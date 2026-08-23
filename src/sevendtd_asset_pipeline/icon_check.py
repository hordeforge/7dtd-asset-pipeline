"""Offline gate for item icons, which are *not* bundle assets.

`7dtd-assets validate` covers everything the bundle owns. Icons are the one
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
* **resolved references** — a `CustomIcon` this mod's own atlas answers;
* **external references** — a `CustomIcon` no atlas here provides. That is
  legitimate (vanilla keys are the normal case) and is reported, never failed.

PNG geometry is read from the IHDR chunk with the standard library, so the
check runs on a bare host. Alpha coverage needs a decoder, so it is measured
only when Pillow is available and skipped with a note otherwise.
"""

from __future__ import annotations

import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import PipelineError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Colour types that carry an alpha channel. 3 (palette) can carry tRNS
# transparency instead, which is handled where it is checked.
ALPHA_COLOUR_TYPES = (4, 6)
COLOUR_TYPE_NAMES = {0: "grayscale", 2: "rgb", 3: "palette", 4: "grayscale+alpha", 6: "rgba"}
# The V3 item atlas cell measured from the game's own itemicons bundle.
DEFAULT_CELL = 160
ICON_PROPERTIES = ("CustomIcon",)


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

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, object]:
        return {
            "atlas_dir": self.atlas_dir,
            "icons": [icon.as_dict() for icon in self.icons],
            "resolved": list(self.resolved),
            "external": list(self.external),
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
        from PIL import Image  # noqa: PLC0415 - optional capability
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


def discover_icon_references(config_dir: Path) -> dict[str, list[str]]:
    """Every `CustomIcon` value under Config/, mapped to the files that ask for it."""
    references: dict[str, list[str]] = {}
    if not config_dir.is_dir():
        return references
    for xml_file in sorted(config_dir.rglob("*.xml")):
        try:
            text = xml_file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise PipelineError(f"cannot read {xml_file}: {exc}") from exc
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
    icons: list[IconFile] = []

    if not atlas_dir.is_dir():
        notes.append(f"no {atlas_root}/ directory; this mod ships no icons")
    else:
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
                collision = seen.get(png.stem.casefold())
                if collision is not None:
                    problems.append(
                        f"{folder.name}: {png.name} and {collision.name} differ only in case; "
                        "the atlas key is the filename stem and one of them will win silently"
                    )
                seen[png.stem.casefold()] = png
                icons.append(inspect_icon(png, folder.name, cell))

    for icon in icons:
        problems.extend(f"{icon.atlas}/{icon.stem}.png: {problem}" for problem in icon.problems)

    provided = {icon.stem: icon for icon in icons}
    provided_ci = {stem.casefold(): stem for stem in provided}
    references = discover_icon_references(config_dir if config_dir else mod_root / "Config")
    resolved: list[str] = []
    external: list[str] = []
    for key in sorted(references):
        if key in provided:
            resolved.append(key)
            continue
        shipped = provided_ci.get(key.casefold())
        if shipped is not None:
            problems.append(
                f'CustomIcon "{key}" differs in case from the shipped {shipped}.png; '
                "keep the key and the filename stem byte-identical"
            )
            resolved.append(key)
        else:
            external.append(key)
    if external:
        notes.append(
            f"{len(external)} CustomIcon key(s) are not provided by this mod: "
            f"{', '.join(external)}. That is normal for vanilla keys — confirm each one "
            "draws the intended art in a client, because a missing key silently draws "
            "whatever else answers to it."
        )
    unused = sorted(set(provided) - set(resolved))
    if unused:
        notes.append(
            f"{len(unused)} shipped icon(s) no CustomIcon references: {', '.join(unused)}. "
            "Block items and recipes can reference an icon indirectly, so this is a "
            "prompt to check, not an error."
        )
    if icons and icons[0].alpha_coverage is None:
        notes.append(
            "alpha coverage was not measured; install Pillow "
            "(uv pip install 'sevendtd-asset-pipeline[authoring]') to gate empty icons"
        )
    return IconReport(
        atlas_dir=str(atlas_dir),
        icons=tuple(icons),
        resolved=tuple(resolved),
        external=tuple(external),
        problems=tuple(problems),
        notes=tuple(notes),
    )


# Kept importable for consumers that only want the XML side.
__all__ = [
    "IconFile",
    "IconReport",
    "check_icons",
    "discover_icon_references",
    "inspect_icon",
    "read_png_header",
]