"""The three ways XML names an atlas sprite, reconciled by `check-icons`.

`CustomIcon` is the explicit key. `display_entry icon=` in progression.xml is
the second. The third is the engine's default: an item or block that sets no
`CustomIcon` shows the sprite named like itself, so a PNG with that exact name
is in use with no property saying so — and a typo in it is invisible to a
check that reads `CustomIcon` alone.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_assets import write_png

from sevendtd_asset_pipeline.icon_check import (
    check_icons,
    discover_icon_references,
    discover_implicit_icon_names,
)
from sevendtd_asset_pipeline.errors import PipelineError


class IconKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.atlas = self.root / "UIAtlases" / "ItemIconAtlas"
        self.config = self.root / "Config"
        self.config.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, name: str, body: str) -> None:
        (self.config / name).write_text(body, encoding="utf-8")

    def test_an_xml_with_an_invalid_byte_is_an_error_not_a_traceback(self) -> None:
        """One non-UTF-8 byte in a Config XML fails as the single-line gate
        error, not as a UnicodeDecodeError traceback."""
        (self.config / "items.xml").write_bytes(b'<config name="caf\xe9" />')
        with self.assertRaisesRegex(PipelineError, "cannot read.*items.xml"):
            discover_icon_references(self.config)

    def test_display_entry_icon_is_an_explicit_reference(self) -> None:
        self._write(
            "progression.xml",
            '<configs><append xpath="/progression"><display_entry icon="myModThing" '
            'name_key="x" has_quality="false" unlock_level="5" /></append></configs>',
        )
        self.assertEqual({"myModThing"}, set(discover_icon_references(self.config)))
        write_png(self.atlas / "myModThing.png", 160, 160)
        report = check_icons(self.root, self.config)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(("myModThing",), report.resolved)

    def test_a_definition_without_custom_icon_resolves_by_its_own_name(self) -> None:
        self._write(
            "items.xml",
            '<configs><append xpath="/items"><item name="myModThing">'
            '<property name="Extends" value="thrownDynamite" />'
            "</item></append></configs>",
        )
        self.assertEqual({"myModThing"}, set(discover_implicit_icon_names(self.config)))
        write_png(self.atlas / "myModThing.png", 160, 160)
        report = check_icons(self.root, self.config)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(("myModThing",), report.implicit)
        self.assertFalse(any("nothing references" in note for note in report.notes))

    def test_a_definition_with_custom_icon_is_not_implicit(self) -> None:
        self._write(
            "blocks.xml",
            '<configs><block name="myModBlock"><property name="CustomIcon" value="myModThing" />'
            "</block></configs>",
        )
        self.assertEqual({}, discover_implicit_icon_names(self.config))

    def test_name_case_mismatch_with_a_shipped_png_fails(self) -> None:
        self._write("items.xml", '<configs><item name="mymodthing"></item></configs>')
        write_png(self.atlas / "myModThing.png", 160, 160)
        report = check_icons(self.root, self.config)
        self.assertFalse(report.ok)
        self.assertIn("looked up by name", report.problems[0])

    def test_a_definition_with_no_png_of_its_name_is_reported_not_failed(self) -> None:
        self._write("items.xml", '<configs><item name="myModVariant"></item></configs>')
        report = check_icons(self.root, self.config)
        self.assertTrue(report.ok, report.problems)
        self.assertTrue(
            any("myModVariant" in note and "inherited" in note for note in report.notes)
        )

    def test_report_dict_carries_implicit(self) -> None:
        report = check_icons(self.root, self.config)
        self.assertIn("implicit", report.as_dict())


if __name__ == "__main__":
    unittest.main()
