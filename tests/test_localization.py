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

import codecs
import tempfile
import unicodedata
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

    def test_a_key_and_its_row_in_different_normalization_forms_are_named(self) -> None:
        """`café` typed as one code point and `cafe` + U+0301 are one word and
        two strings, and every comparison on this path is a string comparison.

        A name copied out of a macOS filename arrives decomposed while the row
        an author typed is composed, so the pair has to be reported rather than
        folded together here: a pass this gate invented is a pass the game does
        not reproduce.
        """
        decomposed = unicodedata.normalize("NFD", "café")
        self.assertNotEqual(decomposed, "café")
        self._write("blocks.xml", f'<configs><block name="{decomposed}" /></configs>')
        write_csv(self.config / "Localization.csv", ["café"])
        report = check_localization(self.root, self.config, self.game, allow_vanilla_keys=True)
        self.assertEqual((), report.resolved)
        self.assertEqual((decomposed,), report.missing)
        self.assertTrue(any("normalization" in note for note in report.notes), report.notes)

    def test_a_name_in_a_config_declaring_a_legacy_code_page_is_still_a_key(self) -> None:
        """A Russian-locale author's editor writes windows-1251, not UTF-8.

        The gate reconciles keys, so a Config file it cannot decode reports no
        key at all: a mod whose every name is non-ASCII passes a localization
        check that never saw it. The XML declaration says how the bytes are
        encoded and is read before the decoder is chosen.
        """
        body = (
            '<?xml version="1.0" encoding="windows-1251"?>\n'
            '<configs><block name="Кирка" /></configs>'
        )
        (self.config / "blocks.xml").write_bytes(body.encode("windows-1251"))
        write_csv(self.config / "Localization.csv", ["Кирка"])
        report = check_localization(self.root, self.config)
        self.assertEqual(("Кирка",), report.resolved)
        self.assertEqual((), report.missing)

    def test_a_config_saved_as_unicode_is_still_a_key(self) -> None:
        """A Windows editor's "Unicode" save says how it is encoded with a
        byte-order mark and no readable declaration.

        The same silence the legacy code page has: the gate cannot decode the
        file, so it sees no key and a mod whose every name is Cyrillic or CJK
        passes a localization check that never read it. The mark is the
        statement, and `ET.parse` reads it — which is how `read_mod_info` has
        always read a UTF-16 `ModInfo.xml`.
        """
        body = '<?xml version="1.0" encoding="utf-16"?>\n<configs><block name="Кирка" /></configs>'
        (self.config / "blocks.xml").write_bytes(codecs.BOM_UTF16_LE + body.encode("utf-16-le"))
        write_csv(self.config / "Localization.csv", ["Кирка"])
        report = check_localization(self.root, self.config)
        self.assertEqual(("Кирка",), report.resolved)
        self.assertEqual((), report.missing)

    def test_a_config_saved_as_unicode_reports_the_key_it_cannot_provide(self) -> None:
        """The read is not a pass by itself: a missing row in such a file is
        still a missing row, and the gate has to say so."""
        body = '<?xml version="1.0" encoding="utf-16"?>\n<configs><block name="Топор" /></configs>'
        (self.config / "blocks.xml").write_bytes(codecs.BOM_UTF16_LE + body.encode("utf-16-le"))
        write_csv(self.config / "Localization.csv", ["Кирка"])
        report = check_localization(self.root, self.config)
        self.assertEqual(("Топор",), report.missing)
        self.assertFalse(report.ok)

    def test_a_description_in_a_script_without_spaces_is_not_failed_as_a_key(self) -> None:
        """The bare-key test is written in English, and English is one of the few
        languages that separates its words with spaces.

        `これは丈夫な道具です` is a sentence, and under a test that asks "is this
        one token?" it is one token, so the gate asks a Japanese author for a
        table row for their own description and fails their mod over it. What
        the file cannot answer is not what a gate should fail on: the value is
        reported, and the verdict is withheld.
        """
        self._write(
            "blocks.xml",
            '<configs><block name="chisel"><property name="Description" '
            'value="これは丈夫な道具です" /></block></configs>',
        )
        write_csv(self.config / "Localization.csv", ["chisel"])
        report = check_localization(self.root, self.config)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual((), report.missing)
        self.assertEqual(("chisel",), report.resolved)
        self.assertTrue(any("これは丈夫な道具です" in note for note in report.notes), report.notes)

    def test_a_non_ascii_key_the_table_answers_for_is_still_a_key(self) -> None:
        """A Russian mod may key on Cyrillic, and the row settles it.

        Reporting the undecided values is only safe because a row still wins:
        without this, a Cyrillic key that resolves would be reported as text
        and the mod would show a raw name with nothing pointing at the row
        that fixes it.
        """
        body = (
            '<configs><block name="chisel"><property name="desc_key" '
            'value="Название" /></block></configs>'
        )
        self._write("blocks.xml", body)
        write_csv(self.config / "Localization.csv", ["chisel", "Название"])
        report = check_localization(self.root, self.config)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(("chisel", "Название"), tuple(sorted(report.resolved)))
        self.assertEqual((), report.missing)

    def test_a_key_spelled_as_its_own_row_is_not_reported(self) -> None:
        decomposed = unicodedata.normalize("NFD", "café")
        self._write("blocks.xml", f'<configs><block name="{decomposed}" /></configs>')
        write_csv(self.config / "Localization.csv", [decomposed])
        report = check_localization(self.root, self.config, self.game, allow_vanilla_keys=True)
        self.assertEqual((decomposed,), report.resolved)
        self.assertFalse([note for note in report.notes if "normalization" in note])


if __name__ == "__main__":
    unittest.main()
