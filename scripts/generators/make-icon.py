#!/usr/bin/env python3
"""Derive a 7DTD item-atlas icon from a high-resolution source image.

7DTD packs `UIAtlases/ItemIconAtlas/<CustomIcon>.png` at runtime and keys the
icon by its file-name stem, so the deployed file must be the exact atlas cell
size with a clean alpha channel. This does the deterministic part of that: trim
to content, fit into the cell with padding, and report what it produced. It
never invents art.

    make-icon.py source.png UIAtlases/ItemIconAtlas/myModThing.png
    make-icon.py source.png out.png --size 160 --padding 0.06 --contact-sheet sheet.png

Icons are not bundle assets: an icon-only change needs no bundle rebuild.
Requires Pillow (scripts/install-tools.sh --with-authoring installs it via
ImageMagick's ecosystem, or `pip install pillow`).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - depends on host packages
    print(
        "ERROR: Pillow is required for the icon lane. Install it with 'pip install pillow'.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def save_atomically(image: "Image.Image", path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".png", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        image.save(temporary_path, "PNG")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def build_icon(source: Path, size: int, padding: float, trim: bool) -> "Image.Image":
    image = Image.open(source).convert("RGBA")
    if trim:
        box = image.getbbox()
        if box is None:
            raise SystemExit(f"ERROR: {source} is fully transparent")
        image = image.crop(box)
    inner = max(1, int(round(size * (1 - 2 * padding))))
    # Preserve aspect ratio: an icon squashed to fit reads as a different object.
    image.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas


def contact_sheet(icon: "Image.Image", path: Path) -> None:
    """Native size beside 2x and 4x, so small-size legibility is reviewable."""
    scales = (1, 2, 4)
    width = sum(icon.width * scale for scale in scales) + 16 * (len(scales) + 1)
    height = icon.height * max(scales) + 32
    sheet = Image.new("RGBA", (width, height), (32, 32, 32, 255))
    x = 16
    for scale in scales:
        scaled = icon.resize((icon.width * scale, icon.height * scale), Image.NEAREST)
        sheet.paste(scaled, (x, 16), scaled)
        x += scaled.width + 16
    save_atomically(sheet, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=int, default=160, help="atlas cell size (default 160)")
    parser.add_argument("--padding", type=float, default=0.05, help="fraction of the cell, per side")
    parser.add_argument("--no-trim", dest="trim", action="store_false", help="keep source margins")
    parser.add_argument("--contact-sheet", type=Path, help="also write a 1x/2x/4x review sheet")
    args = parser.parse_args(argv)

    if not args.source.is_file():
        raise SystemExit(f"ERROR: no such source image: {args.source}")
    if args.output.suffix.lower() != ".png":
        raise SystemExit("ERROR: 7DTD atlas icons must be .png")
    if not 0 <= args.padding < 0.5:
        raise SystemExit("ERROR: --padding must be in [0, 0.5)")

    icon = build_icon(args.source, args.size, args.padding, args.trim)
    save_atomically(icon, args.output)
    alpha = icon.getchannel("A")
    histogram = alpha.histogram()
    opaque = sum(histogram[1:])
    print(f"path:    {args.output}")
    print(f"size:    {icon.width}x{icon.height} RGBA")
    print(f"stem:    {args.output.stem}   (this is the CustomIcon key)")
    print(f"opaque:  {100 * opaque / (icon.width * icon.height):.1f}% of the cell")
    if args.contact_sheet:
        contact_sheet(icon, args.contact_sheet)
        print(f"sheet:   {args.contact_sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
