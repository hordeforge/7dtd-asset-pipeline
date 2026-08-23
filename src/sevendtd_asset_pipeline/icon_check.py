"""Offline gate for item icons, which are *not* bundle assets.

`shamway validate` covers everything the bundle owns. Icons are the one
deployable asset class it cannot see: `ModManager.LoadUiAtlases` packs each
immediate subfolder of a mod's `UIAtlases/` at runtime, keyed by folder name,
with every PNG inside keyed by its filename stem. Nothing about that path
touches the bundle or its manifest.

Every failure mode here is silent in game. A `CustomIcon` whose key no atlas
provides simply draws whatever else answers to that key — often a vanilla
icon, which looks deliberate. A key that differs from the filename only in case
resolves on one lookup path and not another. So this reports three things
separately and never guesses:

* **atlas files** — what this mod actually ships, and whether each PNG is a
  usable atlas cell;
* **resolved references** — a key this mod's own atlas answers;
* **external references** — a key no atlas here provides. That is legitimate
  (vanilla keys are the normal case) and is reported, never failed.

Three things name an atlas key. `CustomIcon` on an item or block, `icon=` on a
`progression.xml` `display_entry`, and — when an item or block sets no
`CustomIcon` at all — the definition's **own name**, which is the engine's
default sprite lookup. `CustomIcon` exists for the cases where the sprite name
differs from the thing's name, so an item named exactly like its PNG needs no
property, and a typo in that PNG's name is invisible to any check that reads
`CustomIcon` alone. All three are reconciled here.

PNG geometry is read from the IHDR chunk with the standard library, so the
check runs on a bare host. Alpha coverage needs a decoder, so it is measured
only when Pillow is available and skipped with a note otherwise.
"""

from __future__ import annotations

import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from .capabilities import extra_install
from .errors import PipelineError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Colour types that carry an alpha channel. 3 (palette) can carry tRNS
# transparency instead, which is handled where it is checked.
ALPHA_COLOUR_TYPES = (4, 6)
COLOUR_TYPE_NAMES = {0: "grayscale", 2: "rgb", 3: "palette", 4: "grayscale+alpha", 6: "rgba"}
# The V3 item atlas cell measured from the game's own itemicons bundle.
DEFAULT_CELL = 160
ICON_PROPERTIES = ("CustomIcon",)
# `<display_entry icon="...">` in progression.xml names an atlas sprite too.
DISPLAY_ENTRY_ICON = re.compile(r'<display_entry\b[^>]*\bicon\s*=\s*"([^"]+)"')
# An item or block definition, with its body, so the absence of CustomIcon
# inside it can be seen. Mod Config files are patch fragments, so a regex over
# the text is the honest parser here.
DEFINITION = re.compile(r'<(item|block)\s+name\s*=\s*"([^"]+)"[^>]*>(.*?)</\1>', re.DOTALL)
CUSTOM_ICON_INSIDE = re.compile(r'name\s*=\s*"CustomIcon"')


@dataclass(frozen=True)
class IconFile:
    atlas: str
    stem: str
    path: str
    width: int
    height: int
    colour_type: str
    has_alpha: bool
    alpha_coverage: float | None
    """Fraction of pixels with alpha above 8/255, or None when Pillow is absent."""
    problems: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["problems"] = list(self.problems)
        return data


@dataclass(frozen=True)
class IconReport:
    atlas_dir: str
    icons: tuple[IconFile, ...]
    resolved: tuple[str, ...]
    external: tuple[str, ...]
    problems: tuple[str, ...]
    notes: tuple[str, ...]
    implicit: tuple[str, ...] = ()
    """Item/block names with no CustomIcon that a shipped PNG answers by name."""

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, object]:
        return {
            "atlas_dir": self.atlas_dir,
            "icons": [icon.as_dict() for icon in self.icons],
            "resolved": list(self.resolved),
            "external": list(self.external),
            "implicit": list(self.implicit),
            "problems": list(self.problems),
            "notes": list(self.notes),
            "ok": self.ok,
        }


def read_png_header(path: Path) -> tuple[int, int, int, int]:
    """Return (width, height, bit_depth, colour_type) from a PNG's IHDR chunk."""
    try:
        with path.open("rb") as handle:
            signature = handle.read(8)
            if signature != PNG_SIGNATURE:
                raise PipelineError(f"{path} is not a PNG (bad signature)")
            length, chunk = struct.unpack(">I4s", handle.read(8))
            if chunk != b"IHDR" or length < 13:
                raise PipelineError(f"{path} has no IHDR chunk; it is not a usable PNG")
            width, height, depth, colour = struct.unpack(">IIBB", handle.read(10))
    except OSError as exc:
        raise PipelineError(f"cannot read {path}: {exc}") from exc
    return width, height, depth, colour


def _alpha_coverage(path: Path) -> float | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        # histogram() rather than getdata(): stable across Pillow versions, and
        # a 256-bin sum instead of a pass over every pixel.
        counts = rgba.getchannel("A").histogram()
    total = rgba.width * rgba.height
    return sum(counts[9:]) / float(total) if total else 0.0


