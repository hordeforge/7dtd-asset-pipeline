"""The fresh-client plumbing: path derivation, deployment, and log classification.

Nothing here launches a client. The launch path is a Steam invocation plus a
wait, and the only logic worth a unit test sits either side of it.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from sevendtd_asset_pipeline import client
from sevendtd_asset_pipeline.errors import PipelineError


class LocationTests(unittest.TestCase):
    def test_derives_proton_paths_from_a_steam_library_game_dir(self) -> None:
        game = Path("/games/SteamLibrary/steamapps/common/7 Days To Die")
        self.assertEqual(client.steamapps_dir(game), Path("/games/SteamLibrary/steamapps"))
        self.assertEqual(
            client.compatdata_dir(game), Path("/games/SteamLibrary/steamapps/compatdata/251570")
        )
        user_data = client.proton_user_data_dir(game)
        assert user_data is not None
        self.assertTrue(str(user_data).endswith("AppData/Roaming/7DaysToDie"))
        self.assertEqual(client.client_log_dir(game, env={}), user_data / "logs")
        self.assertEqual(client.user_mods_dir(game, env={}), user_data / "Mods")

    def test_environment_overrides_win(self) -> None:
        env = {"SEVEN_DAYS_TO_DIE_LOG_DIR": "/elsewhere/logs", "SEVEN_DAYS_TO_DIE_MODS_DIR": "/elsewhere/Mods"}
        self.assertEqual(client.client_log_dir(None, env=env), Path("/elsewhere/logs"))
        self.assertEqual(client.user_mods_dir(None, env=env), Path("/elsewhere/Mods"))

    def test_non_steam_game_dir_needs_an_explicit_override(self) -> None:
        with self.assertRaises(PipelineError):
            client.client_log_dir(Path("/opt/7dtd"), env={})
        with self.assertRaises(PipelineError):
            client.user_mods_dir(None, env={})

    def test_launch_goes_through_steam_with_test_args(self) -> None:
        command = client.launch_command("steam", ("-extra",))
        self.assertEqual(command[:3], ["steam", "-applaunch", "251570"])
        self.assertIn("-skipintro", command)
        self.assertIn("-skipnewsscreen=true", command)
        self.assertEqual(command[-1], "-extra")


class DeployTests(unittest.TestCase):
    def test_copies_only_the_deployable_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mod = root / "MyMod"
            (mod / "Config").mkdir(parents=True)
            (mod / "Config/items.xml").write_text("<configs/>")
            (mod / "Config/Localization.csv").write_text("Key,english\n")
            (mod / "Resources").mkdir()
            (mod / "Resources/mymod.unity3d").write_bytes(b"UnityFS")
            (mod / "UIAtlases/ItemIconAtlas").mkdir(parents=True)
            (mod / "UIAtlases/ItemIconAtlas/x.png").write_bytes(b"\x89PNG")
            (mod / "UIAtlases/ItemIconAtlas/x.png.meta").write_text("guid: 1")
            (mod / "ModInfo.xml").write_text("<xml/>")
            (mod / "MyMod.dll").write_bytes(b"MZ")
            (mod / ".shamway.toml").write_text("schema_version = 1")
            (mod / "assets-src").mkdir()
            (mod / "assets-src/prompt.txt").write_text("secret prompt")
            (mod / "tools/shamway").mkdir(parents=True)
            mods_dir = root / "Mods"

            copied = client.deploy_mod(mod, mods_dir, "MyMod")

            deployed = mods_dir / "MyMod"
            self.assertEqual(
                set(copied), {"ModInfo.xml", "Config", "Resources", "UIAtlases", "MyMod.dll"}
            )
            self.assertTrue((deployed / "Config/Localization.csv").is_file())
            self.assertTrue((deployed / "Resources/mymod.unity3d").is_file())
            self.assertTrue((deployed / "UIAtlases/ItemIconAtlas/x.png").is_file())
            self.assertFalse((deployed / "UIAtlases/ItemIconAtlas/x.png.meta").exists())
            self.assertFalse((deployed / ".shamway.toml").exists())
            self.assertFalse((deployed / "assets-src").exists())
            self.assertFalse((deployed / "tools").exists())

    def test_replaces_a_stale_deployment_and_refuses_without_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mod = root / "MyMod"
            mod.mkdir()
            (mod / "ModInfo.xml").write_text("<xml/>")
            mods_dir = root / "Mods"
            stale = mods_dir / "MyMod/Resources"
            stale.mkdir(parents=True)
            (stale / "old.unity3d").write_bytes(b"old")

            with self.assertRaises(PipelineError):
                client.deploy_mod(mod, mods_dir, "MyMod", replace=False)
            client.deploy_mod(mod, mods_dir, "MyMod")
            self.assertFalse((stale / "old.unity3d").exists())

    def test_refuses_a_mod_without_modinfo(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(PipelineError):
                client.deploy_mod(Path(temp), Path(temp) / "Mods", "X")


class LogScanTests(unittest.TestCase):
    CLEAN = """
