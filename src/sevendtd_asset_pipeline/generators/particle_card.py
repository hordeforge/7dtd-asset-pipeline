#!/usr/bin/env python3
"""Draw a particle card procedurally, with no image model and no ImageMagick.

Two card shapes carry most weather and ambience effects, and neither one is
worth a generated image: a **streak** for falling rain, ash, or snow, and a
broad soft **haze** blob for aerosol, fog banks, and dust. Both are pure
falloff — an image model adds nothing a gaussian does not, and asking one for
"a soft grey blob" reliably returns a planet.

    shamway generate particle-card streak assets-src/vfx/acidRain.png
    shamway generate particle-card haze assets-src/vfx/falloutHaze.png --size 512

The output follows the same convention as `shamway generate cutout luma`: RGB
is white and the shape lives entirely in the alpha channel, so the particle
system's own colour-over-lifetime tints it. One card therefore serves every
colour of rain you will ever need — tint it in the material, not here.

For a haze card with real drawn structure, prompt for one instead
(`shamway prompt opacity-mask`) and bring it through `cutout luma`. This
generator is the answer when a card has to exist with no network, no model,
and no host packages beyond Pillow.

Needs Pillow; `shamway capabilities --missing` prints the install command for
this host.

The cards are deterministic: the same arguments produce the same bytes, so a
regenerated card never shows up as a diff for no reason.
"""

from __future__ import annotations

import argparse
import os
import random
import secrets
import sys
from pathlib import Path

from ..capabilities import extra_install

MISSING = None
try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError as error:  # pragma: no cover - depends on host packages
    # Deferred, not fatal: --help must work on a bare host, so someone can read
    # what this needs before installing anything.
    MISSING = str(error)


def require_imaging() -> None:
    """Fail with the install command, at the point the dependency is used."""
    if MISSING is not None:
        raise SystemExit(
            "ERROR: the particle-card lane needs Pillow ({}).\n  Install it with: {}".format(
                MISSING, extra_install("authoring")
            )
        )


def streak(size: int, width: float, length: float, softness: float) -> Image.Image:
    """A vertical rounded bar, blurred: one falling drop, flake, or cinder.

    A drop is drawn long and thin because the particle system stretches it
    further along its velocity; a card that is already a line leaves nothing
    for the stretch to work with, and a card with hard ends reads as a tally
    mark rather than as rain.
    """
    mask = Image.new("L", (size, size), 0)
    bar = max(1, round(size * width))
    tall = max(bar, round(size * length))
    left = (size - bar) / 2
    top = (size - tall) / 2
    ImageDraw.Draw(mask).rounded_rectangle(
        (left, top, left + bar, top + tall), radius=bar / 2, fill=255
    )
    return mask.filter(ImageFilter.GaussianBlur(max(0.0, softness)))


def haze(size: int, lobes: int, softness: float, seed: int) -> Image.Image:
    """Overlapping soft lobes: a broad, low aerosol puff.

    One circle blurred is a vignette, and a hundred particles of it read as a
    grid of identical dots. A handful of offset lobes gives the card an
    irregular silhouette, which is the whole difference between "fog" and
    "somebody drew a sphere".
    """
    rng = random.Random(seed)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    for _ in range(lobes):
        radius = size * rng.uniform(0.10, 0.24)
        # Kept inside the card: a lobe clipped by the edge gives the particle a
        # straight side, and a straight side is visible in every instance of it.
        limit = size / 2 - radius
        x = size / 2 + rng.uniform(-limit, limit)
        y = size / 2 + rng.uniform(-limit, limit) * 0.45
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=200)
    return mask.filter(ImageFilter.GaussianBlur(max(0.0, softness) * size / 128))


def card(mask: Image.Image) -> Image.Image:
    """White RGB with the shape in alpha — what a tinting material expects."""
    white = Image.new("RGB", mask.size, (255, 255, 255))
    white.putalpha(mask)
    return white


def save(image: Image.Image, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}.png"
    )
    try:
        image.save(temporary)
        temporary.replace(destination)
    finally:
        # A body half-written when the run dies must never survive as a stray
        # dotfile beside the asset (the package's atomic-write pattern).
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "EXAMPLES\n"
            "  shamway generate particle-card streak assets-src/vfx/acidRain.png\n"
            "      a 64 px falling drop, tinted by the material\n"
            "  shamway generate particle-card haze assets-src/vfx/haze.png --size 512\n"
            "      a broad aerosol puff for a persistent zone effect\n"
            "  shamway generate particle-card streak assets-src/vfx/ash.png --width 0.2\n"
            "      shorter and fatter: embers and ash rather than rain\n"
        ),
    )
    shapes = parser.add_subparsers(dest="shape", required=True)

    streak_parser = shapes.add_parser("streak", help="a falling drop, flake, or cinder")
    streak_parser.add_argument("output", type=Path)
    streak_parser.add_argument("--size", type=int, default=64, help="square card size in pixels")
    streak_parser.add_argument(
        "--width", type=float, default=0.10, help="bar width as a fraction of --size"
    )
    streak_parser.add_argument(
        "--length", type=float, default=0.88, help="bar length as a fraction of --size"
    )
    streak_parser.add_argument(
        "--softness", type=float, default=2.0, help="gaussian blur radius in pixels"
    )

    haze_parser = shapes.add_parser("haze", help="a broad soft aerosol puff")
    haze_parser.add_argument("output", type=Path)
    haze_parser.add_argument("--size", type=int, default=512, help="square card size in pixels")
    haze_parser.add_argument("--lobes", type=int, default=7, help="overlapping soft lobes")
    haze_parser.add_argument(
        "--softness", type=float, default=6.0, help="blur radius, scaled with --size"
    )
    haze_parser.add_argument(
        "--seed", type=int, default=0, help="lobe placement; the same seed is the same card"
    )

    args = parser.parse_args(argv)
    require_imaging()
    if args.size < 8:
        raise SystemExit(f"ERROR: --size must be at least 8 pixels, got {args.size}")

    if args.shape == "streak":
        if not 0 < args.width <= 1 or not 0 < args.length <= 1:
            raise SystemExit("ERROR: --width and --length are fractions of --size, in (0, 1]")
        mask = streak(args.size, args.width, args.length, args.softness)
    else:
        if args.lobes < 1:
            raise SystemExit(f"ERROR: --lobes must be at least 1, got {args.lobes}")
        mask = haze(args.size, args.lobes, args.softness, args.seed)

    if not mask.getbbox():
        raise SystemExit("ERROR: those settings drew nothing; lower --softness or raise --size")
    save(card(mask), args.output)
    print(f"wrote {args.output} ({args.size}x{args.size} {args.shape} card)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