def inspect_icon(path: Path, atlas: str, cell: int = DEFAULT_CELL) -> IconFile:
    width, height, _depth, colour = read_png_header(path)
    coverage = _alpha_coverage(path)
    problems: list[str] = []
    has_alpha = colour in ALPHA_COLOUR_TYPES
    if not has_alpha and colour != 3:
        problems.append(
            f"{COLOUR_TYPE_NAMES.get(colour, colour)} with no alpha channel; an atlas cell "
            "without transparency draws its background over the inventory slot"
        )
    if width != height:
        problems.append(f"{width}x{height} is not square; the atlas packs square cells")
    if cell and (width != cell or height != cell):
        problems.append(
            f"{width}x{height} is not the {cell}x{cell} cell size measured from the game's "
            "own item atlas; a mismatched cell is rescaled at pack time"
        )
    if coverage is not None and coverage < 0.02:
        problems.append(
            f"only {coverage * 100:.1f}% of pixels are opaque; the icon is essentially empty"
        )
    if coverage is not None and coverage > 0.995 and has_alpha:
        problems.append(
            "the alpha channel is fully opaque; the subject was never cut out of its "
            "background (see docs/art-direction.md, 'Cutting the background out')"
        )
    return IconFile(
        atlas=atlas,
        stem=path.stem,
        path=str(path),
        width=width,
        height=height,
        colour_type=COLOUR_TYPE_NAMES.get(colour, str(colour)),
        has_alpha=has_alpha,
        alpha_coverage=None if coverage is None else round(coverage, 4),
        problems=tuple(problems),
    )


def _config_texts(config_dir: Path) -> list[tuple[Path, str]]:
    texts: list[tuple[Path, str]] = []
    if not config_dir.is_dir():
        return texts
    for xml_file in sorted(config_dir.rglob("*.xml")):
        try:
            texts.append((xml_file, xml_file.read_text(encoding="utf-8-sig")))
        except OSError as exc:
            raise PipelineError(f"cannot read {xml_file}: {exc}") from exc
    return texts


def _scan_atlases(
    mod_root: Path, atlas_dir: Path, cell: int
) -> tuple[list[IconFile], list[str], list[str]]:
    """Inspect every PNG in every atlas folder; also report non-PNG strays.

    Returns the icons plus the problems and notes accumulated while walking.
    """
    icons: list[IconFile] = []
    problems: list[str] = []
    notes: list[str] = []
    for folder in sorted(path for path in atlas_dir.iterdir() if path.is_dir()):
        members = sorted(folder.iterdir())
        pngs = [path for path in members if path.suffix.lower() == ".png"]
        for stray in members:
            if stray.is_file() and stray not in pngs:
                notes.append(
                    f"{stray.relative_to(mod_root)} is not a .png; LoadUiAtlases ignores it"
                )
        if not pngs:
            notes.append(f"{folder.relative_to(mod_root)} contains no icons")
        seen: dict[str, Path] = {}
        for png in pngs:
            folded = png.stem.casefold()
            collision = seen.get(folded)
            if collision is not None:
                problems.append(
                    f"{folder.name}: {png.name} and {collision.name} differ only in case; "
                    "the atlas key is the filename stem and one of them will win silently"
                )
            seen[folded] = png
            icons.append(inspect_icon(png, folder.name, cell))
    for icon in icons:
        problems.extend(f"{icon.atlas}/{icon.stem}.png: {problem}" for problem in icon.problems)
    return icons, problems, notes


def _match_shipped(
    key: str, provided: dict[str, IconFile], provided_ci: dict[str, str]
) -> str | None:
    """The shipped stem that answers `key`: itself, a case-variant, or None."""
    if key in provided:
        return key
    return provided_ci.get(key.casefold())


