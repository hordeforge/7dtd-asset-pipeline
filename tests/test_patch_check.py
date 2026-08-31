"""`check-patches`: a mod patch XPath that selects zero nodes is a silent no-op.

The engine's `XmlPatcher` (`GetXpathResultsInList`) returns false when an XPath
matches no node, and the operation returns 0 silently — so a typo'd selector
ships unapplied with no error. This gate replays each structural operation's
XPath against the stock `Data/Config` copy and fails the zero-match ones.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline.config import CONFIG_NAME, load_config
from sevendtd_asset_pipeline.patch_check import _HAS_LXML, check_patches
from sevendtd_asset_pipeline.scaffold import initialize
from sevendtd_asset_pipeline.validation import validate_mod


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

    def test_a_full_xpath_union_is_evaluated_when_lxml_is_present(self) -> None:
        # A union of two node-sets is full XPath 1.0; the stdlib subset cannot
        # run it. With lxml the gate evaluates it and fails the zero-node union;
        # without lxml it reports the selector as not checked rather than guess.
        self._stock("blocks", '<blocks><block name="a" /></blocks>')
        self._patch(
            "blocks",
            "<configs><remove xpath=\"//block[@name='missing'] | //block[@name='nope']\" "
            "/></configs>",
        )
        report = check_patches(self.mod, self.config, self.game)
        if _HAS_LXML:
            self.assertFalse(report.ok)
        with mock.patch("sevendtd_asset_pipeline.patch_check._HAS_LXML", False):
            fallback = check_patches(self.mod, self.config, self.game)
        self.assertTrue(fallback.ok)
        self.assertTrue(any("cannot evaluate" in n for n in fallback.notes))

    def test_validate_reports_a_zero_match_patch(self) -> None:
        """`validate` folds the patch gate in, not only `shamway check-patches`."""
        root = self.mod  # reuse a temp mod root
        root.joinpath("ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod"/><Version value="1.0.0"/><Description value="x"/></xml>',
            encoding="utf-8",
        )
        initialize(root, "ExampleMod", None, "2022.3.62f2", bundle_source="none")
        # game dir + a stock config the patch targets
        (self.game / "Data" / "Config" / "blocks.xml").write_text(
            '<blocks><block name="a" /></blocks>', encoding="utf-8"
        )
        (self.config / "blocks.xml").write_text(
            "<configs><append xpath=\"//block[@name='missing']\"><x/></append></configs>",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"SEVEN_DAYS_TO_DIE_DIR": str(self.game)}):
            config = load_config(root / CONFIG_NAME)
            report = validate_mod(config)
        self.assertTrue(any("missing" in message for message in report.messages))


if __name__ == "__main__":
    unittest.main()
