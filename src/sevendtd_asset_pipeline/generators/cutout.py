#!/usr/bin/env python3
"""Cut a generated image out of its background into a clean RGBA source.

Image generators do not produce transparency. The reliable way to get it is to
ask for a flat, saturated key colour the subject cannot contain — magenta
`#ff00ff` for anything olive, steel or earth-toned; green `#00ff00` when the
subject is itself magenta or pink — and then remove that colour here. This is
the step between "a generated picture" and "an asset", and it is where most of
the quality is won or lost: a hard threshold leaves a coloured fringe on every
soft edge, and a fringe is exactly what makes an icon look pasted on.

Three modes, because three kinds of source need opposite treatment:

    shamway generate cutout key   concept.png cut.png
    shamway generate cutout luma  smoke-mask.png smoke-card.png
    shamway generate cutout alpha haze-src.png haze-card.png --size 512

**key** removes a solid background colour, keeping partial alpha across the
transition band so soft edges survive, and de-spills the leftover key tint that
otherwise rims the subject.

**luma** is for particle cards drawn as grayscale on black: brightness becomes
alpha and RGB becomes white, so the particle system's own colour-over-lifetime
tints it. Raising the black point removes the faint halo a generator leaves in
"empty" space without hardening the puff edges.

**alpha** is for a source that already carries a real alpha channel — which a
generated "opacity mask" often does, with alpha that is *not* its own
brightness. It keeps that alpha untouched and only whitens the RGB. Running
`luma` on such a source silently recomputes alpha from brightness and can cap
a card near half opacity; check `--size` padding rather than reaching for
`luma` when the source already has transparency.

Needs Pillow; `shamway capabilities --missing` prints the install command for this host.

Check the result with `shamway check-icons` (for an atlas cell) and look at
it against both a light and a dark background — a fringe is invisible on one.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from .. import atomic
from ..capabilities import extra_install

MISSING = None
try:
    from PIL import Image
except ImportError as error:  # pragma: no cover - depends on host packages
    # Deferred, not fatal: --help must work on a bare host, so someone can read
    # what this needs before installing anything.
    MISSING = str(error)


def require_imaging() -> None:
    """Fail with the install command, at the point the dependency is used."""
    if MISSING is not None:
        raise SystemExit(
            "ERROR: the cutout lane needs Pillow ({}).\n  Install it with: {}".format(
                MISSING, extra_install("authoring")
            )
        )


def parse_colour(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise SystemExit(f"ERROR: --key must be a #rrggbb colour, got {value!r}")
    try:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        raise SystemExit(f"ERROR: --key is not hexadecimal: {value!r}") from None


def border_key(image: Image.Image, inset: int = 2) -> tuple[int, int, int]:
    """Guess the key from the image border, where the subject is not.

    The most common border colour is the background by construction: a prompt
    that asked for a flat key and got one has thousands of identical border
    pixels, and a prompt that did not will show up as a low-confidence guess.
    """
    width, height = image.size
    pixels = image.convert("RGB").load()
    counts: dict[tuple[int, int, int], int] = {}
    for x in range(width):
        for y in (inset, height - 1 - inset):
            counts[pixels[x, y]] = counts.get(pixels[x, y], 0) + 1
    for y in range(height):
        for x in (inset, width - 1 - inset):
            counts[pixels[x, y]] = counts.get(pixels[x, y], 0) + 1
    colour, count = max(counts.items(), key=lambda item: item[1])
    total = 2 * (width + height)
    if count / total < 0.5:
        print(
            f"WARN: the border is only {count / total:.0%} one colour ({colour}); "
            "this source probably has no flat key. Regenerate it asking for an "
            "exactly flat #ff00ff background rather than thresholding a gradient.",
            file=sys.stderr,
        )
    return colour


def distance(pixel: tuple[int, int, int], key: tuple[int, int, int]) -> float:
    squared = sum((a - b) ** 2 for a, b in zip(pixel, key, strict=True))
    return math.sqrt(squared)


def key_out(
    image: Image.Image,
    key: tuple[int, int, int],
    transparent: float,
    opaque: float,
    despill: bool,
) -> tuple[Image.Image, float]:
    """Replace the key colour with alpha, keeping the soft transition band."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    source = rgba.load()
    output = Image.new("RGBA", (width, height))
    target = output.load()
    # Thresholds are given as percentages of the 0..441 RGB distance range, so
    # the same numbers work whatever the key colour is.
    near = transparent / 100.0 * 441.67
    far = opaque / 100.0 * 441.67
    if far <= near:
        raise SystemExit("ERROR: --opaque-threshold must be above --transparent-threshold")
    opaque_pixels = 0
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = source[x, y]
            separation = distance((red, green, blue), key)
            if separation <= near:
                target[x, y] = (red, green, blue, 0)
                continue
            coverage = 1.0 if separation >= far else (separation - near) / (far - near)
            if despill and coverage < 1.0:
                # In the transition band the pixel is part subject, part key.
                # Pull it away from the key so the edge does not keep its tint.
                red, green, blue = (
                    max(0, min(255, round(channel - (1.0 - coverage) * (key_channel - 128) * 0.6)))
                    for channel, key_channel in ((red, key[0]), (green, key[1]), (blue, key[2]))
                )
            new_alpha = round(alpha * coverage)
            target[x, y] = (red, green, blue, new_alpha)
            if new_alpha > 8:
                opaque_pixels += 1
    return output, opaque_pixels / float(width * height)


