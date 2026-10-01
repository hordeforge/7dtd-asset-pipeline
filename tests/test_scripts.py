"""The host-script registry: what a mod reaches through `shamway script`.

`scripts.SCRIPTS` is a published surface like docs.TOPICS and
generators.GENERATORS: AGENTS.md says a new host script goes in it, and a
consumer calls it from an installed package with no checkout of this
repository. So every registered name must resolve to real packaged bytes, the
packaged copies must equal the repository's own (they have drifted before, as
docs/ had), and the listing must name what exists.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import ClassVar

import sevendtd_asset_pipeline
from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.scripts import SCRIPTS, main, path


class ScriptRegistryTests(unittest.TestCase):
    def test_every_registered_script_resolves_to_real_bytes(self) -> None:
        for name, (_filename, summary) in SCRIPTS.items():
            with self.subTest(name):
                self.assertTrue(summary, "a script must say what it is for")
                script = path(name)
                self.assertTrue(script.is_file(), str(script))
                self.assertTrue(script.read_bytes().startswith(b"#!"), str(script))

    def test_packaged_scripts_are_the_repo_scripts(self) -> None:
        """setup.py copies scripts/*.sh and scripts/*.py into the package on every build.

        A wheel built from a stale tree ships yesterday's installer; equality
        here is cheap to keep and expensive to lose.

        The file list comes from the directory rather than a literal, for the
        reason setup.py globs both suffixes: the shell scripts keep their JSON
        and import probes in sibling .py files so each file stays one language,
        and a staged installer whose helper did not come along resolves
        nothing. A hand-kept list is a list that forgets one.
        """
        source_root = Path(sevendtd_asset_pipeline.__file__).resolve().parents[2] / "scripts"
        if not source_root.is_dir():
            self.skipTest("running from a packaged install without the repo scripts/")
        packaged_root = Path(sevendtd_asset_pipeline.__file__).resolve().parent / "scripts"
        if not packaged_root.is_dir():
            # A plain checkout stages nothing: MANIFEST.in prunes the staged
            # copies from the sdist, so the build regenerates them in its own
            # tree and `scripts.path()` falls back to scripts/ here. There is
            # no second copy to drift. The release workflow compares the built
            # wheel against the tree, which is where the two can differ.
            self.skipTest("nothing staged in this tree; the wheel is checked at release")
        staged = sorted(
            path.name for suffix in ("*.sh", "*.py") for path in source_root.glob(suffix)
        )
        self.assertTrue(staged, "scripts/ carries no script to stage")
        # Every registered name must be among them, so the registry cannot
        # point at a file the build does not ship.
        for filename in (filename for filename, _summary in SCRIPTS.values()):
            self.assertIn(filename, staged)
        for filename in staged:
            with self.subTest(filename):
                self.assertEqual(
                    (source_root / filename).read_bytes(),
                    (packaged_root / filename).read_bytes(),
                    f"{filename} differs between scripts/ and the packaged copy; "
                    "run `make stage` (or rebuild the wheel) so both readers see one script",
                )

    def test_an_unknown_script_lists_the_known_ones(self) -> None:
        with self.assertRaisesRegex(PipelineError, "install-tools"):
            path("no-such-script")

    def test_install_tools_extras_installs_gltfpack_compressonator_and_assetripper(
        self,
    ) -> None:
        source = Path(__file__).resolve().parents[1] / "scripts" / "install-tools.sh"
        text = source.read_text(encoding="utf-8")
        extras = text[text.index("install_extras()") :]
        extras = extras[: extras.index("\n}\n") + 2]
        self.assertIn("install_binary_release gltfpack", extras)
        self.assertIn("install_binary_release compressonatorcli", extras)
        self.assertIn("install_assetripper", extras)

    def test_apt_collection_keeps_missing_optional_zig_out_of_the_install(self) -> None:
        source = Path(__file__).resolve().parents[1] / "scripts/install-tools.sh"
        text = source.read_text(encoding="utf-8")
        body = text[text.index("collect_apt()") : text.index("\ncollect_dnf()")]
        bash = shutil.which("bash")
        assert bash is not None
        shell = (
            """have() { [ "$1" != zig ]; }
has_python_311() { return 0; }
apt-cache() { [ "$ZIG_AVAILABLE" = 1 ]; }
PACKAGES=()
WITH_AUTHORING=0 WITH_UNITY_PREREQS=0 WITH_DESKTOP_CAPTURE=0 WITH_RESEARCH=0
"""
            + body
            + '\ncollect_apt\nprintf "%s\\n" "${PACKAGES[@]}"'
        )
        for available in ("0", "1"):
            with self.subTest(available=available):
                done = subprocess.run(
                    [bash, "-c", shell],
                    env={**os.environ, "ZIG_AVAILABLE": available},
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(available == "1", "zig" in done.stdout.splitlines())

    def test_install_unityz_upgrades_an_older_than_pin_binary(self) -> None:
        """A host with 0.1.2+ already on PATH used to skip the pin forever."""
        source = Path(__file__).resolve().parents[1] / "scripts" / "install-unityz.sh"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn(
            "already satisfies the >=0.1.2 pipeline contract",
            text,
        )
        self.assertIn("already meets the pinned", text)
        self.assertIn("upgrading unityz", text)
        self.assertIn("UNITYZ_PINNED_VERSION", text)

    def test_docs_quote_the_pinned_unityz_release_and_commit(self) -> None:
        """A setup page naming an old pin sends a host to the wrong release.

        The pin moves in `install-unityz.sh` alone, so the pages drift: setup.md
        still named 0.1.3 and a commit from three pins ago, and nobody learns
        until they install a reader older than the writer's. Only claims that
        say "pinned" are checked, so a historical or measured citation in the
        research pages stays a citation.
        """
        root = Path(__file__).resolve().parents[1]
        installer = (root / "scripts" / "install-unityz.sh").read_text(encoding="utf-8")
        pinned = re.search(r'^UNITYZ_PINNED_VERSION="([^"]+)"', installer, re.M)
        commit = re.search(r'^UNITYZ_PINNED_COMMIT="([^"]+)"', installer, re.M)
        assert pinned and commit, "install-unityz.sh declares no pinned version and commit"
        pages = (*sorted((root / "docs").rglob("*.md")), root / "README.md")
        versioned: set[str] = set()
        committed: set[str] = set()
        for page in pages:
            text = page.read_text(encoding="utf-8")
            with self.subTest(page=page.name):
                for match in re.finditer(r"pinned unityz (\d+\.\d+\.\d+)", text):
                    versioned.add(match.group(1))
                    self.assertEqual(
                        match.group(1),
                        pinned.group(1),
                        f"{page.name} names pinned unityz {match.group(1)}; "
                        f"install-unityz.sh pins {pinned.group(1)}",
                    )
                for match in re.finditer(r"pinned commit \(`([0-9a-f]{40})`\)", text):
                    committed.add(match.group(1))
                    self.assertEqual(
                        match.group(1),
                        commit.group(1),
                        f"{page.name} names a pinned commit the installer no longer pins",
                    )
        # A phrase that stops appearing everywhere leaves the loops above with
        # nothing to iterate, and a doc drift test that checks nothing is worse
        # than no test: the next pin moves and the pages stay stale.
        self.assertEqual(
            {pinned.group(1)},
            versioned,
            "no documentation page states the pinned unityz version the installer pins",
        )
        self.assertEqual(
            {commit.group(1)},
            committed,
            "no documentation page states the pinned commit the installer pins",
        )

    def test_playtest_acceptance_refuses_mixed_visual_suites(self) -> None:
        """Load, prefab-look, and block-place must not share one PLAYTEST_SUITE."""
        source = Path(__file__).resolve().parents[1] / "scripts" / "playtest-acceptance.sh"
        text = source.read_text(encoding="utf-8")
        self.assertIn("refusing mixed visual suites", text)
        self.assertIn("*_look", text)
        self.assertIn("*_block_*", text)
        synth = Path(__file__).resolve().parents[1] / "scripts" / "playtest-synthesized.sh"
        self.assertIn("shamwayselftest_editorless", synth.read_text(encoding="utf-8"))

    def test_spawned_entity_look_requires_collision_and_ground_evidence(self) -> None:
        """A renderer-only success must not hide broken entity physics."""
        synth = Path(__file__).resolve().parents[1] / "scripts" / "playtest-synthesized.sh"
        text = synth.read_text(encoding="utf-8")
        assertion = (
            'grep -qE "motion_${LOOK_STEM}: render-probe .*collisionReady=True.*groundReady=True"'
        )
        self.assertIn(assertion, text)
        self.assertLess(text.index(assertion), text.index("if ((FAILED)); then"))
        self.assertIn("WALK_ENTITY_LOOK=1", text)
        self.assertIn("surfaceHit", text)
        self.assertIn("the $LOOK_STEM prefab staged", text)

    def test_the_predates_message_renders_both_instants_in_utc(self) -> None:
        """The client-log freshness failure prints two instants; local time collapses them.

        At a fall-back the host clock repeats an hour, so two instants an hour
        apart in Europe/Warsaw (2026-10-25 00:30Z and 01:30Z) render as the
        same local "02:30" and the printed "predates" reads as a contradiction
        in the one message that explains a red run.
        """
        synth = Path(__file__).resolve().parents[1] / "scripts" / "playtest-synthesized.sh"
        text = synth.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"date -d \"@\$\{?[A-Z_]+\}?")
        date = shutil.which("date")
        if date is None:
            self.skipTest("no date(1) on PATH to render the two instants with")
        earlier, later = 1792888200, 1792891800  # 2026-10-25 00:30Z and 01:30Z

        def render(args: list[str], zone: str | None = None) -> str:
            env = dict(os.environ) if zone is None else {**os.environ, "TZ": zone}
            return subprocess.run(
                [date, *args], env=env, capture_output=True, text=True, check=True
            ).stdout.strip()

        def epoch(stamp: int) -> list[str]:
            return ["-r", str(stamp)] if sys.platform == "darwin" else ["-d", f"@{stamp}"]

        local = [render([*epoch(stamp), "+%H:%M"], "Europe/Warsaw") for stamp in (earlier, later)]
        utc = [render(["-u", *epoch(stamp), "+%H:%M"]) for stamp in (earlier, later)]
        self.assertEqual(local[0], local[1], "the zone must really repeat that hour here")
        self.assertNotEqual(utc[0], utc[1], "UTC is what the message must render")

    def test_the_listing_names_every_registered_script(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, main(["--list"]))
        text = out.getvalue()
        for name, (_filename, summary) in SCRIPTS.items():
            self.assertIn(name, text)
            self.assertIn(summary, text)
        self.assertIn("--path", text)


class HostLocaleTests(unittest.TestCase):
    """The host scripts under a locale that is not US English.

    A helper that reads a path out of JSON and hands it to the shell has to
    produce the same text whatever `LC_ALL` says, and the suite-id fold in
    `playtest-synthesized.sh` has to be the ASCII one the orchestrator applies.
    Both run here with a C locale forced, which is the environment in which
    CPython hands a script ASCII stdio.
    """

    SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
    C_LOCALE: ClassVar[dict[str, str]] = {
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
    }
    BASH = shutil.which("bash") or "/bin/bash"

    def _run(
        self, script: str, *arguments: str, stdin: bytes = b""
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(self.SCRIPTS_DIR / script), *arguments],
            input=stdin,
            capture_output=True,
            env={**os.environ, **self.C_LOCALE},
            check=False,
        )

    def test_json_field_round_trips_a_non_ascii_path(self) -> None:
        path = "/home/josé/Meine Mod/Mods"
        payload = json.dumps({"log_dir": path}).encode("utf-8")
        done = self._run("json_field.py", "log_dir", stdin=payload)
        self.assertEqual(0, done.returncode, done.stderr.decode("utf-8", "replace"))
        self.assertEqual(f"{path}\n", done.stdout.decode("utf-8"))

    def test_json_field_names_a_producer_that_is_not_writing_utf8(self) -> None:
        """A cp1252 console piping into the script used to yield a mangled path
        with no diagnostic, and the shell then wrote to whatever that was."""
        done = self._run("json_field.py", "log_dir", stdin=b'{"log_dir":"caf\xe9"}')
        self.assertEqual(1, done.returncode)
        self.assertIn("not UTF-8", done.stderr.decode("utf-8", "replace"))

    def test_a_release_asset_name_with_non_ascii_matches_its_selector(self) -> None:
        name = "blender-café.tar.xz"
        payload = json.dumps(
            {
                "assets": [
                    {
                        "name": name,
                        "browser_download_url": "https://github.com/o/r/releases/download/v1/x",
                    }
                ]
            }
        ).encode("utf-8")
        done = self._run("github_asset_url.py", "--name", name, stdin=payload)
        self.assertEqual(0, done.returncode, done.stderr.decode("utf-8", "replace"))
        self.assertIn(b"download/v1/x", done.stdout)

    def test_suite_ids_fold_to_ascii_case_whatever_the_locale_says(self) -> None:
        """`${var,,}` lowercases through LC_CTYPE, and a Turkish host turns the
        I in `IStem` into a dotless i, naming a suite the orchestrator never
        runs. The helper is extracted from the script and called under a C
        locale, which is the ASCII fold a suite id is made of; the letters
        outside ASCII are left alone rather than mangled by whichever locale
        the host happens to run."""
        source = (self.SCRIPTS_DIR / "playtest-synthesized.sh").read_text(encoding="utf-8")
        body = source[source.index("ascii_lower()") :]
        body = body[: body.index("\n}\n") + 2]
        done = subprocess.run(
            [self.BASH, "-c", f'{body}\nascii_lower "ShamwayISTem_ÄÖÜ"'],
            capture_output=True,
            env={**os.environ, **self.C_LOCALE},
            check=True,
        )
        self.assertEqual("shamwayistem_ÄÖÜ", done.stdout.decode("utf-8"))

    def test_the_capture_loop_does_not_sort_timestamps_through_the_locale(self) -> None:
        """`sort -rn` parses its key with LC_NUMERIC, so a comma-decimal locale
        ranks every log as 0 and the loop photographs whichever session wrote
        last. The uptime comparison that replaced the awk is integer bash
        arithmetic, which no locale touches."""
        source = (self.SCRIPTS_DIR / "playtest-capture.sh").read_text(encoding="utf-8")
        self.assertIn("LC_ALL=C sort -rn", source)
        self.assertNotIn("awk -v now=", source)


if __name__ == "__main__":
    unittest.main()
