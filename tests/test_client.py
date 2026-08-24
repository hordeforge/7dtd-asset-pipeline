"""The fresh-client plumbing: path derivation, deployment, and log classification.

Nothing here launches a client. The launch path is a Steam invocation plus a
wait, and the only logic worth a unit test sits either side of it.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

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
        env = {
            "SEVEN_DAYS_TO_DIE_LOG_DIR": "/elsewhere/logs",
            "SEVEN_DAYS_TO_DIE_MODS_DIR": "/elsewhere/Mods",
        }
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
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(PipelineError):
            client.deploy_mod(Path(temp), Path(temp) / "Mods", "X")

    def test_refuses_a_name_that_traverses_out_of_the_mods_dir(self) -> None:
        """A mod name is a folder name, never a path.

        The name can come from the deployed mod's own ModInfo.xml or an API
        parameter, so a traversal or absolute name must be rejected before it
        reaches the rmtree/mkdir that prepare the destination.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mod = root / "MyMod"
            mod.mkdir()
            (mod / "ModInfo.xml").write_text("<xml/>")
            mods_dir = root / "Mods"
            hostage = root / "hostage"
            hostage.mkdir()
            for name in ("../hostage", "../../hostage", str(root / "elsewhere"), "..", ".", ""):
                with self.assertRaises(PipelineError, msg=name):
                    client.deploy_mod(mod, mods_dir, name)
            self.assertTrue(hostage.is_dir())
            self.assertFalse(mods_dir.exists())

    def test_deploy_resolves_the_mod_name_from_modinfo(self) -> None:
        """`deploy` without --name reads ModInfo.xml through read_mod_name.

        The name lookup lives in `references`; this path once imported it from
        `config`, where it does not exist, and the function-level import hid
        the ImportError until a real deploy ran.
        """
        with tempfile.TemporaryDirectory() as temp:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = client.main(["deploy", temp])
            self.assertEqual(status, 1)
            self.assertIn("cannot parse", stderr.getvalue())


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
        self.assertEqual(set(report.found), {"mod_loaded", "localization_loaded", "atlas_packed"})

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
        text = (
            self.CLEAN
            + """
[MODS] Mod reference for a mod that is not loaded: MyMood
Model has a wrong name: expected myModThing
Loading AssetBundle /x/y.unity3d failed
[Steamworks.NET] SteamAPI_Init() failed. Refer to Valve's documentation
Particle Velocity curves must all be in the same mode
WRN Entity FallingBlock_3 (EntityFallingBlock) fell off the world, pos=1,2,3
"""
        )
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

    def test_a_flood_of_negative_lines_is_capped_not_accumulated(self) -> None:
        """A runaway log reports its first problems and warnings, and stops.

        One broken particle system logs thousands of lines a second; the
        report holds 50 problems and 20 warnings, so the scan keeps only
        those instead of every matching line in the file.
        """
        flood = "\n".join(
            ["Particle Velocity curves must all be in the same mode"] * 500
            + ["NullReferenceException: at Foo.Bar () [0x00000]"] * 100
        )
        text = f"Loaded Mod: MyMod (1.0)\n{self.CLEAN}\n{flood}\n"
        report = client.scan_log_text(text, "MyMod")
        self.assertEqual(len(report.problems), client.PROBLEM_LIMIT)
        self.assertEqual(len(report.warnings), client.WARNING_LIMIT)
        self.assertTrue(
            all(
                k == "particle_curve_mode"
                for k in (line.split(":", 1)[0] for line in report.problems)
            )
        )
        self.assertTrue(all(w.startswith("exception:") for w in report.warnings))
        # The positive markers seen before the flood still count as found.
        self.assertEqual(report.missing_positive, ())


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
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(PipelineError):
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

    def test_a_pid_that_stopped_naming_the_client_is_not_signalled(self) -> None:
        """SIGKILL follows identity, not bare PID liveness.

        Between the SIGTERM grace loop and the kill decision the client can
        exit and the kernel can recycle its PID to an unrelated process; the
        stale id must not receive our signals.
        """
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp:
            proc = Path(temp)
            for pid, argv0 in ((300, "/games/7DaysToDie.exe"), (301, "/bin/bash")):
                (proc / str(pid)).mkdir()
                (proc / str(pid) / "cmdline").write_bytes(argv0.encode() + b"\0")
            self.assertTrue(client._is_client_pid(300, proc))
            self.assertFalse(client._is_client_pid(301, proc))
            self.assertFalse(client._is_client_pid(999999, proc))
            signalled: list[tuple[int, int]] = []
            with patch.object(
                os, "kill", side_effect=lambda pid, sig: signalled.append((pid, sig))
            ):
                client.stop_client([300, 301], grace_seconds=0.05, proc=proc)
            self.assertNotIn(301, [pid for pid, _ in signalled])
            self.assertIn(300, [pid for pid, _ in signalled])

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
            reg.write_text(
                '[Software\\The Fun Pimps]\n"DiscordDisabled_h123"=dword:00000000\n"Other"=dword:1\n'
            )
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
                Path(tmp),
                running="yes",
                session="other-20260823-120000-abc",
                heartbeat=self._stamp(5),
            )
            self.assertEqual(client.lock_holder(path), "other-20260823-120000-abc")

    def test_a_stale_holder_reads_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._lock(
                Path(tmp),
                running="yes",
                session="other-20260823-120000-abc",
                heartbeat=self._stamp(600),
            )
            self.assertIsNone(client.lock_holder(path))

    def test_running_no_and_a_missing_file_both_read_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(client.lock_holder(self._lock(Path(tmp), running="no")))
            self.assertIsNone(client.lock_holder(Path(tmp) / "absent"))

    def test_deploy_and_launch_refuse_while_another_session_holds_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._lock(
                Path(tmp),
                running="yes",
                session="other-20260823-120000-abc",
                heartbeat=self._stamp(5),
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

    def test_deploy_writes_only_when_the_lock_is_free(self) -> None:
        """The guard sits on the write, so a free lock still deploys."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mod"
            (root / "Config").mkdir(parents=True)
            (root / "ModInfo.xml").write_text(
                '<?xml version="1.0"?><xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
            )
            (root / "Config" / "items.xml").write_text("<configs />", encoding="utf-8")
            free = Path(tmp) / "playtest_running"
            free.write_text("running=no\n", encoding="utf-8")
            os.environ[client.LOCK_ENV] = str(free)
            try:
                status = client.main(["deploy", str(root), "--mods-dir", str(Path(tmp) / "Mods")])
            finally:
                del os.environ[client.LOCK_ENV]
            self.assertEqual(status, 0)
            self.assertTrue((Path(tmp) / "Mods/ExampleMod/Config/items.xml").is_file())
            self.assertIsNone(client.lock_holder(free))

    def test_deploy_holds_the_lock_across_the_copy(self) -> None:
        """Refuse-then-copy was check-then-act: the hold must cover the write.

        Between the old refusal and the copy finishing, another session could
        acquire and launch, and the deployment landed in that run. The copy
        now runs inside the held lock, so the record is ours for the whole
        write and released after it.
        """
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mod"
            root.mkdir()
            (root / "ModInfo.xml").write_text(
                '<?xml version="1.0"?><xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
            )
            path = Path(tmp) / "playtest_running"
            seen: list[str | None] = []

            def spy(*args: object, **kwargs: object) -> list[str]:
                seen.append(client.lock_holder(path))
                return []

            os.environ[client.LOCK_ENV] = str(path)
            try:
                with patch.object(client, "deploy_mod", spy):
                    client.main(["deploy", str(root), "--mods-dir", str(Path(tmp) / "Mods")])
            finally:
                del os.environ[client.LOCK_ENV]
            self.assertEqual(len(seen), 1, "the copy never ran")
            holder = seen[0]
            assert holder is not None, "the copy ran while no session held the lock"
            self.assertTrue(holder.startswith("shamway-"))
            self.assertIsNone(client.lock_holder(path), "the lock leaked after the deploy")

    def test_hold_for_write_refuses_over_a_fresh_holder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._lock(Path(tmp), running="yes", session="other-1", heartbeat=self._stamp(5))
            env = {client.LOCK_ENV: str(path)}
            with (
                self.assertRaises(PipelineError) as raised,
                client.hold_for_write("deploy into the shared Mods folder", env=env),
            ):
                pass
            self.assertIn("other-1", str(raised.exception))
            # The refusal must not have clobbered the holder's record.
            self.assertEqual(client.lock_holder(path), "other-1")

    def test_the_holding_session_can_write_through_hold_for_write(self) -> None:
        """PLAYTEST_SESSION_ID names this run's holder, so the write proceeds.

        Taking over under our own id must hold, run the body, and leave a
        released record behind — not refuse against ourselves.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = self._lock(Path(tmp), running="yes", session="mine-1", heartbeat=self._stamp(5))
            env = {client.LOCK_ENV: str(path), client.LOCK_SESSION_ENV: "mine-1"}
            inside: list[str | None] = []
            with client.hold_for_write("deploy into the shared Mods folder", env=env):
                inside.append(client.lock_holder(path))
            self.assertEqual(inside, ["mine-1"], "the body ran while nobody held the lock")
            self.assertIsNone(client.lock_holder(path), "the hold leaked past the write")

    def test_holding_refuses_over_another_fresh_holder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._lock(Path(tmp), running="yes", session="other-1", heartbeat=self._stamp(5))
            with self.assertRaises(PipelineError), client.held_lock("mine-1", path):
                pass

    def test_release_leaves_a_reclaimed_record_alone(self) -> None:
        """Release clears only a record that names us, never a foreign claim.

        While this session sat frozen past the stale window, another session
        may have taken the documented reclaim. Publishing running=no on the
        way out — the old code did whenever the record did not read as ours —
        erases their live hold and lets a third session start over their run.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "playtest_running"
            with client.held_lock("mine-1", path):
                self._lock(Path(tmp), running="yes", session="other-2", heartbeat=self._stamp(600))
            fields = dict(client.read_lock(path))
            self.assertEqual(fields.get("running"), "yes")
            self.assertEqual(fields.get("session"), "other-2")

    def test_heartbeat_does_not_restamp_over_a_reclaiming_session(self) -> None:
        """The heartbeat re-validates ownership under the flock before writing."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "playtest_running"
            with (
                patch.object(client, "LOCK_HEARTBEAT_SECONDS", 0.02),
                client.held_lock("mine-1", path),
            ):
                # The documented reclaim: our record aged out and another
                # session took over while we were suspended.
                self._lock(
                    Path(tmp),
                    running="yes",
                    session="other-2",
                    acquired=self._stamp(600),
                    heartbeat=self._stamp(0),
                )
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    if dict(client.read_lock(path)).get("session") != "other-2":
                        self.fail("the heartbeat clobbered the reclaiming session's record")
                    time.sleep(0.01)
                time.sleep(0.1)
            self.assertEqual(dict(client.read_lock(path)).get("session"), "other-2")

    def test_concurrent_writers_publish_whole_records_and_leave_no_temporaries(self) -> None:
        """Two lock writers must never share a temp file.

        A fixed `<lock>.tmp` let the heartbeat thread and an acquirer truncate
        one temp file together: readers saw interleaved bytes, and the loser
        of the rename pair died on FileNotFoundError mid-heartbeat.
        """
        import threading as threading_module

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "playtest_running"
            failures: list[BaseException] = []

            def write(tag: str) -> None:
                try:
                    for _ in range(40):
                        client._write_lock(
                            path,
                            {
                                "running": "yes",
                                "session": f"{tag}-{client.new_session_id('w')}",
                                "acquired": "2026-08-24T00:00:00Z",
                                "heartbeat": "2026-08-24T00:00:00Z",
                            },
                        )
                except BaseException as exc:  # noqa: BLE001 - collected below
                    failures.append(exc)

            threads = [
                threading_module.Thread(target=write, args=(tag,)) for tag in ("alpha", "beta")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(failures, [])
            fields = client.read_lock(path)
            self.assertIn(fields.get("session", "").split("-", 1)[0], {"alpha", "beta"})
            self.assertEqual(
                [entry.name for entry in Path(tmp).iterdir() if ".tmp." in entry.name],
                [],
                "a crashed or raced writer left its temporary behind",
            )


class PortabilityTests(unittest.TestCase):
    """The CLI claims to be portable (docs/getting-started/quickstart.md: Linux, macOS, Windows).

    `fcntl` exists only on Unix, so it must never sit at module scope of
    anything the console script imports: on Windows one top-level import turns
    every command, even `--help`, into ModuleNotFoundError.
    """

    def _run_blocked(self, body: str) -> subprocess.CompletedProcess[str]:
        """Run `body` in a fresh interpreter where importing fcntl fails.

        `sys.modules[name] = None` is the documented way to make an import of
        that name raise ModuleNotFoundError, which stands in for a platform
        (Windows) where the module does not exist at all.
        """
        script = "\n".join(
            (
                "import sys",
                "sys.modules['fcntl'] = None",
                body,
            )
        )
        root = Path(__file__).resolve().parent.parent
        env = dict(os.environ)
        source = str(root / "src")
        env["PYTHONPATH"] = (
            f"{source}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else source
        )
        return subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=False
        )

    def test_the_cli_imports_without_fcntl(self) -> None:
        result = self._run_blocked(
            "import sevendtd_asset_pipeline.client\n"
            "import sevendtd_asset_pipeline.cli\n"
            "print('IMPORTED')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("IMPORTED", result.stdout)

    def test_holding_the_lock_without_fcntl_is_a_named_error(self) -> None:
        result = self._run_blocked(
            "import tempfile\n"
            "from pathlib import Path\n"
            "from sevendtd_asset_pipeline import client\n"
            "with tempfile.TemporaryDirectory() as tmp:\n"
            "    try:\n"
            "        with client.held_lock('mine-1', Path(tmp) / 'lock'):\n"
            "            pass\n"
            "    except client.PipelineError as exc:\n"
            "        print('PIPELINE-ERROR:', exc)\n"
            "    else:\n"
            "        print('NO-ERROR')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PIPELINE-ERROR:", result.stdout)
        self.assertNotIn("NO-ERROR", result.stdout)

    def test_writes_degrade_to_refuse_only_without_fcntl(self) -> None:
        """A native Windows client keeps its deploy; it just cannot hold.

        With no flock there is no protocol to serialize through, so the write
        guard falls back to the refuse-only check instead of taking the
        deployment away from that host entirely.
        """
        result = self._run_blocked(
            "import tempfile\n"
            "from pathlib import Path\n"
            "from sevendtd_asset_pipeline import client\n"
            "with tempfile.TemporaryDirectory() as tmp:\n"
            "    lock = Path(tmp) / 'lock'\n"
            "    lock.write_text('running=no\\n', encoding='utf-8')\n"
            "    env = {client.LOCK_ENV: str(lock)}\n"
            "    with client.hold_for_write('deploy into the shared Mods folder', env=env):\n"
            "        print('WROTE-FREE:', client.read_lock(lock))\n"
            "    lock.write_text(\n"
            "        'running=yes\\nsession=other-1\\nheartbeat='\n"
            "        + __import__('datetime').datetime.now(\n"
            "            __import__('datetime').UTC\n"
            "        ).strftime('%Y-%m-%dT%H:%M:%SZ') + '\\n',\n"
            "        encoding='utf-8',\n"
            "    )\n"
            "    try:\n"
            "        with client.hold_for_write('deploy into the shared Mods folder', env=env):\n"
            "            print('WROTE-HELD')\n"
            "    except client.PipelineError as exc:\n"
            "        print('REFUSED:', exc)\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WROTE-FREE:", result.stdout)
        self.assertIn("REFUSED: another session holds", result.stdout)
        self.assertNotIn("WROTE-HELD", result.stdout)


class CliTests(unittest.TestCase):
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


class FreshClientRunTests(unittest.TestCase):
    """A muted timed run must unmute even when the run fails part-way.

    WirePlumber persists the game stream's mute, so a run that dies between
    muting and the scheduled unmute would otherwise silence every later
    session of this game, not just this run.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.lock = self.root / "playtest_running"
        self.steam = self.root / "steam-stub"
        self.steam.write_text("#!/bin/sh\nexit 0\n")
        self.steam.chmod(0o755)
        os.environ[client.LOCK_ENV] = str(self.lock)
        # fresh_client_run derives the log dir from the game dir unless one is
        # given; the tests patch the log functions, but the derivation itself
        # still runs first and needs a usable answer.
        self.logs = self.root / "logs"
        self.logs.mkdir()
        (self.logs / "output_log_client__test.txt").write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        os.environ.pop(client.LOCK_ENV, None)
        self.temporary.cleanup()

    def _run(
        self, *, sleep_side_effect: BaseException | None = None, stop: bool = False
    ) -> client.AcceptanceRun:
        self.calls: list[str] = []
        # The run window is recorded, never slept: two seconds of real idle per
        # case bought nothing the recorded value does not pin.
        self.slept: list[float] = []
        report = client.LogReport(log="log", mod_name=None)

        def fake_mute(muted: bool, wait_seconds: int = 60) -> list[int]:
            self.calls.append("mute" if muted else "unmute")
            return [7] if muted else []

        def fake_stop(pids: list[int]) -> None:
            self.calls.append("stop")
            if stop:
                raise RuntimeError("the stop failed")

        def fake_sleep(seconds: float) -> None:
            self.slept.append(seconds)
            if sleep_side_effect is not None:
                raise sleep_side_effect

        patches = [
            mock.patch.object(client, "set_client_mute", side_effect=fake_mute),
            mock.patch.object(client, "running_client_pids", return_value=[]),
            mock.patch.object(client, "stop_client", side_effect=fake_stop),
            mock.patch.object(
                client, "latest_client_log", return_value=self.root / "client-log.txt"
            ),
            mock.patch.object(client, "scan_log", return_value=report),
            mock.patch("time.sleep", side_effect=fake_sleep),
        ]
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            return client.fresh_client_run(
                game_dir=None,
                mod_name="ExampleMod",
                run_seconds=2,
                mute=True,
                steam_bin=str(self.steam),
                log_dir=self.logs,
            )

    def test_a_bounded_muted_run_unmutes_before_stopping_the_client(self) -> None:
        # The unmute must precede the stop: once the client exits there is no
        # stream to un-mute, and WirePlumber would save the muted state.
        run = self._run()
        self.assertEqual(["mute", "unmute", "stop"], self.calls)
        self.assertEqual([2], self.slept, "the requested run window is what was waited")
        self.assertTrue(run.unmuted_again)
        self.assertTrue(run.muted)

    def test_a_failure_mid_run_still_unmutes(self) -> None:
        # The interrupt lands inside the run window; the finally must undo the
        # mute before the error reaches the caller.
        with self.assertRaises(KeyboardInterrupt):
            self._run(sleep_side_effect=KeyboardInterrupt())
        self.assertIn("unmute", self.calls)
        self.assertEqual(["mute", "unmute"], self.calls)

    def test_a_failed_stop_after_the_unmute_does_not_unmute_twice(self) -> None:
        with self.assertRaises(RuntimeError):
            self._run(stop=True)
        # The scheduled unmute already happened; the cleanup path must not
        # report or retry it as if it had been skipped.
        self.assertEqual(["mute", "unmute", "stop"], self.calls)


if __name__ == "__main__":
    unittest.main()
