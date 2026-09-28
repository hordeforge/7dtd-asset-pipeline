"""Text handling at this package's own boundaries: bytes in, names as identity.

Two policies are asserted here rather than in the gates that use them, because
a gate that folds a name and a gate that does not are the same defect wearing
two coats, and only the shared answer tells them apart.

Every input below is a legal one: a filename macOS wrote decomposed, a mod
name in a script with no ASCII in it, and a child process that emitted a byte
outside UTF-8. None of them is exotic to the hosts this pipeline runs on.
"""

from __future__ import annotations

import ast
import codecs
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import sevendtd_asset_pipeline as package
from sevendtd_asset_pipeline import validation
from sevendtd_asset_pipeline.acceptance import _identifier
from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.localization_check import spelling_mismatches
from sevendtd_asset_pipeline.references import resolve_case_insensitive
from sevendtd_asset_pipeline.text import (
    CASES,
    CHILD_DECODE_ERRORS,
    CHILD_ENCODING,
    NORMALIZATION,
    bom_encoding,
    folded,
    spelling_differences,
)

SOURCE = Path(package.__file__).parent
# The host scripts ship with the package and read the same way, so one guard
# covers both trees rather than leaving the second to rot.
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
# "café" as a filename arrives from macOS, where the file system stores the
# combining acute (U+0301) rather than the precomposed letter.
COMPOSED = "caf\u00e9"
DECOMPOSED = "cafe\u0301"


class NameFoldingTests(unittest.TestCase):
    def test_both_spellings_of_one_name_fold_to_one_key(self) -> None:
        self.assertEqual(folded(COMPOSED), folded(DECOMPOSED))
        self.assertEqual(folded("MyModThing"), folded("mymodthing"))

    def test_case_and_normalization_are_answered_apart(self) -> None:
        """A case-only pair and a spelling-only pair are different repairs."""
        self.assertEqual(spelling_differences("mymodthing", "myModThing"), (CASES,))
        self.assertEqual(spelling_differences(COMPOSED, DECOMPOSED), (NORMALIZATION,))
        self.assertEqual(spelling_differences("Café", "CAFE\u0301"), (CASES, NORMALIZATION))

    def test_one_name_reported_as_its_own_spelling_has_no_difference(self) -> None:
        self.assertEqual(spelling_differences(COMPOSED, COMPOSED), ())

    def test_localization_reports_the_pair_rather_than_folding_it(self) -> None:
        """A key and its table row that differ only in form are named, not merged.

        The engine resolves a key against the table it loaded, so folding them
        here would pass a gate the game does not reproduce.
        """
        self.assertEqual(spelling_mismatches([COMPOSED], {DECOMPOSED}), [(COMPOSED, DECOMPOSED)])
        self.assertEqual(spelling_mismatches([COMPOSED], {COMPOSED}), [])


class ByteOrderMarkTests(unittest.TestCase):
    """A mark is the encoding statement a UTF-16 or UTF-32 file can make.

    Its declaration is ASCII sitting among bytes that are not, so a reader that
    waits for a declaration has nothing to read and refuses the file. The mark
    is readable from any bytes and is what the Windows writers emit.
    """

    def test_each_mark_names_a_codec_that_decodes_its_own_bytes(self) -> None:
        for mark, encoding in (
            (codecs.BOM_UTF8, "utf-8"),
            (codecs.BOM_UTF16_LE, "utf-16-le"),
            (codecs.BOM_UTF16_BE, "utf-16-be"),
            (codecs.BOM_UTF32_LE, "utf-32-le"),
            (codecs.BOM_UTF32_BE, "utf-32-be"),
        ):
            with self.subTest(encoding=encoding):
                raw = mark + "Кирка".encode(encoding)
                named = bom_encoding(raw)
                self.assertIsNotNone(named)
                assert named is not None
                self.assertEqual("Кирка", raw.decode(named))

    def test_a_utf_32_mark_is_not_read_as_the_utf_16_mark_it_begins_with(self) -> None:
        """`BOM_UTF32_LE` starts with the bytes of `BOM_UTF16_LE`, so the
        longest mark has to be tried first or a UTF-32 file decodes to
        gibberish rather than an error."""
        self.assertEqual("utf-32", bom_encoding(codecs.BOM_UTF32_LE + b"x"))
        self.assertEqual("utf-16", bom_encoding(codecs.BOM_UTF16_LE + b"x"))

    def test_bytes_with_no_mark_name_no_codec(self) -> None:
        self.assertIsNone(bom_encoding(b"<config/>"))
        self.assertIsNone(bom_encoding(b""))


class StemIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_two_spellings_of_one_stem_are_an_ambiguity(self) -> None:
        """7DTD resolves a stem by name, so one name filed twice is one winner.

        Before the fold this pair was two distinct stems and the gate passed a
        bundle in which either spelling silently answers the lookup.
        """
        with self.assertRaisesRegex(PipelineError, "ambiguous file-name stems"):
            validation.reject_ambiguous_stems([f"{COMPOSED}.png", f"{DECOMPOSED}.png"])

    def test_a_reference_spelled_the_other_way_names_the_form_difference(self) -> None:
        index = validation._stem_index([f"{DECOMPOSED}.png"])
        with self.assertRaises(PipelineError) as raised:
            validation._check_stem("Config/items.xml", COMPOSED, index, Path("manifest"))
        message = str(raised.exception)
        self.assertIn("normalization form", message)
        self.assertIn("composed (NFC)", message)

    def test_a_case_only_stem_mismatch_still_reports_case(self) -> None:
        index = validation._stem_index(["myModThing.png"])
        with self.assertRaisesRegex(PipelineError, "asset case is 'mymodthing'"):
            validation._check_stem("Config/items.xml", "mymodthing", index, Path("manifest"))

    def test_a_bundle_path_spelled_composed_finds_a_decomposed_file(self) -> None:
        """macOS stores `Café.unity3d` decomposed; the reference is composed."""
        bundle = self.root / "Resources" / DECOMPOSED
        bundle.mkdir(parents=True)
        target = bundle / f"{DECOMPOSED}.unity3d"
        target.write_bytes(b"fixture")
        relative = f"Resources/{COMPOSED}/{COMPOSED}.unity3d"
        self.assertEqual(resolve_case_insensitive(self.root, relative), target)

    def test_a_reference_to_a_bundle_that_is_absent_is_still_absent(self) -> None:
        self.assertIsNone(resolve_case_insensitive(self.root, "Resources/absent.unity3d"))


class ChildOutputDecodingTests(unittest.TestCase):
    def test_no_child_is_decoded_with_the_host_locale(self) -> None:
        """Every text-mode child names its encoding, or the host decides.

        `text=True` alone decodes with `locale.getpreferredencoding(False)`, so
        the same `unityz` invocation reads differently on a German and a
        C-locale host, and one byte from a Windows tool raises where the gate
        should have reported a diagnostic.
        """
        offenders: list[str] = []
        for path in sorted((*SOURCE.rglob("*.py"), *SCRIPTS.glob("*.py"))):
            if "__pycache__" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if not isinstance(node.func.value, ast.Name) or node.func.value.id != "subprocess":
                    continue
                keywords = {keyword.arg for keyword in node.keywords}
                if (
                    "text" in keywords or "universal_newlines" in keywords
                ) and "encoding" not in keywords:
                    offenders.append(f"{path}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_the_policy_is_utf8_with_replacement(self) -> None:
        self.assertEqual((CHILD_ENCODING, CHILD_DECODE_ERRORS), ("utf-8", "replace"))

    def test_a_child_that_answers_in_another_encoding_still_yields_its_line(self) -> None:
        """A latin-1 byte in a diagnostic is replaced, not raised.

        The failure this replaces is a `UnicodeDecodeError` out of
        `communicate()`, which no call site caught: the run ended in a
        traceback instead of the one ERROR line the CLI promises.
        """
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "noisy.py"
            script.write_text(
                "import sys\nsys.stdout.buffer.write(b'caf\\xe9 broken\\n')\n", encoding="utf-8"
            )
            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                encoding=CHILD_ENCODING,
                errors=CHILD_DECODE_ERRORS,
                check=False,
            )
        self.assertEqual(result.returncode, 0)
        self.assertIn("broken", result.stdout)


class ProviderIdentifierTests(unittest.TestCase):
    def test_two_mod_names_in_scripts_get_two_identifiers(self) -> None:
        """The assembly name and the playtest suite id both come from this.

        `日本` and `中文` share no ASCII, and a fallback that names them alike
        would run one mod's suite under the other's name in a live client.
        """
        self.assertNotEqual(_identifier("日本"), _identifier("中文"))
        self.assertRegex(_identifier("日本"), r"\A[A-Za-z][A-Za-z0-9_]*\Z")
        self.assertEqual(_identifier("My Mod"), "MyMod")


if __name__ == "__main__":
    unittest.main()