[MODS] Loading localization from mod: MyMod
Loaded Mod: MyMod (1.0)
UIAtlas ItemIconAtlas: Pack took 1234 us
Awake IsFocused: True
"""

    def test_a_clean_log_with_every_positive_marker_passes(self) -> None:
        report = client.scan_log_text(self.CLEAN, "MyMod")
        self.assertTrue(report.ok, report.as_dict())
        self.assertEqual(
            set(report.found), {"mod_loaded", "localization_loaded", "atlas_packed"}
        )

    def test_missing_positive_markers_fail_when_a_mod_is_named(self) -> None:
        report = client.scan_log_text("Loaded Mod: MyMod (1.0)\n", "MyMod")
        self.assertFalse(report.ok)
        self.assertEqual(set(report.missing_positive), {"localization_loaded", "atlas_packed"})

    def test_positive_markers_are_informational_without_a_mod_name(self) -> None:
        report = client.scan_log_text("nothing here\n", None)
        self.assertTrue(report.ok)
        self.assertEqual(report.missing_positive, ())

    def test_another_mods_lines_do_not_count(self) -> None:
        report = client.scan_log_text("Loaded Mod: OtherMod (1.0)\n", "MyMod")
        self.assertIn("mod_loaded", report.missing_positive)

    def test_negative_markers_are_problems(self) -> None:
        text = self.CLEAN + """
