#!/usr/bin/env python3
"""Derive a 7DTD item-atlas icon from a high-resolution source image.

7DTD packs `UIAtlases/ItemIconAtlas/<CustomIcon>.png` at runtime and keys the
icon by its file-name stem, so the deployed file must be the exact atlas cell
size with a clean alpha channel. This does the deterministic part of that: trim
to content, fit into the cell with padding, and report what it produced. It
never invents art.

    shamway generate icon source.png UIAtlases/ItemIconAtlas/myModThing.png
    shamway generate icon source.png out.png --size 160 --padding 0.06 --contact-sheet sheet.png

Icons are not bundle assets: an icon-only change needs no bundle rebuild.
Requires Pillow (scripts/install-tools.sh --with-authoring installs it via
ImageMagick's ecosystem, or `uv pip install pillow`).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import atomic
from ..capabilities import extra_install

MISSING = None
try:
    from PIL import Image, ImageEnhance
except ImportError as error:  # pragma: no cover - depends on host packages
    # Deferred, not fatal: --help must work on a bare host, so someone can read
    # what this needs before installing anything.
    MISSING = str(error)


def require_imaging() -> None:
    """Fail with the install command, at the point the dependency is used."""
    if MISSING is not None:
        raise SystemExit(
            "ERROR: the icon lane needs Pillow ({}).\n  Install it with: {}".format(
                MISSING, extra_install("authoring")
            )
        )


def save_atomically(image: Image.Image, path: Path) -> None:
    with atomic.staged_write(path) as staged:
        image.save(staged, "PNG")


def build_icon(
    source: Path,
    size: int,
    padding: float,
    trim: bool,
    fill: float = 1.0,
    saturation: float = 1.0,
) -> Image.Image:
    """Fit the source into a cell.

    `fill` and `saturation` exist for one reason: a smaller tier of a family is
    the same source drawn smaller and greyer, so it reads as the same object
    with less in it. 0.7 fill and 0.45 saturation is a proven pairing; pass
    them instead of generating a second source, and record them.
    """
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
    if trim:
        box = image.getbbox()
        if box is None:
            raise SystemExit(f"ERROR: {source} is fully transparent")
        image = image.crop(box)
    if saturation != 1.0:
        alpha = image.getchannel("A")
        image = ImageEnhance.Color(image.convert("RGB")).enhance(saturation).convert("RGBA")
        image.putalpha(alpha)
    inner = max(1, round(size * (1 - 2 * padding) * fill))
    # Preserve aspect ratio: an icon squashed to fit reads as a different object.
    image.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas


def contact_sheet(icon: Image.Image, path: Path) -> None:
    """Native size beside 2x and 4x, on a dark row and a light one.

    Two backgrounds, not one, because the two ways an icon fails are opposite
    and each is invisible on the other ground: a dark-edged subject disappears
    into a dark inventory slot, and a cutout that kept a white halo only shows
    it against light. `docs/authoring/agent-workflows.md` asks for both, and
    this used to render dark alone.
    """
    scales = (1, 2, 4)
    grounds = ((32, 32, 32, 255), (222, 222, 222, 255))
    margin = 16
    row_height = icon.height * max(scales) + margin * 2
    width = sum(icon.width * scale for scale in scales) + margin * (len(scales) + 1)
    sheet = Image.new("RGBA", (width, row_height * len(grounds)), (0, 0, 0, 255))
    for row, ground in enumerate(grounds):
        band = Image.new("RGBA", (width, row_height), ground)
        x = margin
        for scale in scales:
            scaled = icon.resize((icon.width * scale, icon.height * scale), Image.NEAREST)
            band.paste(scaled, (x, margin), scaled)
            x += scaled.width + margin
        sheet.paste(band, (0, row * row_height))
    save_atomically(sheet, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=int, default=160, help="atlas cell size (default 160)")
    parser.add_argument(
        "--padding", type=float, default=0.05, help="fraction of the cell, per side"
    )
    parser.add_argument("--no-trim", dest="trim", action="store_false", help="keep source margins")
    parser.add_argument("--contact-sheet", type=Path, help="also write a 1x/2x/4x review sheet")
    parser.add_argument(
        "--fill",
        type=float,
        default=1.0,
        help="scale the subject within the padded cell (0.7 for a smaller tier)",
    )
    parser.add_argument(
        "--saturation",
        type=float,
        default=1.0,
        help="colour saturation multiplier (0.45 for a greyer tier)",
    )
    args = parser.parse_args(argv)
    require_imaging()

    if not args.source.is_file():
        raise SystemExit(f"ERROR: no such source image: {args.source}")
    if args.output.suffix.lower() != ".png":
        raise SystemExit("ERROR: 7DTD atlas icons must be .png")
    if not 0 <= args.padding < 0.5:
        raise SystemExit("ERROR: --padding must be in [0, 0.5)")
    if not 0 < args.fill <= 1:
        raise SystemExit("ERROR: --fill must be in (0, 1]")
    if args.saturation < 0:
        raise SystemExit("ERROR: --saturation must be >= 0")

    icon = build_icon(args.source, args.size, args.padding, args.trim, args.fill, args.saturation)
    save_atomically(icon, args.output)
    alpha = icon.getchannel("A")
    histogram = alpha.histogram()
    opaque = sum(histogram[1:])
    print(f"path:    {args.output}")
    print(f"size:    {icon.width}x{icon.height} RGBA")
    print(f"stem:    {args.output.stem}   (this is the CustomIcon key)")
    print(f"opaque:  {100 * opaque / (icon.width * icon.height):.1f}% of the cell")
    if args.fill != 1.0 or args.saturation != 1.0:
        print(
            f"variant: fill {args.fill}  saturation {args.saturation}"
            "   (record these with the source)"
        )
    if args.contact_sheet:
        contact_sheet(icon, args.contact_sheet)
        print(f"sheet:   {args.contact_sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
