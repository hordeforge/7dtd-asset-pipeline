"""The block `Class` gate.

An invented `Class` is not one bad block: the engine aborts the whole XML file,
so every other block in it is lost, `items.xml` fails after it, saved block ids
stop matching and world load ends in a NullReferenceException. `shamway
validate` passed exactly that and a live client was the first thing to object.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline import engine_classes
from sevendtd_asset_pipeline.config import PipelineConfig
from sevendtd_asset_pipeline.errors import PipelineError


def _config_dir(root: Path, xml: str) -> Path:
    config = root / "Config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "blocks.xml").write_text(xml, encoding="utf-8")
    return config


BLOCK = """<configs><append xpath="/blocks">
  <block name="myProp">
    <property name="Shape" value="ModelEntity" />
    {klass}
  </block>
</append></configs>"""


class DeclaredClassTests(unittest.TestCase):
    def test_a_block_without_a_class_declares_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_dir(Path(tmp), BLOCK.format(klass=""))
            self.assertEqual([], engine_classes.declared_block_classes(config))

    def test_a_blocks_class_is_found_with_its_block_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xml = BLOCK.format(klass='<property name="Class" value="Loot" />')
            config = _config_dir(Path(tmp), xml)
            declared = engine_classes.declared_block_classes(config)
            self.assertEqual(1, len(declared))
            block, value, path = declared[0]
            self.assertEqual(("myProp", "Loot"), (block, value))
            self.assertEqual("blocks.xml", path.name)

    def test_a_class_outside_a_block_is_not_a_blocks_class(self) -> None:
        """An item or recipe Class must not be graded against block types."""
        with tempfile.TemporaryDirectory() as tmp:
            xml = (
                '<configs><item name="myItem">'
                '<property name="Class" value="Ammo" /></item></configs>'
            )
            config = _config_dir(Path(tmp), xml)
            self.assertEqual([], engine_classes.declared_block_classes(config))

    def test_one_blocks_properties_do_not_bleed_into_the_next(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xml = (
                "<configs>"
                '<block name="first"><property name="Class" value="Loot" /></block>'
                '<block name="second"><property name="Shape" value="Cube" /></block>'
                "</configs>"
            )
            config = _config_dir(Path(tmp), xml)
            declared = engine_classes.declared_block_classes(config)
            self.assertEqual([("first", "Loot")], [(b, v) for b, v, _ in declared])


class ClassSourceTests(unittest.TestCase):
    def test_the_assembly_answer_strips_the_block_prefix(self) -> None:
        listing = "0: BlockLoot\n1: BlockDoor\n2: BlockPlant\n3: Block\n"
        with (
            mock.patch("shutil.which", return_value="/usr/bin/monodis"),
            mock.patch("pathlib.Path.is_file", return_value=True),
            mock.patch(
                "subprocess.run",
                return_value=mock.MagicMock(returncode=0, stdout=listing),
            ),
        ):
            names, source = engine_classes.block_classes(Path("/game"))
        self.assertEqual({"Loot", "Door", "Plant"}, names)
        self.assertIn("monodis", source)

    def test_an_empty_listing_is_not_treated_as_an_empty_game(self) -> None:
        """Otherwise every mod that names any class at all would be refused."""
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game / "Data" / "Config").mkdir(parents=True)
            (game / "Data" / "Config" / "blocks.xml").write_text(
                '<blocks><block name="v"><property name="Class" value="Loot" /></block></blocks>',
                encoding="utf-8",
            )
            with (
                mock.patch("shutil.which", return_value="/usr/bin/monodis"),
                mock.patch(
                    "subprocess.run",
                    return_value=mock.MagicMock(returncode=0, stdout="nothing useful"),
                ),
            ):
                names, source = engine_classes.block_classes(game)
        self.assertEqual({"Loot"}, names)
        self.assertIn("vanilla usage only", source)

    def test_no_game_directory_is_a_refusal_not_a_pass(self) -> None:
        with self.assertRaisesRegex(PipelineError, "no game directory"):
            engine_classes.block_classes(None)


class ValidateGateTests(unittest.TestCase):
    """The gate has to fire through `validate`, not only through its module."""

    def _mod(self, root: Path, klass: str) -> PipelineConfig:
        from sevendtd_asset_pipeline.config import load_config, render_config

        (root / "Config").mkdir(parents=True, exist_ok=True)
        (root / "Resources").mkdir(parents=True, exist_ok=True)
        (root / "ModInfo.xml").write_text(
            '<?xml version="1.0"?><xml><Name value="M" /></xml>', encoding="utf-8"
        )
        (root / ".shamway.toml").write_text(
            render_config(mod_name="M", bundle_name="", unity_version="", bundle_source="none"),
            encoding="utf-8",
        )
        (root / "Config" / "blocks.xml").write_text(BLOCK.format(klass=klass), encoding="utf-8")
        return load_config(root / ".shamway.toml")

    def test_validate_refuses_an_unresolvable_class(self) -> None:
        from sevendtd_asset_pipeline.validation import validate_mod

        with tempfile.TemporaryDirectory() as tmp:
            config = self._mod(Path(tmp), '<property name="Class" value="Decoration" />')
            with (
                mock.patch(
                    "sevendtd_asset_pipeline.validation.block_classes",
                    return_value=({"Loot", "Door"}, "a test source"),
                ),
                self.assertRaisesRegex(PipelineError, "BlockDecoration"),
            ):
                validate_mod(config)

    def test_validate_says_not_run_when_nothing_can_answer(self) -> None:
        """An unrun gate must never read like a passed one."""
        from sevendtd_asset_pipeline.validation import validate_mod

        with tempfile.TemporaryDirectory() as tmp:
            config = self._mod(Path(tmp), '<property name="Class" value="Loot" />')
            with mock.patch(
                "sevendtd_asset_pipeline.validation.block_classes",
                side_effect=PipelineError("no game directory is configured"),
            ):
                report = validate_mod(config)
        self.assertTrue(
            any(line.startswith("not run:") for line in report.messages), report.messages
        )


if __name__ == "__main__":
    unittest.main()
