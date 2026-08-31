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
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import PipelineError

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
    name up) or an explicit localize-bearing property value that is a bare token.
    """
    keys: dict[str, list[str]] = {}
    for xml_file, text in texts if texts is not None else _config_texts(config_dir):
        for match in DEFINITION.finditer(text):
            # Group 2 is the name. Group 1 is the tag; entity_class resolves its
            # display name by the class name too.
            name = match.group(2).strip()
            if name:
                keys.setdefault(name, []).append(str(xml_file))
        for pattern in _PROPERTY_PATTERNS.values():
            for match in pattern.finditer(text):
                value = (match.group(1) or match.group(2)).strip()
                if value and _BARE_KEY.match(value):
                    keys.setdefault(value, []).append(str(xml_file))
    return keys


def _config_texts(config_dir: Path) -> list[tuple[Path, str]]:
    texts: list[tuple[Path, str]] = []
    if not config_dir.is_dir():
        return texts
    for xml_file in sorted(config_dir.rglob("*.xml")):
        try:
            texts.append((xml_file, xml_file.read_text(encoding="utf-8-sig")))
        except (OSError, UnicodeDecodeError) as exc:
            raise PipelineError(f"cannot read {xml_file}: {exc}") from exc
    return texts


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
    texts = _config_texts(config)

    referenced = discover_localization_keys(config, texts)
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
                f"neither this mod's {LOCALIZATION_FILENAME} nor the game's the vanilla "
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
    if (
        game_dir is not None
        and not (Path(game_dir) / "Data" / "Config" / LOCALIZATION_FILENAME).is_file()
    ):
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