def luma_to_alpha(
    image: Image.Image, black_point: float, white_rgb: bool
) -> tuple[Image.Image, float]:
    """Turn a grayscale-on-black mask into a white RGBA particle card."""
    grey = image.convert("L")
    width, height = grey.size
    source = grey.load()
    output = Image.new("RGBA", (width, height))
    target = output.load()
    floor = black_point / 100.0 * 255.0
    span = max(255.0 - floor, 1.0)
    colour = image.convert("RGB").load()
    covered = 0
    for y in range(height):
        for x in range(width):
            alpha = round(max(0.0, source[x, y] - floor) / span * 255.0)
            if white_rgb:
                target[x, y] = (255, 255, 255, alpha)
            else:
                red, green, blue = colour[x, y]
                target[x, y] = (red, green, blue, alpha)
            if alpha > 8:
                covered += 1
    return output, covered / float(width * height)


def keep_alpha(image: Image.Image, white_rgb: bool) -> tuple[Image.Image, float]:
    """Keep a source's own alpha channel and only whiten its RGB.

    A generated "opacity mask" often arrives with alpha **already baked in and
    unequal to its luma** — the source this mode was written for peaks at alpha
    251 where its brightness peaks at 135. Recomputing alpha from brightness
    there does not clean the card up; it caps it near half opacity, and the
    result is a visibly fainter particle that nothing in the pipeline flags.

    So: when the source already has real alpha, keep it. `luma` is for the
    other case, a mask drawn as grey on black with no alpha at all.
    """
    output = image.convert("RGBA")
    alpha = output.getchannel("A")
    if white_rgb:
        white = Image.new("RGB", output.size, (255, 255, 255))
        white.putalpha(alpha)
        output = white
    histogram = alpha.histogram()
    covered = sum(histogram[9:])
    return output, covered / float(output.width * output.height)


