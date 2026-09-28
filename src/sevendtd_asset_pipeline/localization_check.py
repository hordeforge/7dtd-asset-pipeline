"""Offline gate for text localization, the mirror of `icon_check` for strings.

`icons` are the sprite half of "a key the engine looks up"; localization is the
text half, and it is just as silent when it breaks. An item, block or entity
class is displayed by its **name**, which the engine resolves through
`Localization.Get` — so a definition whose name no `Config/Localization.csv`
row provides shows the raw name in the UI. There is no error anywhere: the
string simply is not translated, and a typo (the row was spelled differently
from the name) is indistinguishable from "no localization intended" by the
engine, which is why the check must exist here.

Vanilla names are the normal case — every game asset resolves through the
game's own table, and a mod that adds a new name provides a row for it. So,
like `icon_check`, the reconciliation is: every name the mod **defines** (and
every explicit localize-bearing property value that is a bare key) must be
provided by the mod's `Localization.csv` **or** (when the game config is
available and `--allow-vanilla-keys`, the default) by the game's
`Localization.csv`. A referenced key in neither is `missing` — reported, and
failed only when the mod ships a `Localization.csv` (a mod that localizes
anything clearly meant to localize this, so a missing row is a bug).

The engine fact lives in `docs/research/research-provenance.md`: the game's
`Localization.csv` is read from `Config/`, and `Localization.Get(key)` returns
the key itself on a miss — which is exactly the raw-name symptom.

No custom parser: a bare-key test (single token, no spaces or commas) is what
separates a key from a literal description. A `Description` value of
`"A sturdy tool"` is passed to `Localization.Get` too, but it is not a key the
author must provide — it is shown as-is on the miss — so only bare tokens are
reconciled.

That test is written in English, and English is the only language that puts
spaces between its words. A Japanese, Korean, Chinese, Thai or Vietnamese
description is a bare token under it, and a gate that reconciles it asks the
author for a table row for their own sentence. A value carrying no ASCII is
therefore reconciled only when a table row answers for it; otherwise it is
reported as undecided, because whether it is a key is a question the file
cannot answer and only a failing gate can hide.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import PipelineError
from .references import config_xml_texts
from .text import nfc

# A definition whose name is the display string: the engine looks the name up.
DEFINITION = re.compile(r'<(item|block|entity_class)\s+name\s*=\s*"([^"]+)"', re.DOTALL)
# Explicit properties whose value is a localization key. A bare token only: a
# value with spaces/commas is literal text shown as-is on a miss, not a key.
LOCALIZE_PROPERTIES = (
    "display_name",
    "Description",
    "desc_key",
    "tooltip",
    "LongDescription",
)
_PROPERTY_PATTERNS = {
    name: re.compile(
        rf'name\s*=\s*"{name}"\s+value\s*=\s*"([^"]+)"|'
        rf'value\s*=\s*"([^"]+)"\s+name\s*=\s*"{name}"'
    )
    for name in LOCALIZE_PROPERTIES
}
# A value that could be a key: a single token, no whitespace or comma. Anything
# else is literal text (an English sentence, a number list) and is not a key.
_BARE_KEY = re.compile(r"^[^\s,;]+$")
# The other half of that test, and it is script-dependent. An English sentence
# is excluded from key-hood by its spaces; a Japanese, Korean, Chinese or Thai
# sentence has none, so the same value reads as a bare token and the gate asks
# the author for a table row for their own description. A key that carries no
# ASCII is legal (a Russian mod may well key on Cyrillic), so the mark of a
# key rather than of a sentence is the one the table settles: see
# `check_localization`.
_ASCII_KEY_CHARS = re.compile(r"[A-Za-z0-9_]")
# The game and mod both keep the table at Config/Localization.csv.
LOCALIZATION_FILENAME = "Localization.csv"


@dataclass
class LocalizationReport:
    """The reconciliation: what the mod references, what it provides, what is missing."""

    csv: str
    referenced: tuple[str, ...]
    resolved: tuple[str, ...]
    vanilla: tuple[str, ...]
    missing: tuple[str, ...]
    problems: list[str]
    notes: list[str]

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, object]:
        return asdict(self) | {"ok": self.ok}


def spelling_mismatches(referenced: Iterable[str], provided: set[str]) -> list[tuple[str, str]]:
    """Referenced keys that only a table row with a different spelling would answer.

    Two spellings of one word are different strings, and every comparison on
    this path is a string comparison: a name copied out of a filename on macOS
    arrives decomposed (`cafe` + U+0301) while the row an author typed is
    composed, so the two sides can be the same word and still miss. The engine
    resolves a key against the table it loaded rather than by any folded
    comparison, so a pair like this is reported by name rather than folded
    together here: silently treating them as equal would turn this gate into a
    pass the game does not reproduce.
    """
    by_form: dict[str, set[str]] = {}
    for key in provided:
        by_form.setdefault(nfc(key), set()).add(key)
    mismatches: list[tuple[str, str]] = []
    for key in referenced:
        for candidate in sorted(by_form.get(nfc(key), set())):
            if candidate != key:
                mismatches.append((key, candidate))
    return mismatches


def read_csv_keys(path: Path) -> set[str]:
    """The `Key` column (first field) of a `Localization.csv`."""
    keys: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise PipelineError(f"cannot read {path}: {exc}") from exc
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        key = row[0].strip().strip('"')
        if key:
            keys.add(key)
    return keys


def discover_localization_keys(
    config_dir: Path, texts: list[tuple[Path, str]] | None = None
) -> dict[str, list[str]]:
    """Every localization key the mod references, mapped to its files.

    A key is a definition name (item/block/entity_class — the engine looks the
    name up) or an explicit localize-bearing property value that is a bare token
    with ASCII in it. A bare value with no ASCII in it is a key under one
    reading of "bare" and a sentence under another, and this returns neither
    verdict: `_scan_localization` hands those back apart, and
    `check_localization` settles them against the tables.
    """
    keys, _ = _scan_localization(config_dir, texts)
    return keys


def _scan_localization(
    config_dir: Path, texts: list[tuple[Path, str]] | None = None
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """The referenced keys, and the bare values whose key-ness is undecided.

    The two differ only in what they can prove from the file: a value carrying
    no ASCII in a bare token is a key under an English reading of "bare" and a
    sentence under a Japanese one, and nothing in the file itself separates
    them. Both are returned rather than one being dropped, because dropping the
    undecided half is what makes the gate ask a Chinese author for a table row
    for their own description.
    """
    keys: dict[str, list[str]] = {}
    undecided: dict[str, list[str]] = {}
    for xml_file, text in texts if texts is not None else config_xml_texts(config_dir):
        for match in DEFINITION.finditer(text):
            # Group 2 is the name. Group 1 is the tag; entity_class resolves its
            # display name by the class name too.
            name = match.group(2).strip()
            if name:
                keys.setdefault(name, []).append(str(xml_file))
        for pattern in _PROPERTY_PATTERNS.values():
            for match in pattern.finditer(text):
                value = (match.group(1) or match.group(2)).strip()
                if not value or not _BARE_KEY.match(value):
                    continue
                undecided.setdefault(value, []).append(str(xml_file))
    for value, files in undecided.items():
        if _ASCII_KEY_CHARS.search(value):
            keys.setdefault(value, files)
    return keys, {value: files for value, files in undecided.items() if value not in keys}


def check_localization(
    mod_root: Path,
    config_dir: Path | None = None,
    game_dir: Path | None = None,
    allow_vanilla_keys: bool = True,
) -> LocalizationReport:
    """Reconcile the mod's referenced localization keys with its CSV (and the game's)."""
    mod_root = Path(mod_root).resolve()
    config = Path(config_dir) if config_dir else mod_root / "Config"
    csv_path = config / LOCALIZATION_FILENAME
    texts = config_xml_texts(config)

    referenced, undecided = _scan_localization(config, texts)
    provided = read_csv_keys(csv_path) if csv_path.is_file() else set()
    game_keys: set[str] = set()
    if game_dir is not None:
        vanilla_csv = Path(game_dir) / "Data" / "Config" / LOCALIZATION_FILENAME
        if vanilla_csv.is_file() and allow_vanilla_keys:
            game_keys = read_csv_keys(vanilla_csv)

    problems: list[str] = []
    notes: list[str] = []
    resolved: list[str] = []
    vanilla_resolved: list[str] = []
    missing: list[str] = []

    # The table settles what a bare value with no ASCII in it is: a row answers
    # for it and it is a key that resolves; no row answers for it and nothing
    # here can say whether the author wrote a key with no row or a sentence.
    # Failing the second one is how a Japanese description comes back as a
    # missing localization key, so it is reported as what it is: undecided.
    for value in sorted(undecided):
        if value in provided or value in game_keys:
            referenced.setdefault(value, undecided[value])
        else:
            notes.append(
                f"{value!r} is set as a localize-bearing property value and carries no ASCII, "
                "so a key and a sentence are indistinguishable in it: a script that does not "
                "separate words with spaces writes either the same way. No "
                f"{LOCALIZATION_FILENAME} row provides it, so it is reported rather than failed: "
                "if it is a key, the row is missing; if it is literal text, nothing is missing "
                "and the engine shows it as it stands"
            )

    for key in sorted(referenced):
        if key in provided:
            resolved.append(key)
        elif key in game_keys:
            # A vanilla name resolves through the game's table; allowed (default).
            vanilla_resolved.append(key)
        else:
            missing.append(key)

    if missing:
        if csv_path.is_file():
            # The mod localizes; a referenced key it provides nowhere is a bug.
            problems.append(
                f"{len(missing)} localization key(s) referenced by Config/ are provided by "
                f"neither this mod's {LOCALIZATION_FILENAME} nor the game's vanilla "
                f"table: {', '.join(missing)}. Localization.Get returns the key itself on a "
                "miss, so each shows as a raw name/string in the UI. Add a row (or extend a "
                "vanilla entry) or set the property to literal text."
            )
        else:
            notes.append(
                f"{len(missing)} localization key(s) referenced by Config/ have no "
                f"{LOCALIZATION_FILENAME} in this mod, so they will show as raw names: "
                f"{', '.join(missing)}. Ship a Localization.csv to translate them, or they are "
                "deliberately untranslated."
            )
    if not csv_path.is_file():
        notes.append(
            "this mod ships no Config/Localization.csv; its defined names are untranslated"
        )
    for key, candidate in spelling_mismatches(referenced, provided | game_keys):
        notes.append(
            f"{key!r} and the row {candidate!r} are the same word in different Unicode "
            "normalization forms, one composed and one decomposed. They are different "
            "strings, so a lookup that compares them does not match; spell the key in "
            "Config/ exactly as the table spells it, composed (NFC)."
        )
    if game_dir is None:
        notes.append(
            "the game's Localization.csv was never looked for, because no game directory "
            "is configured; every vanilla key is reported as missing. Set "
            "SEVEN_DAYS_TO_DIE_DIR (or point check-localization at a game directory) to "
            "know the difference"
        )
    elif not (Path(game_dir) / "Data" / "Config" / LOCALIZATION_FILENAME).is_file():
        notes.append("the game's Localization.csv was not found; vanilla keys were not checked")

    return LocalizationReport(
        csv=str(csv_path) if csv_path.is_file() else "",
        referenced=tuple(sorted(referenced)),
        resolved=tuple(resolved),
        vanilla=tuple(vanilla_resolved),
        missing=tuple(missing),
        problems=problems,
        notes=notes,
    )
