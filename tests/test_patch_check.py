"""`check-patches`: a mod patch XPath that selects zero nodes is a silent no-op.

The engine's `XmlPatcher` (`GetXpathResultsInList`) returns false when an XPath
matches no node, and the operation returns 0 silently — so a typo'd selector
ships unapplied with no error. This gate replays each structural operation's
XPath against the stock `Data/Config` copy and fails the zero-match ones.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.patch_check import check_patches


class PatchCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.mod = self.root / "mod"
        self.config = self.mod / "Config"
        self.config.mkdir(parents=True)
        self.game = self.root / "game"
        (self.game / "Data" / "Config").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _stock(self, name: str, body: str) -> None:
        (self.game / "Data" / "Config" / f"{name}.xml").write_text(body, encoding="utf-8")

    def _patch(self, name: str, body: str) -> None:
        (self.config / f"{name}.xml").write_text(body, encoding="utf-8")

    def test_append_to_the_root_resolves(self) -> None:
        self._stock("blocks", '<blocks><block name="a" /></blocks>')
        self._patch(
            "blocks",
            '<configs><append xpath="/blocks"><block name="b" /></append></configs>',
        )
        report = check_patches(self.mod, self.config, self.game)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(1, len(report.resolved))

    def test_a_zero_match_xpath_fails(self) -> None:
        self._stock("blocks", '<blocks><block name="a" /></blocks>')
        self._patch(
            "blocks",
            "<configs><append xpath=\"//block[@name='missing']\"><x/></append></configs>",
        )
        report = check_patches(self.mod, self.config, self.game)
        self.assertFalse(report.ok)
        self.assertTrue(any("missing" in p for p in report.problems))

    def test_an_absolute_child_walk_zero_match_fails(self) -> None:
        self._stock("x", '<configs><item name="a" /></configs>')
        self._patch("x", "<configs><remove xpath=\"/configs/item[@name='nope']\" /></configs>")
        report = check_patches(self.mod, self.config, self.game)
        self.assertFalse(report.ok)

    def test_a_missing_stock_target_is_a_note_not_a_fail(self) -> None:
        self._patch("noStock", '<configs><append xpath="/x"><y/></append></configs>')
        report = check_patches(self.mod, self.config, self.game)
        self.assertTrue(report.ok)
        self.assertTrue(any("no stock" in n for n in report.notes))

    def test_no_game_directory_skips_with_a_note(self) -> None:
        self._patch("blocks", '<configs><append xpath="/blocks"><x/></append></configs>')
        report = check_patches(self.mod, self.config, None)
        self.assertTrue(report.ok)
        self.assertTrue(any("no game directory" in n for n in report.notes))


if __name__ == "__main__":
    unittest.main()
