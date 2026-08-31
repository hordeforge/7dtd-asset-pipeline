"""The localization half of the key reconciliation, done by `check-localization`.

`check-icons` reconciles the sprite keys (`CustomIcon`); this reconciles the
text keys. An item/block/entity_class displays by its name, which the engine
looks up through `Localization.Get` — so a name no `Localization.csv` row
provides shows the raw name in the UI, with no error anywhere. The check
mirrors `icon_check`: referenced keys (names + bare-token localize properties),
minus the mod's CSV, minus the game's vanilla table (default allowed), is
`missing`. A mod that ships a CSV but drops a referenced key fails; a mod that
ships no CSV reports (it is deliberately untranslated).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.localization_check import (
    check_localization,
    discover_localization_keys,
)


def write_csv(path: Path, keys: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "Key,File,Type,UsedInMainMenu,NoTranslate,KeepLoaded,english,Context / Alternate Text,"
    rows = [header]
    for key in keys:
        rows.append(f"{key},items,Item,,,,{key},,,")
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")


class LocalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = self.root / "Config"
        self.config.mkdir(parents=True)
        self.game = self.root / "game"
        (self.game / "Data" / "Config").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, name: str, body: str) -> None:
        (self.config / name).write_text(body, encoding="utf-8")

    def test_discovery_names_and_bare_key_properties(self) -> None:
        self._write(
            "items.xml",
            '<configs><append xpath="/items"><item name="myModThing">'
            '<property name="Description" value="A sturdy tool" />'
            '<property name="display_name" value="renamedThing" />'
            "</item></append></configs>",
        )
        keys = discover_localization_keys(self.config)
        # Names and bare-token localize props are keys; the spaces in the
        # Description make it literal text, not a key to provide.
        self.assertEqual({"myModThing", "renamedThing"}, set(keys))

    def test_mod_csv_covers_every_referenced_key(self) -> None:
        self._write("blocks.xml", '<configs><block name="myBlock" /></configs>')
        write_csv(self.config / "Localization.csv", ["myBlock"])
        report = check_localization(self.root, self.config)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(("myBlock",), report.resolved)
        self.assertEqual((), report.missing)

    def test_mod_csv_missing_a_referenced_key_fails(self) -> None:
        self._write("blocks.xml", '<configs><block name="myBlock" /></configs>')
        write_csv(self.config / "Localization.csv", ["someOtherKey"])
        report = check_localization(self.root, self.config)
        self.assertFalse(report.ok)
        self.assertEqual(("myBlock",), report.missing)
        self.assertTrue(any("myBlock" in p for p in report.problems))

    def test_no_csv_reports_but_does_not_fail(self) -> None:
        self._write("blocks.xml", '<configs><block name="myBlock" /></configs>')
        report = check_localization(self.root, self.config)
        self.assertTrue(report.ok)
        self.assertEqual(("myBlock",), report.missing)
        self.assertTrue(any("no Config/Localization.csv" in n for n in report.notes))

    def test_vanilla_key_is_allowed_by_default(self) -> None:
        self._write("blocks.xml", '<configs><block name="vanillaBlock" /></configs>')
        write_csv(self.game / "Data" / "Config" / "Localization.csv", ["vanillaBlock"])
        report = check_localization(self.root, self.config, self.game, allow_vanilla_keys=True)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(("vanillaBlock",), report.vanilla)
        self.assertEqual((), report.missing)
        # Disabling vanilla allowance makes it a miss.
        strict = check_localization(self.root, self.config, self.game, allow_vanilla_keys=False)
        self.assertEqual(("vanillaBlock",), strict.missing)


if __name__ == "__main__":
    unittest.main()