[MODS] Mod reference for a mod that is not loaded: MyMood
Model has a wrong name: expected myModThing
Loading AssetBundle /x/y.unity3d failed
[Steamworks.NET] SteamAPI_Init() failed. Refer to Valve's documentation
Particle Velocity curves must all be in the same mode
WRN Entity FallingBlock_3 (EntityFallingBlock) fell off the world, pos=1,2,3
"""
        report = client.scan_log_text(text, "MyMod")
        self.assertFalse(report.ok)
        keys = {line.split(":", 1)[0] for line in report.problems}
        self.assertEqual(
            keys,
            {
                "mod_reference_not_loaded",
                "model_wrong_name",
                "bundle_load_failed",
                "steam_api_failed",
                "particle_curve_mode",
                "falling_block",
            },
        )

    def test_as_dict_is_json_shaped(self) -> None:
        data = client.scan_log_text(self.CLEAN, "MyMod").as_dict()
        self.assertEqual(data["ok"], True)
        self.assertIsInstance(data["found"], dict)
        self.assertIsInstance(data["problems"], list)


class LatestLogTests(unittest.TestCase):
    def test_requires_a_log_written_after_the_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            logs = Path(temp)
            old = logs / "output_log_client__2026-08-22__10-00-00.txt"
            old.write_text("old")
            past = time.time() - 3600
            os.utime(old, (past, past))
            self.assertEqual(client.latest_client_log(logs), old)
            with self.assertRaises(PipelineError):
                client.latest_client_log(logs, written_after=time.time() - 60)
            new = logs / "output_log_client__2026-08-23__10-00-00.txt"
            new.write_text("new")
            self.assertEqual(client.latest_client_log(logs, written_after=time.time() - 60), new)

    def test_no_logs_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(PipelineError):
                client.latest_client_log(Path(temp))


class ProcessAndAudioTests(unittest.TestCase):
    def test_matches_client_executables_not_substrings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            proc = Path(temp)
            for pid, argv0 in (
                (100, "Z:\\games\\7DaysToDie.exe"),
                (101, "/opt/7DaysToDie_EAC.exe"),
                (102, "/srv/7DaysToDieServer.x86_64"),
                (103, "/usr/bin/python3 tool 7DaysToDie_Data/x"),
            ):
                (proc / str(pid)).mkdir()
                (proc / str(pid) / "cmdline").write_bytes(argv0.encode() + b"\0--arg\0")
            (proc / "self").mkdir()
            self.assertEqual(client.running_client_pids(proc), [100, 101])

    def test_sink_inputs_are_selected_by_application_name_or_binary(self) -> None:
        inputs = [
            {"index": 3, "properties": {"application.name": "Firefox"}},
            {"index": 7, "properties": {"application.name": "7DaysToDie.exe"}},
            {"index": 9, "properties": {"application.process.binary": "7daystodie.exe"}},
            {"index": 11, "properties": "garbage"},
        ]
        self.assertEqual(client.client_sink_inputs(inputs), [7, 9])

    def test_saved_wireplumber_mute_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "stream-properties"
            self.assertIsNone(client.saved_mute_state(state))
            state.write_text('Output/Audio:application.name:7DaysToDie.exe={"mute":true}\n')
            self.assertTrue(client.saved_mute_state(state))
            state.write_text('Output/Audio:application.name:7DaysToDie.exe={"mute":false}\n')
            self.assertFalse(client.saved_mute_state(state))

    def test_discord_pref_is_rewritten_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            reg = Path(temp) / "user.reg"
            reg.write_text('[Software\\The Fun Pimps]\n"DiscordDisabled_h123"=dword:00000000\n"Other"=dword:1\n')
            self.assertTrue(client.disable_discord_integration(reg))
            self.assertIn('"DiscordDisabled_h123"=dword:00000001', reg.read_text())
            self.assertIn('"Other"=dword:1', reg.read_text())
            reg.write_text("nothing\n")
            self.assertFalse(client.disable_discord_integration(reg))


class LockTests(unittest.TestCase):
    """The shared-client lock this repository reads but does not own.

    Regression cover for a client deployed into someone else's run: the
    process check is blind between two runs of an orchestrator that releases
    and re-acquires, and the lock is the only thing that is not.
    """

    def _lock(self, root: Path, **fields: str) -> Path:
        path = root / "playtest_running"
        path.write_text("".join(f"{k}={v}\n" for k, v in fields.items()), encoding="utf-8")
        return path

    def _stamp(self, age_seconds: float) -> str:
        from datetime import UTC, datetime, timedelta

        moment = datetime.now(UTC) - timedelta(seconds=age_seconds)
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_a_fresh_holder_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._lock(
                Path(tmp), running="yes", session="other-20260823-120000-abc", heartbeat=self._stamp(5)
            )
            self.assertEqual(client.lock_holder(path), "other-20260823-120000-abc")

    def test_a_stale_holder_reads_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._lock(
                Path(tmp), running="yes", session="other-20260823-120000-abc", heartbeat=self._stamp(600)
            )
            self.assertIsNone(client.lock_holder(path))

    def test_running_no_and_a_missing_file_both_read_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(client.lock_holder(self._lock(Path(tmp), running="no")))
            self.assertIsNone(client.lock_holder(Path(tmp) / "absent"))

    def test_deploy_and_launch_refuse_while_another_session_holds_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._lock(
                Path(tmp), running="yes", session="other-20260823-120000-abc", heartbeat=self._stamp(5)
            )
            env = {client.LOCK_ENV: str(path)}
            with self.assertRaises(PipelineError) as raised:
                client.refuse_while_held("deploy into the shared Mods folder", env=env)
            self.assertIn("other-20260823-120000-abc", str(raised.exception))

    def test_the_holding_session_is_not_refused_against_itself(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._lock(Path(tmp), running="yes", session="mine-1", heartbeat=self._stamp(5))
            env = {client.LOCK_ENV: str(path), client.LOCK_SESSION_ENV: "mine-1"}
            client.refuse_while_held("launch a client", env=env)

    def test_holding_writes_a_record_and_releases_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "playtest_running"
            with client.held_lock("mine-1", path):
                self.assertEqual(client.lock_holder(path), "mine-1")
            self.assertIsNone(client.lock_holder(path))
            self.assertIn("running=no", path.read_text(encoding="utf-8"))

    def test_holding_refuses_over_another_fresh_holder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._lock(Path(tmp), running="yes", session="other-1", heartbeat=self._stamp(5))
            with self.assertRaises(PipelineError):
                with client.held_lock("mine-1", path):
                    pass


class CliTests(unittest.TestCase):
    def test_deploy_resolves_the_mod_name_through_the_module_that_has_it(self) -> None:
        """`client deploy` once imported read_mod_name from the wrong module."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mod"
            (root / "Config").mkdir(parents=True)
            (root / "ModInfo.xml").write_text(
                '<?xml version="1.0"?><xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
            )
            (root / "Config" / "items.xml").write_text("<configs />", encoding="utf-8")
            mods = Path(tmp) / "Mods"
            free = Path(tmp) / "playtest_running"
            free.write_text("running=no\n", encoding="utf-8")
            os.environ[client.LOCK_ENV] = str(free)
            try:
                code = client.main(["deploy", str(root), "--mods-dir", str(mods)])
            finally:
                del os.environ[client.LOCK_ENV]
            self.assertEqual(code, 0)
            self.assertTrue((mods / "ExampleMod" / "Config" / "items.xml").is_file())

    def test_where_without_a_game_dir_prints_nulls(self) -> None:
        import contextlib
        import io
        import json

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = client.main(["where", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertIn("launch", data)


if __name__ == "__main__":
    unittest.main()