def finish(image: Image.Image, args: argparse.Namespace) -> Image.Image:
    if args.trim:
        box = image.getbbox()
        if box:
            image = image.crop(box)
    if args.size:
        if args.pad:
            inner = int(args.size * args.pad)
            image.thumbnail((inner, inner), Image.LANCZOS)
            padded = Image.new("RGBA", (args.size, args.size), (0, 0, 0, 0))
            padded.paste(
                image,
                ((args.size - image.width) // 2, (args.size - image.height) // 2),
            )
            image = padded
        else:
            image = image.resize((args.size, args.size), Image.LANCZOS)
    if getattr(args, "white_rgb", False):
        # Padding above adds fully transparent *black* texels, and a card's
        # RGB is read at the edge whatever its alpha says: bilinear filtering
        # blends those texels into the visible rim and darkens it. A white
        # card must be white everywhere, including where it is invisible.
        alpha = image.getchannel("A")
        white = Image.new("RGB", image.size, (255, 255, 255))
        white.putalpha(alpha)
        image = white
    return image


def save(image: Image.Image, destination: Path) -> None:
    with atomic.staged_write(destination) as staged:
        image.save(staged, "PNG")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "EXAMPLES\n"
            "  shamway generate cutout key art/nuke-v4-chromakey.png art/nuke-v4.png\n"
            "      remove an auto-detected flat background, keeping soft edges\n\n"
            "  shamway generate cutout key art/icon-src.png UIAtlases/ItemIconAtlas/myModNuke.png \\\n"
            "      --size 160 --pad 0.9 --trim\n"
            "      cut out, trim to the subject, and centre it in a 160 px atlas cell\n\n"
            "  shamway generate cutout luma art/smoke-mask.png art/smoke-card.png --black-point 15\n"
            "      grayscale puff mask to a white RGBA particle card\n"
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("source", type=Path)
        sub.add_argument("output", type=Path)
        sub.add_argument("--size", type=int, help="square output size, e.g. 160 for an atlas cell")
        sub.add_argument(
            "--pad",
            type=float,
            default=None,
            help="fraction of --size the subject may fill (0.9 leaves a margin)",
        )
        sub.add_argument(
            "--trim", action="store_true", help="crop to the opaque bounding box first"
        )

    key_parser = commands.add_parser("key", help="remove a flat chroma-key background")
    common(key_parser)
    key_parser.add_argument(
        "--key", help="#rrggbb key colour; auto-detected from the border if absent"
    )
    key_parser.add_argument(
        "--transparent-threshold",
        type=float,
        default=12.0,
        help="percent distance from the key that is still fully transparent (default 12)",
    )
    key_parser.add_argument(
        "--opaque-threshold",
        type=float,
        default=50.0,
        help="percent distance from the key that is fully opaque (default 50)",
    )
    key_parser.add_argument(
        "--no-despill",
        dest="despill",
        action="store_false",
        help="keep the key tint in the transition band (almost never wanted)",
    )

    luma_parser = commands.add_parser("luma", help="grayscale-on-black mask to RGBA")
    common(luma_parser)
    luma_parser.add_argument(
        "--black-point",
        type=float,
        default=15.0,
        help="percent brightness treated as empty (default 15, removes the generator's haze)",
    )
    luma_parser.add_argument(
        "--keep-colour",
        dest="white_rgb",
        action="store_false",
        help="keep the source RGB instead of making it white",
    )

    alpha_parser = commands.add_parser(
        "alpha", help="source that already has alpha: keep it, whiten the RGB"
    )
    common(alpha_parser)
    alpha_parser.add_argument(
        "--keep-colour",
        dest="white_rgb",
        action="store_false",
        help="keep the source RGB instead of making it white",
    )

    args = parser.parse_args(argv)
    require_imaging()
    if not args.source.is_file():
        raise SystemExit(f"ERROR: no such image: {args.source}")
    with Image.open(args.source) as opened:
        image = opened.copy()

    if args.command == "key":
        key = parse_colour(args.key) if args.key else border_key(image)
        result, coverage = key_out(
            image, key, args.transparent_threshold, args.opaque_threshold, args.despill
        )
        print(f"key:      #{key[0]:02x}{key[1]:02x}{key[2]:02x}")
    elif args.command == "luma":
        result, coverage = luma_to_alpha(image, args.black_point, args.white_rgb)
        print(f"black:    {args.black_point:.0f}%")
    else:
        if "A" not in image.getbands():
            raise SystemExit(
                f"ERROR: {args.source} has no alpha channel to keep "
                "(bands: {}); use `cutout luma` for a grayscale mask, or "
                "`cutout key` for a flat key background.".format("".join(image.getbands()))
            )
        result, coverage = keep_alpha(image, args.white_rgb)
        print("alpha:    kept from the source")

    if coverage < 0.01:
        if args.command == "alpha":
            raise SystemExit(
                "ERROR: the source's alpha channel is essentially empty. It may be a "
                "grayscale mask with a placeholder alpha; try `cutout luma`."
            )
        raise SystemExit(
            "ERROR: the result is essentially empty; the key matched the subject too. "
            "Widen --transparent-threshold's gap to --opaque-threshold, or pass an "
            "explicit --key."
        )
    if coverage > 0.99:
        print(
            "WARN: nothing became transparent. The source probably has no flat key — "
            "check it, rather than shipping an opaque cell.",
            file=sys.stderr,
        )

    result = finish(result, args)
    save(result, args.output)
    print(f"source:   {args.source} ({image.width}x{image.height})")
    print(f"output:   {args.output} ({result.width}x{result.height} RGBA)")
    print(f"coverage: {coverage:.1%} of pixels opaque before trimming")
    print("next:     look at it on a light AND a dark background; a fringe hides on one")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
