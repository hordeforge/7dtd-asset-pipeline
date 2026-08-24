"""Tests for the asset-class gates a bundle check cannot cover.

Icons never enter the bundle, and a clip's audibility is decided by things no
parser can see, so both gates work on the file itself. Each test below stands
for a failure that is silent in game.
"""

from __future__ import annotations

import array
import math
import struct
import tempfile
import unittest
import wave
import zlib
from pathlib import Path
from typing import Any

import sevendtd_asset_pipeline
from sevendtd_asset_pipeline import Pipeline, PipelineError
from sevendtd_asset_pipeline.assets_src import LANES, render_readme
from sevendtd_asset_pipeline.icon_check import (
    check_icons,
    discover_icon_references,
    read_png_header,
)
from sevendtd_asset_pipeline.sound_check import check_sound


def write_png(
    path: Path, width: int, height: int, colour_type: int = 6, cut_out: bool = True
) -> None:
    """Write a minimal valid PNG, so the checks run without Pillow.

    `cut_out` gives the image a transparent margin around an opaque centre,
    which is what a real atlas cell looks like; without it the checks correctly
    report that the subject was never separated from its background.
    """
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[colour_type]
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            inside = not cut_out or (
                width // 4 <= x < 3 * width // 4 and height // 4 <= y < 3 * height // 4
            )
            alpha = 255 if inside else 0
            row += bytes(
                {0: [128], 2: [128, 128, 128], 4: [128, alpha], 6: [128, 128, 128, alpha]}[
                    colour_type
                ]
            )
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    assert channels  # the pixel table above must stay in step with colour_type


def write_clip(
    path: Path,
    seconds: float = 0.5,
    rate: int = 44100,
    channels: int = 1,
    amplitude: float = 0.6,
    offset: float = 0.0,
) -> None:
    count = int(seconds * rate)
    samples = array.array("h")
    for index in range(count):
        value = amplitude * math.sin(2 * math.pi * 220 * index / rate) + offset
        clamped = max(-1.0, min(1.0, value))
        for _ in range(channels):
            samples.append(int(clamped * 32767))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())


def write_raw_clip(path: Path, rate: int, channels: int) -> None:
    """A 16-bit PCM WAV with arbitrary header fields, valid or not.

    `wave`'s writer refuses nothing here, so the header is packed by hand; this
    is how a file damaged by another tool reaches the gates.
    """
    data = b"\x00\x00" * 100
    body = struct.pack("<HHIIHH", 1, channels, 0, rate, 2 * channels, 16)
    payload = (
        b"WAVEfmt " + struct.pack("<I", 16) + body + b"data" + struct.pack("<I", len(data)) + data
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(payload)) + payload)


class IconTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.atlas = self.root / "UIAtlases" / "ItemIconAtlas"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _config(self, body: str) -> Path:
        config = self.root / "Config"
        config.mkdir(parents=True, exist_ok=True)
        (config / "items.xml").write_text(body, encoding="utf-8")
        return config

    def test_reads_png_geometry_without_pillow(self) -> None:
        write_png(self.atlas / "myModThing.png", 160, 160)
        self.assertEqual((160, 160, 8, 6), read_png_header(self.atlas / "myModThing.png"))

    def test_accepts_a_correct_cell_and_resolves_its_key(self) -> None:
        write_png(self.atlas / "myModThing.png", 160, 160)
        config = self._config(
            '<configs><item name="a"><property name="CustomIcon" value="myModThing" /></item></configs>'
        )
        report = check_icons(self.root, config)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(("myModThing",), report.resolved)

    def test_rejects_a_cell_that_is_not_the_atlas_size(self) -> None:
        write_png(self.atlas / "myModThing.png", 128, 128)
        report = check_icons(self.root, self._config("<configs/>"))
        self.assertFalse(report.ok)
        self.assertIn("160x160", report.problems[0])

    def test_rejects_a_cell_with_no_alpha_channel(self) -> None:
        write_png(self.atlas / "myModThing.png", 160, 160, colour_type=2)
        report = check_icons(self.root, self._config("<configs/>"))
        self.assertFalse(report.ok)
        self.assertIn("no alpha channel", report.problems[0])

    def test_a_case_mismatch_between_key_and_filename_fails(self) -> None:
        write_png(self.atlas / "myModThing.png", 160, 160)
        config = self._config(
            '<configs><item name="a"><property name="CustomIcon" value="mymodthing" /></item></configs>'
        )
        report = check_icons(self.root, config)
        self.assertFalse(report.ok)
        self.assertIn("differs in case", report.problems[0])

    def test_a_vanilla_key_is_reported_not_failed(self) -> None:
        write_png(self.atlas / "myModThing.png", 160, 160)
        config = self._config(
            '<configs><item name="a"><property name="CustomIcon" value="thrownDynamite" /></item></configs>'
        )
        report = check_icons(self.root, config)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(("thrownDynamite",), report.external)

    def test_a_mod_with_no_atlas_is_not_a_failure(self) -> None:
        report = check_icons(self.root, self._config("<configs/>"))
        self.assertTrue(report.ok)
        self.assertTrue(any("ships no icons" in note for note in report.notes))

    def test_discovers_keys_in_either_attribute_order(self) -> None:
        config = self._config(
            "<configs>"
            '<property name="CustomIcon" value="first" />'
            '<property value="second" name="CustomIcon" />'
            "</configs>"
        )
        self.assertEqual({"first", "second"}, set(discover_icon_references(config)))

    def test_report_is_json_serializable(self) -> None:
        import json

        write_png(self.atlas / "myModThing.png", 128, 128)
        report = check_icons(self.root, self._config("<configs/>"))
        self.assertEqual(report.as_dict(), json.loads(json.dumps(report.as_dict())))
        self.assertTrue(all(isinstance(problem, str) for problem in report.problems))


class SoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_accepts_a_normal_mono_clip(self) -> None:
        clip = self.root / "ok.wav"
        write_clip(clip)
        report = check_sound(clip)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(1, report.channels)
        self.assertAlmostEqual(0.5, report.duration_seconds, places=3)

    def test_rejects_stereo_unless_allowed(self) -> None:
        clip = self.root / "stereo.wav"
        write_clip(clip, channels=2)
        self.assertFalse(check_sound(clip).ok)
        self.assertTrue(check_sound(clip, require_mono=False).ok)

    def test_rejects_an_unexpected_sample_rate(self) -> None:
        clip = self.root / "odd.wav"
        write_clip(clip, rate=32000)
        self.assertIn("sample rate", " ".join(check_sound(clip).problems))

    def test_rejects_silence_and_near_silence(self) -> None:
        silent = self.root / "silent.wav"
        write_clip(silent, amplitude=0.0)
        self.assertIn("digital silence", " ".join(check_sound(silent).problems))
        quiet = self.root / "quiet.wav"
        write_clip(quiet, amplitude=0.01)
        self.assertIn("inaudible", " ".join(check_sound(quiet).problems))

    def test_rejects_clipping(self) -> None:
        clip = self.root / "hot.wav"
        write_clip(clip, amplitude=1.4)
        self.assertIn("clipping", " ".join(check_sound(clip).problems))

    def test_rejects_dc_offset(self) -> None:
        """The defect that survives every other check and clicks on playback."""
        clip = self.root / "offset.wav"
        write_clip(clip, amplitude=0.3, offset=0.2)
        self.assertIn("DC offset", " ".join(check_sound(clip).problems))

    def test_rejects_a_clip_longer_than_its_limit(self) -> None:
        clip = self.root / "long.wav"
        write_clip(clip, seconds=2.0)
        self.assertIn("exceeds", " ".join(check_sound(clip, max_seconds=1.0).problems))

    def test_eight_bit_audio_is_named_and_actionable(self) -> None:
        clip = self.root / "eight.wav"
        with wave.open(str(clip), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(1)
            handle.setframerate(44100)
            handle.writeframes(bytes(1000))
        with self.assertRaises(PipelineError) as raised:
            check_sound(clip)
        self.assertIn("16-bit", str(raised.exception))

    def test_a_missing_clip_is_a_pipeline_error(self) -> None:
        with self.assertRaises(PipelineError):
            check_sound(self.root / "absent.wav")

    def test_a_damaged_header_is_named_not_a_traceback(self) -> None:
        """A zero rate reaches a duration division and must fail as one gate line."""
        clip = self.root / "broken-rate.wav"
        write_raw_clip(clip, rate=0, channels=1)
        with self.assertRaises(PipelineError) as raised:
            check_sound(clip)
        self.assertIn("damaged", str(raised.exception))

    def test_zero_channels_still_fails_as_a_gate_line(self) -> None:
        """`wave` refuses this first; the gate must wrap it either way."""
        clip = self.root / "broken-channels.wav"
        write_raw_clip(clip, rate=44100, channels=0)
        with self.assertRaises(PipelineError):
            check_sound(clip)

    def test_a_big_endian_host_measures_the_same_clip_the_same(self) -> None:
        """WAV samples are little-endian; `array.array("h")` is native order.

        Forcing `sys.byteorder` to "big" lets a little-endian CI prove the
        byte swap happens; on a real big-endian host the unpatched tests above
        already exercise the same path.
        """
        from unittest import mock

        clip = self.root / "ok.wav"
        write_clip(clip)
        native = check_sound(clip).as_dict()
        with mock.patch("sys.byteorder", "big"):
            swapped = check_sound(clip).as_dict()
        self.assertEqual(native, swapped)

    def test_report_is_json_serializable_even_for_silence(self) -> None:
        import json

        clip = self.root / "silent.wav"
        write_clip(clip, amplitude=0.0)
        data = json.loads(json.dumps(check_sound(clip).as_dict()))
        self.assertIsNone(data["peak_dbfs"])


class GeneratorTests(unittest.TestCase):
    """The generators are the pipeline's public authoring surface.

    They must be reachable by name from an installed package — a mod calls
    `shamway generate <name>` and never a path into this repository — and
    each must be able to explain itself on a host that has none of the optional
    imaging or mesh packages installed.
    """

    def test_every_registered_generator_imports(self) -> None:
        from sevendtd_asset_pipeline.generators import GENERATORS, load

        for name in GENERATORS:
            with self.subTest(name):
                self.assertTrue(callable(load(name).main))

    def test_every_generator_answers_help_without_its_dependencies(self) -> None:
        import contextlib
        import io

        from sevendtd_asset_pipeline.generators import GENERATORS, run

        for name in GENERATORS:
            with self.subTest(name):
                output = io.StringIO()
                with self.assertRaises(SystemExit) as raised, contextlib.redirect_stdout(output):
                    run(name, ["--help"])
                self.assertEqual(0, raised.exception.code)
                self.assertIn("usage:", output.getvalue())
                self.assertIn(f"shamway generate {name}", output.getvalue())

    def test_an_unknown_generator_lists_the_known_ones(self) -> None:
        from sevendtd_asset_pipeline.generators import run

        with self.assertRaises(PipelineError) as raised:
            run("nope", [])
        self.assertIn("sound", str(raised.exception))

    def test_the_audio_converter_rejects_a_damaged_header_as_one_error_line(self) -> None:
        """The generator lane fails with its ERROR line, not a division traceback."""
        from sevendtd_asset_pipeline.generators import load

        with tempfile.TemporaryDirectory() as name:
            clip = Path(name) / "broken.wav"
            write_raw_clip(clip, rate=0, channels=1)
            with self.assertRaises(SystemExit) as raised:
                load("audio").read_wav(clip)
            self.assertIn("damaged", str(raised.exception))

    def test_audio_writes_stay_little_endian_on_a_big_endian_host(self) -> None:
        """WAV is little-endian on disk whatever the host's byte order is.

        The same bytes must come out with `sys.byteorder` forced to "big" as
        with it native; the swap must also leave the caller's array in host
        order, because conversion keeps computing on it.
        """
        from unittest import mock

        from sevendtd_asset_pipeline.generators import load

        audio = load("audio")
        samples = array.array("h", [0, 1000, -1000, 32767, -32768])
        original = list(samples)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            native, swapped = root / "native.wav", root / "swapped.wav"
            audio.write_wav(native, samples, 44100)
            with mock.patch("sys.byteorder", "big"):
                audio.write_wav(swapped, samples, 44100)
                self.assertEqual(original, list(audio.read_wav(native)[0]), "host order preserved")
            self.assertEqual(native.read_bytes(), swapped.read_bytes())
            self.assertEqual(original, list(samples), "writing must not swap the caller's array")

    def test_sound_synthesis_is_reproducible_and_passes_its_own_gate(self) -> None:
        """A seeded generator whose output the pipeline would reject is a bug."""
        import contextlib
        import io

        from sevendtd_asset_pipeline.generators import run

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            first, second = root / "a.wav", root / "b.wav"
            for target in (first, second):
                with contextlib.redirect_stdout(io.StringIO()):
                    run("sound", ["tick", str(target), "--seed", "5"])
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertTrue(check_sound(first).ok, check_sound(first).problems)

    def test_the_sounds_xml_entry_omits_noise_unless_asked(self) -> None:
        """<Noise> on a sound layered over a vanilla event calls the horde twice."""
        import contextlib
        import io

        from sevendtd_asset_pipeline.generators import run

        plain, noisy = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(plain):
            run("sound", ["sounds-xml", "myModThud"])
        with contextlib.redirect_stdout(noisy):
            run("sound", ["sounds-xml", "myModThud", "--noise"])
        self.assertNotIn("<Noise", plain.getvalue())
        self.assertIn("<Noise", noisy.getvalue())

    def test_a_distant_variant_gets_its_fade_range(self) -> None:
        """DistantFadeStart defaults to -1 in game, so emitting it is the point."""
        import contextlib
        import io

        from sevendtd_asset_pipeline.generators import run

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            run("sound", ["sounds-xml", "myModThud", "--distant", "myModThudFar"])
        self.assertIn("DistantClip", output.getvalue())
        self.assertIn("DistantFadeStart", output.getvalue())


class AdoptionTests(unittest.TestCase):
    """Adopting a Unity project a mod already has.

    This is the path every existing mod takes, and the one where a mistake is
    expensive: moving a Unity project means moving every `.meta` with it, and
    any slip re-imports each asset under a fresh GUID, silently breaking every
    prefab reference. So adoption must move nothing.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="ExistingMod" /></xml>', encoding="utf-8"
        )
        # A project shaped like one a mod already had: its own layout, its own
        # editor scripts, and a source asset carrying a .meta.
        self.project = self.root / "_meta" / "unity" / "ExistingModAssets"
        self.bundle_source = self.project / "Assets" / "ExistingMod" / "Bundle"
        self.bundle_source.mkdir(parents=True)
        (self.bundle_source / "existingModThing.prefab").write_text("prefab", encoding="utf-8")
        self.meta = self.bundle_source / "existingModThing.prefab.meta"
        self.meta.write_text("guid: 0123456789abcdef", encoding="utf-8")
        (self.project / "Assets" / "ExistingMod" / "Editor").mkdir(parents=True)
        self.mod_builder = self.project / "Assets" / "ExistingMod" / "Editor" / "WorldBuilder.cs"
        self.mod_builder.write_text("// the mod's own generator", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _adopt(self, **overrides: Any) -> tuple[Pipeline, list[Path]]:
        options: dict[str, Any] = {
            "unity_version": "2022.3.62f2",
            "adopt_project": self.project,
            "source_root": "Assets/ExistingMod/Bundle",
            "manifest_dir": "_meta/unity/manifests",
        }
        options.update(overrides)
        return Pipeline.scaffold(self.root, **options)

    def test_adoption_moves_nothing_and_keeps_the_mods_own_scripts(self) -> None:
        before = sorted(path.name for path in self.bundle_source.iterdir())
        self._adopt()
        self.assertEqual(before, sorted(path.name for path in self.bundle_source.iterdir()))
        self.assertEqual("guid: 0123456789abcdef", self.meta.read_text())
        self.assertTrue(self.mod_builder.is_file())
        self.assertFalse((self.root / "tools" / "shamway" / "UnityProject").exists())

    def test_adoption_installs_only_the_pipeline_owned_editor_scripts(self) -> None:
        from sevendtd_asset_pipeline.scaffold import EDITOR_FOLDER, PIPELINE_EDITOR_SCRIPTS

        self._adopt()
        installed = self.project / EDITOR_FOLDER
        self.assertEqual(
            sorted(PIPELINE_EDITOR_SCRIPTS), sorted(path.name for path in installed.iterdir())
        )

    def test_the_config_points_at_the_existing_project(self) -> None:
        pipeline, _ = self._adopt()
        self.assertEqual(self.project.resolve(), pipeline.config.unity_project)
        self.assertEqual("Assets/ExistingMod/Bundle", pipeline.config.source_root)
        self.assertEqual(
            (self.root / "_meta" / "unity" / "manifests").resolve(),
            pipeline.config.manifest_dir,
        )

    def test_a_missing_source_root_is_refused_with_what_it_means(self) -> None:
        with self.assertRaises(PipelineError) as raised:
            self._adopt(source_root="Assets/Wrong/Path")
        self.assertIn("does not exist", str(raised.exception))
        self.assertFalse((self.root / ".shamway.toml").exists())

    def test_a_project_outside_the_mod_is_refused(self) -> None:
        """A mod that reaches outside itself to build is not a standalone repo."""
        with tempfile.TemporaryDirectory() as elsewhere:
            outside = Path(elsewhere) / "Project"
            (outside / "Assets").mkdir(parents=True)
            with self.assertRaises(PipelineError) as raised:
                self._adopt(adopt_project=outside, source_root=None)
        self.assertIn("below the mod root", str(raised.exception))

    def test_a_directory_that_is_not_a_unity_project_is_refused(self) -> None:
        empty = self.root / "_meta" / "unity" / "NotAProject"
        empty.mkdir(parents=True)
        with self.assertRaises(PipelineError) as raised:
            self._adopt(adopt_project=empty, source_root=None)
        self.assertIn("not a Unity project", str(raised.exception))

    def test_adoption_still_writes_the_agent_guide_and_source_tree(self) -> None:
        _, created = self._adopt()
        names = [path.name for path in created]
        self.assertIn("AGENTS.md", names)
        self.assertIn("assets-src", names)
        self.assertTrue((self.root / "assets-src" / "README.md").is_file())


class DocumentationTests(unittest.TestCase):
    """`shamway docs` is how an agent in a mod repo reads the rules."""

    def test_every_topic_resolves_to_a_real_page(self) -> None:
        from sevendtd_asset_pipeline.docs import TOPICS, read

        for topic in TOPICS:
            with self.subTest(topic):
                self.assertTrue(read(topic).startswith("#"))

    def test_an_unknown_topic_lists_the_known_ones(self) -> None:
        from sevendtd_asset_pipeline.docs import read

        with self.assertRaises(PipelineError) as raised:
            read("nope")
        self.assertIn("art-direction", str(raised.exception))

    def test_the_listing_matches_the_topic_table(self) -> None:
        from sevendtd_asset_pipeline.docs import TOPICS, topics

        listed = topics()
        self.assertEqual(len(TOPICS), len(listed))
        for entry in listed:
            with self.subTest(entry["topic"]):
                self.assertEqual("true", entry["available"])
                self.assertTrue(entry["summary"])

    def test_every_directory_indexes_its_own_pages(self) -> None:
        """Each docs/ subdirectory is a category with a README that lists it.

        The categories are the navigation: an agent that lands in
        `docs/authoring/` must be able to tell what the directory is for and
        what is in it without going back up. A page added to a category and
        left out of its index is a page nobody finds.
        """
        root = Path(__file__).resolve().parents[1] / "docs"
        if not root.is_dir():
            self.skipTest("running from a packaged install without the repo docs/")
        for directory in sorted(path for path in root.iterdir() if path.is_dir()):
            index = directory / "README.md"
            with self.subTest(directory.name):
                self.assertTrue(index.is_file(), f"docs/{directory.name}/ has no README.md")
                listed = index.read_text(encoding="utf-8")
                for page in sorted(directory.glob("*.md")):
                    if page.name == "README.md":
                        continue
                    self.assertIn(
                        page.name,
                        listed,
                        f"docs/{directory.name}/{page.name} is not named in its README",
                    )

    def test_the_root_index_names_every_top_level_page(self) -> None:
        root = Path(__file__).resolve().parents[1] / "docs"
        if not root.is_dir():
            self.skipTest("running from a packaged install without the repo docs/")
        index = (root / "README.md").read_text(encoding="utf-8")
        for page in sorted(root.glob("*.md")):
            if page.name == "README.md":
                continue
            with self.subTest(page.name):
                self.assertIn(page.name, index)
        for directory in sorted(path for path in root.iterdir() if path.is_dir()):
            with self.subTest(directory.name):
                self.assertIn(f"{directory.name}/", index)

    def test_packaged_pages_are_the_repo_pages(self) -> None:
        """A wheel ships `src/sevendtd_asset_pipeline/docs/`; a checkout reads `docs/`.

        The two must never disagree: an agent in a mod repo reads the packaged
        copy while this repository's own rules are edited at the root, and the
        copy has already drifted once. `setup.py` re-copies on every build, so
        equality here is cheap to keep and expensive to lose.

        Every `.md` under docs/ is compared, not just the TOPICS pages: the
        genre stores (adrs/, rfcs/, prds/, reports/, reviews/, digests/) and
        their READMEs and templates ship in the wheel too, and a drift there
        would be invisible to every other check.
        """
        source = Path(__file__).resolve().parents[1] / "docs"
        if not source.is_dir():
            self.skipTest("running from a packaged install without the repo docs/")
        packaged = Path(sevendtd_asset_pipeline.__file__).resolve().parent / "docs"
        packaged_pages = sorted(path.relative_to(packaged) for path in packaged.rglob("*.md"))
        source_pages = sorted(path.relative_to(source) for path in source.rglob("*.md"))
        self.assertEqual(
            source_pages,
            packaged_pages,
            "docs/ and the packaged copy disagree on which pages exist; "
            "re-copy the tree (or rebuild the wheel)",
        )
        for relative in source_pages:
            with self.subTest(str(relative)):
                self.assertTrue(
                    (packaged / relative).read_bytes() == (source / relative).read_bytes(),
                    f"{relative} differs between docs/ and the packaged copy; "
                    "re-copy it (or rebuild the wheel) so both readers see one page",
                )


class AssetsSourceTreeTests(unittest.TestCase):
    def test_readme_names_every_lane_and_resolves_placeholders(self) -> None:
        readme = render_readme("MyMod", "mymod.unity3d")
        self.assertNotIn("{mod_name}", readme)
        self.assertNotIn("{bundle_name}", readme)
        for lane in LANES:
            self.assertIn(f"`{lane}/`", readme)

    def test_scaffold_creates_the_tree_without_clobbering(self) -> None:
        from sevendtd_asset_pipeline.assets_src import create

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "assets-src" / "icons").mkdir(parents=True)
            existing = root / "assets-src" / "icons" / "mine.png"
            existing.write_bytes(b"keep me")
            created = create(root, "MyMod", "mymod.unity3d")
            self.assertTrue((created / "README.md").is_file())
            self.assertEqual(b"keep me", existing.read_bytes())


if __name__ == "__main__":
    unittest.main()