def _reconcile_explicit_keys(
    references: dict[str, list[str]],
    provided: dict[str, IconFile],
    provided_ci: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    """Sort `CustomIcon`/`display_entry` keys into resolved and external.

    A key differing only in case from the shipped PNG resolves on one lookup
    path and not another, so it is reported and still counted as resolved.
    """
    resolved: list[str] = []
    external: list[str] = []
    problems: list[str] = []
    for key in sorted(references):
        shipped = _match_shipped(key, provided, provided_ci)
        if shipped is None:
            external.append(key)
            continue
        if shipped != key:
            problems.append(
                f'icon key "{key}" differs in case from the shipped {shipped}.png; '
                "keep the key and the filename stem byte-identical"
            )
        resolved.append(key)
    return resolved, external, problems


def _reconcile_implicit_names(
    definitions: dict[str, list[str]],
    provided: dict[str, IconFile],
    provided_ci: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    """Sort name-default lookups into answered and unanswered.

    A definition with no CustomIcon shows the sprite named like itself, so a
    shipped PNG with that exact stem is in use whether or not anything says so.
    """
    implicit: list[str] = []
    unnamed: list[str] = []
    problems: list[str] = []
    for name in sorted(definitions):
        shipped = _match_shipped(name, provided, provided_ci)
        if shipped is None:
            unnamed.append(name)
            continue
        if shipped != name:
            problems.append(
                f'"{name}" sets no CustomIcon, so its icon is looked up by name, and the '
                f"shipped {shipped}.png differs from it in case; rename one of them"
            )
        implicit.append(name)
    return implicit, unnamed, problems


def discover_implicit_icon_names(config_dir: Path) -> dict[str, list[str]]:
    """Item and block names defined without a `CustomIcon`, mapped to their files.

    These resolve their sprite by name (or by a `CustomIcon` inherited through
    `Extends`, which this cannot see), so a PNG named exactly like the item is
    the icon whether or not any property says so.
    """
    names: dict[str, list[str]] = {}
    for xml_file, text in _config_texts(config_dir):
        for match in DEFINITION.finditer(text):
            if CUSTOM_ICON_INSIDE.search(match.group(3)):
                continue
            names.setdefault(match.group(2).strip(), []).append(str(xml_file))
    return names


def discover_icon_references(config_dir: Path) -> dict[str, list[str]]:
    """Every explicit atlas key under Config/, mapped to the files that ask for it.

    Explicit means `CustomIcon` and `display_entry icon=`; the name-default
    lookup is `discover_implicit_icon_names`.
    """
    references: dict[str, list[str]] = {}
    for xml_file, text in _config_texts(config_dir):
        for match in DISPLAY_ENTRY_ICON.finditer(text):
            value = match.group(1).strip()
            if value:
                references.setdefault(value, []).append(str(xml_file))
        for name in ICON_PROPERTIES:
            # A regex rather than a parse: mod Config files are XPath patch
            # fragments, and a fragment with several roots is not a document.
            pattern = re.compile(
                rf'name\s*=\s*"{name}"\s+value\s*=\s*"([^"]+)"|'
                rf'value\s*=\s*"([^"]+)"\s+name\s*=\s*"{name}"'
            )
            for match in pattern.finditer(text):
                value = (match.group(1) or match.group(2)).strip()
                if value:
                    references.setdefault(value, []).append(str(xml_file))
    return references


def check_icons(
    mod_root: Path,
    config_dir: Path | None = None,
    atlas_root: str = "UIAtlases",
    cell: int = DEFAULT_CELL,
) -> IconReport:
    """Check this mod's atlas PNGs and reconcile them with its `CustomIcon` keys."""
    mod_root = Path(mod_root).resolve()
    atlas_dir = mod_root / atlas_root
    problems: list[str] = []
    notes: list[str] = []

    if not atlas_dir.is_dir():
        notes.append(f"no {atlas_root}/ directory; this mod ships no icons")
        icons: list[IconFile] = []
    else:
        icons, problems, notes = _scan_atlases(mod_root, atlas_dir, cell)

    provided = {icon.stem: icon for icon in icons}
    provided_ci = {stem.casefold(): stem for stem in provided}
    config = config_dir if config_dir else mod_root / "Config"

    resolved, external, explicit_problems = _reconcile_explicit_keys(
        discover_icon_references(config), provided, provided_ci
    )
    problems.extend(explicit_problems)
    if external:
        notes.append(
            f"{len(external)} icon key(s) are not provided by this mod: "
            f"{', '.join(external)}. That is normal for vanilla keys — confirm each one "
            "draws the intended art in a client, because a missing key silently draws "
            "whatever else answers to it."
        )

    implicit, unnamed, implicit_problems = _reconcile_implicit_names(
        discover_implicit_icon_names(config), provided, provided_ci
    )
    problems.extend(implicit_problems)
    if unnamed:
        notes.append(
            f"{len(unnamed)} item/block definition(s) set no CustomIcon and ship no PNG of "
            f"their own name: {', '.join(unnamed)}. Each shows a CustomIcon inherited "
            "through Extends, or the vanilla sprite of that name, or whatever else answers "
            "— confirm in a client."
        )

    unused = sorted(set(provided) - set(resolved) - set(implicit))
    if unused:
        notes.append(
            f"{len(unused)} shipped icon(s) nothing references by CustomIcon, display_entry, "
            f"or item/block name: {', '.join(unused)}. A recipe or a C# lookup can still use "
            "one, so this is a prompt to check, not an error."
        )
    if icons and icons[0].alpha_coverage is None:
        notes.append(
            "alpha coverage was not measured; install Pillow "
            f"({extra_install('authoring')}) to gate empty icons"
        )
    return IconReport(
        atlas_dir=str(atlas_dir),
        icons=tuple(icons),
        resolved=tuple(resolved),
        external=tuple(external),
        problems=tuple(problems),
        notes=tuple(notes),
        implicit=tuple(implicit),
    )


# Kept importable for consumers that only want the XML side.
__all__ = [
    "IconFile",
    "IconReport",
    "check_icons",
    "discover_icon_references",
    "discover_implicit_icon_names",
    "inspect_icon",
    "read_png_header",
]
