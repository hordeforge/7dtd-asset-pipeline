#!/usr/bin/env python3
"""Draw a fur/hide albedo procedurally for a generated entity, with no image model.

A synthesized entity's body is primitives bound to a rig, and its albedo is
what makes that read as a creature instead of a green mesh. Asking an image
model for "a fur texture" reliably returns a photograph of a dog; this
generator draws the three things a hide actually is — broad mottled patches,
anisotropic fur clumps, and a fine hair grain — as seeded noise, so the same
arguments produce the same bytes and a regenerated skin never shows up as a
diff for no reason.

    shamway generate hide assets-src/bundle/myWolf_albedo.png --seed 7
    shamway generate hide assets-src/bundle/myWolf_albedo.png \
        --base 96,80,60 --fur 140,120,90 --strength 0.5 --size 256
    shamway generate hide assets-src/bundle/myWolf_albedo.png \
        --base 192,180,152 --patch 70,55,40 --patch-strength 0.7
        a cream coat with dark spots — two-tone, readable against both
        forest and dirt
    shamway generate hide assets-src/bundle/myWolf_albedo.png --size 512
        a 512 px skin for a large entity

The output is a square albedo written at `{stem}_albedo`-style paths — the
bundle writer binds `<stem>_albedo.png` to the prefab's material when it sits
beside the mesh — and it is tuned for an unlit textured material: mid-value
base colour, modest contrast, no pure black or white, so the primitives read
as hide rather than as stripes. `--patch` adds a second coat colour (dark
spots on the base), which is what makes a generated entity's silhouette and
its leg-ground boundary readable against both forest and dirt — a single
flat hue disappears into whatever the biome is.

The pattern is periodic by construction (the same FFT-shaping `texture-maps
detail` uses), which a primitive's default UVs need — a seam where the noise
wraps is invisible when the noise itself wraps.

**Atlas mode.** A generated entity merges every part into one mesh where each
part's vertices span the whole 0-1 UV box, so no single coat can reserve a
colour for the feet — the paws and the body read as one object and the
ground junction disappears. `shamway generate entity --atlas` instead gives
each part its own cell of the texture and writes a manifest; pass that to
`generate hide --atlas` and each cell is painted the role colour its part
demands (paw dark, limb a shade, body the coat), with the gutters filled by
`--outline` so every part's silhouette reads against the terrain. Each atlas
cell draws its own periodic field at the cell's own pixel size, so a
primitive's wrapping default UVs never seam inside its cell:

    shamway generate entity myWolf.glb --atlas myWolf.atlas.json
    shamway generate hide assets-src/bundle/myWolf_albedo.png \
        --atlas myWolf.atlas.json --seed 7

Needs Pillow and NumPy; `shamway capabilities --missing` prints the install
command for this host.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from .. import atomic
from ..capabilities import extra_install

MISSING = None
try:
    import numpy as np
    from PIL import Image
except ImportError as error:  # pragma: no cover - depends on host packages
    # Deferred, not fatal: --help must work on a bare host, so someone can read
    # what this needs before installing anything.
    MISSING = str(error)


def require_imaging() -> None:
    """Fail with the install command, at the point the dependency is used."""
    if MISSING is not None:
        raise SystemExit(
            "ERROR: the hide lane needs Pillow and NumPy ({}).\n  Install them with: {}".format(
                MISSING, extra_install("authoring")
            )
        )


def tileable_noise(
    size: int, rng: np.random.Generator, exponent: float, anisotropy: float
) -> np.ndarray:
    """Periodic noise: white noise shaped in the frequency domain.

    Filtering an FFT and transforming back yields a field that wraps exactly,
    so a primitive's default UVs never show a seam. `exponent` is the spectral
    slope (more negative = smoother, larger features); `anisotropy` > 1
    stretches the surviving frequencies along V.
    """
    field = rng.standard_normal((size, size))
    fy = np.fft.fftfreq(size)[:, None]
    fx = np.fft.fftfreq(size)[None, :]
    radius = np.sqrt((fx * anisotropy) ** 2 + (fy / anisotropy) ** 2)
    radius[0, 0] = 1e-6
    shaped = np.fft.ifft2(np.fft.fft2(field) * radius**exponent).real
    shaped -= shaped.mean()
    peak = np.abs(shaped).max()
    return shaped / peak if peak > 1e-9 else shaped


def hide_rgb(
    size: int,
    seed: int,
    base: tuple[int, int, int],
    fur: tuple[int, int, int],
    patch: tuple[int, int, int],
    strength: float,
    fur_strength: float,
    patch_strength: float,
    grain: float,
) -> np.ndarray:
    """A (size, size, 3) albedo: mottled hide with fur clumps, spots, hair grain.

    Four noise layers, one per scale: broad patches (`strength`), dark spots
    in the positive patch regions (`patch_strength`), anisotropic fur clumps
    stretched along V (`fur_strength`), and a fine isotropic grain. Every layer
    is periodic, so the texture tiles on a primitive's default UVs. `patch`
    (default a dark shade of `base`) is what makes the hide two-tone: a single
    flat hue disappears into the biome, and the leg-ground boundary becomes
    invisible with it.
    """
    rng = np.random.default_rng(seed)
    patches = tileable_noise(size, rng, exponent=-1.6, anisotropy=1.0)
    clumps = tileable_noise(size, rng, exponent=-1.1, anisotropy=2.6)
    hair = tileable_noise(size, rng, exponent=-0.35, anisotropy=1.0)

    base_array = np.asarray(base, dtype=np.float64)
    fur_array = np.asarray(fur, dtype=np.float64)
    patch_array = np.asarray(patch, dtype=np.float64)
    mottle = 1.0 + patches * strength  # broad hide patches
    spot = np.clip(patches * 0.5 + 0.5, 0.0, 1.0)  # 0..1 spot field
    clump = np.clip(clumps * 0.5 + 0.5, 0.0, 1.0)  # 0..1 fur-clump field
    rgb = base_array[None, None, :] * mottle[..., None]
    # Spots are a colour mix, not a tint: where the spot field is high the
    # patch colour wins outright (`patch_strength` 1 = solid spots), so the
    # two tones are actually apart instead of a muddy middle.
    blend = spot * patch_strength
    rgb = rgb * (1.0 - blend)[..., None] + patch_array[None, None, :] * blend[..., None]
    # Clumps shift the coat toward the fur colour (`fur_strength` 0 = base only).
    rgb = rgb + (fur_array - base_array)[None, None, :] * (clump * fur_strength)[..., None]
    # The hair grain is luminance noise, blended softly so it reads as coat
    # rather than as static.
    rgb = rgb * (1.0 + hair * grain)[..., None]
    return np.clip(np.clip(rgb, 0.0, 255.0).astype(np.uint8), 0, 255)


# Whole-texture hide for a primitive whose UVs span [0, 1]. In atlas mode each
# part's UVs are confined to a cell, so each cell draws its own periodic field
# — a field across the whole texture would not wrap inside a cell and would
# seam where a primitive's default UVs wrap.
def _cell_field(
    rng: np.random.Generator, cell_px: int, strength: float, fur_strength: float, grain: float
) -> np.ndarray:
    """A periodic fur field the size of one atlas cell, in `[0, 1]` per channel.

    The cell is square (the entity atlas uses a square grid), so a field
    generated at exactly `cell_px` tiles it with no seam — which is what a
    primitive's default UVs need once they are confined to that cell. The three
    noise layers and the clump-anisotropy match `hide_rgb`, so an atlased hide
    and a whole-coat hide read as the same species.
    """
    patches = tileable_noise(cell_px, rng, exponent=-1.6, anisotropy=1.0)
    clumps = tileable_noise(cell_px, rng, exponent=-1.1, anisotropy=2.6)
    hair = tileable_noise(cell_px, rng, exponent=-0.35, anisotropy=1.0)
    mottle = 1.0 + patches * strength
    clump = np.clip(clumps * 0.5 + 0.5, 0.0, 1.0)
    field = mottle * (1.0 + clump * fur_strength)  # one planar field, no colour yet
    return field * (1.0 + hair * grain)


def hide_atlas_rgb(
    size: int,
    seed: int,
    grid: int,
    cells: dict[str, tuple[float, float, float, float]],
    roles: dict[str, str],
    base: tuple[int, int, int],
    fur: tuple[int, int, int],
    paw: tuple[int, int, int],
    limb: tuple[int, int, int],
    outline: tuple[int, int, int],
    strength: float,
    fur_strength: float,
    patch_strength: float,
    grain: float,
) -> np.ndarray:
    """A (size, size, 3) albedo for an atlased entity: one field per cell.

    Every part owns one cell of the atlas (set up by `shamway generate entity
    --atlas`), so this generator paints each cell a role colour instead of one
    whole-coat hue. That is the contrast a rendered creature needs: with every
    part sampling the same texture no colour can be reserved for the feet, so
    the paws and the body read as one object and the ground junction vanishes.
    Here `paw` cells go dark (contact), `limb` cells a shade, and the rest the
    base coat — so the legs, the body, and each hoof are distinguishable in a
    single frame. The gutter between cells is painted `outline`, which is the
    darker edging that makes each part's silhouette legible.

    Each cell is drawn with its own periodic field (see `_cell_field`) so a
    primitive's wrapping default UVs never show a seam inside the cell, and the
    same seed gives the same bytes in the same cells. `patch_strength` is
    accepted for signature parity with `hide_rgb` but does not shift the base
    coat here — in atlas mode the role colour is the discrimination, and a spot
    on a paw cell would dilute it.
    """
    cell_px = max(16, size // grid)
    rng = np.random.default_rng(seed)

    field = _cell_field(rng, cell_px, strength, fur_strength, grain)
    base_array = np.asarray(base, dtype=np.float64)
    fur_array = np.asarray(fur, dtype=np.float64)
    paw_array = np.asarray(paw, dtype=np.float64)
    limb_array = np.asarray(limb, dtype=np.float64)
    outline_array = np.asarray(outline, dtype=np.float64)

    out = np.empty((size, size, 3), dtype=np.uint8)
    out[...] = outline_array[None, None, :]

    for name, (u0, v0, u1, v1) in cells.items():
        role = roles.get(name, "body")
        if role == "paw":
            fill = paw_array[None, None, :] * field[..., None]
        elif role == "limb":
            fill = limb_array[None, None, :] * field[..., None]
        elif role in {"head", "tail"}:
            fill = fur_array[None, None, :] * field[..., None]
        else:
            fill = base_array[None, None, :] * field[..., None]
        fill = np.clip(fill, 0.0, 255.0).astype(np.uint8)

        # Paste the cell field into the cell's pixel rect, least-remainder
        # so the UV-inset the mesh applies never lands on a shared edge.
        x0 = round(u0 * size)
        x1 = round(u1 * size)
        y0 = round((1.0 - v1) * size)
        y1 = round((1.0 - v0) * size)
        fh = y1 - y0
        fw = x1 - x0
        if fh <= 0 or fw <= 0:
            continue
        cell_field = np.resize(fill, (fh, fw, 3)) if (fh, fw) != (cell_px, cell_px) else fill
        out[y0:y1, x0:x1] = cell_field
    return out


def save(image: np.ndarray, destination: Path) -> None:
    with atomic.staged_write(destination) as staged:
        Image.fromarray(image, "RGB").save(staged, "PNG", optimize=True)


def parse_colour(text: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in text.split(","))
    except ValueError as error:
        raise SystemExit(f"ERROR: --base/--fur must be R,G,B integers, got {text!r}") from error
    if len(parts) != 3 or any(part < 0 or part > 255 for part in parts):
        raise SystemExit(f"ERROR: --base/--fur must be R,G,B integers in 0..255, got {text!r}")
    return (parts[0], parts[1], parts[2])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "EXAMPLES\n"
            "  shamway generate hide assets-src/bundle/myWolf_albedo.png --seed 7\n"
            "      the default mossy-green hide, deterministic at that seed\n"
            "  shamway generate hide assets-src/bundle/myWolf_albedo.png \\\n"
            "      --base 96,80,60 --fur 140,120,90 --strength 0.5\n"
            "      a brown-grey hide with lighter fur clumps\n"
            "  shamway generate hide assets-src/bundle/myWolf_albedo.png --size 512\n"
            "      a 512 px skin for a large entity\n"
        ),
    )
    parser.add_argument("output", type=Path, help="write the albedo PNG here")
    parser.add_argument(
        "--size", type=int, default=256, help="square texture size in pixels (default 256)"
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="pattern seed; the same seed is the same skin"
    )
    parser.add_argument(
        "--base",
        default="85,109,73",
        help="base hide colour as R,G,B (default 85,109,73, the self-test creature's green)",
    )
    parser.add_argument(
        "--fur",
        default=None,
        help="fur-clump colour as R,G,B; defaults to a lighter --base",
    )
    parser.add_argument(
        "--patch",
        default=None,
        help="spot colour as R,G,B; defaults to a darker --base. A second tone is"
        " what makes the hide readable against both forest and dirt",
    )
    parser.add_argument(
        "--strength",
        type=float,
        default=0.5,
        help="mottle contrast in [0, 1]; 0 is a flat colour (default 0.5)",
    )
    parser.add_argument(
        "--fur-strength",
        type=float,
        default=0.3,
        help="fur-clump contrast in [0, 1] (default 0.3)",
    )
    parser.add_argument(
        "--patch-strength",
        type=float,
        default=0.7,
        help="spot contrast in [0, 1] (default 0.7)",
    )
    parser.add_argument(
        "--grain",
        type=float,
        default=0.15,
        help="fine hair-grain luminance noise in [0, 1] (default 0.15)",
    )
    parser.add_argument(
        "--atlas",
        default=None,
        metavar="JSON",
        help="a per-part UV atlas manifest written by `shamway generate entity"
        " --atlas`. Each part then paints its own cell with its role colour —"
        " paws dark, limbs a shade, body the coat — instead of one whole-coat"
        " hue, and the gutters are filled with the --outline colour so each"
        " part's silhouette reads. This is the mode a rendered creature needs;"
        " without it every part shares the whole texture and one coat covers"
        " the entire animal",
    )
    parser.add_argument(
        "--paw",
        default=None,
        help="paw/hoof colour as R,G,B for --atlas mode; defaults to a dark"
        " shade of --base. The feet stay distinct from the legs and the ground",
    )
    parser.add_argument(
        "--limb",
        default=None,
        help="leg/arm colour as R,G,B for --atlas mode; defaults to a shade of"
        " --base between the body and the paw",
    )
    parser.add_argument(
        "--outline",
        default=None,
        help="the gutter colour between atlas cells as R,G,B; defaults to a"
        " dark neutral. A darker edging is what makes a part's silhouette, and"
        " the paw's contact with the ground, legible in a single frame",
    )
    args = parser.parse_args(argv)
    require_imaging()
    if args.size < 16:
        raise SystemExit(f"ERROR: --size must be at least 16 pixels, got {args.size}")
    for name, value in (
        ("--strength", args.strength),
        ("--fur-strength", args.fur_strength),
        ("--patch-strength", args.patch_strength),
        ("--grain", args.grain),
    ):
        if not 0.0 <= value <= 1.0:
            raise SystemExit(f"ERROR: {name} must be in [0, 1], got {value}")
    base = parse_colour(args.base)
    fur = (
        parse_colour(args.fur)
        if args.fur is not None
        else (
            min(255, int(base[0] * 1.3)),
            min(255, int(base[1] * 1.3)),
            min(255, int(base[2] * 1.3)),
        )
    )
    patch = (
        parse_colour(args.patch)
        if args.patch is not None
        else (max(0, int(base[0] * 0.45)), max(0, int(base[1] * 0.45)), max(0, int(base[2] * 0.45)))
    )

    if args.atlas:
        manifest = json.loads(Path(args.atlas).read_text(encoding="utf-8"))
        cells = manifest.get("parts")
        roles = manifest.get("roles")
        grid = manifest.get("grid")
        if not isinstance(cells, dict) or not cells:
            raise SystemExit(f"ERROR: {args.atlas} has no per-part cells")
        if not isinstance(roles, dict):
            roles = {}
        if not isinstance(grid, int) or grid < 1:
            grid = math.ceil(math.sqrt(len(cells)))
        paw = (
            parse_colour(args.paw)
            if args.paw is not None
            else (
                max(0, int(base[0] * 0.35)),
                max(0, int(base[1] * 0.35)),
                max(0, int(base[2] * 0.35)),
            )
        )
        limb = (
            parse_colour(args.limb)
            if args.limb is not None
            else (
                int(max(base[0], fur[0]) * 0.7),
                int(max(base[1], fur[1]) * 0.7),
                int(max(base[2], fur[2]) * 0.7),
            )
        )
        outline = (
            parse_colour(args.outline)
            if args.outline is not None
            else (
                max(0, int(base[0] * 0.2)),
                max(0, int(base[1] * 0.2)),
                max(0, int(base[2] * 0.2)),
            )
        )
        rgb = hide_atlas_rgb(
            args.size,
            args.seed,
            grid,
            cells,
            roles,
            base,
            fur,
            paw,
            limb,
            outline,
            args.strength,
            args.fur_strength,
            args.patch_strength,
            args.grain,
        )
        save(rgb, args.output)
        n_colours = len(np.unique(rgb.reshape(-1, 3), axis=0))
        print(
            f"wrote {args.output} ({args.size}x{args.size} atlased hide, seed"
            f" {args.seed}, {len(cells)} cells, base {base}, paw {paw},"
            f" outline {outline}, {n_colours} colours)"
        )
        return 0

    rgb = hide_rgb(
        args.size,
        args.seed,
        base,
        fur,
        patch,
        args.strength,
        args.fur_strength,
        args.patch_strength,
        args.grain,
    )
    if len(np.unique(rgb.reshape(-1, 3), axis=0)) < 8:
        raise SystemExit(
            "ERROR: those settings drew an (almost) flat colour; raise --strength or --grain"
        )
    save(rgb, args.output)
    print(
        f"wrote {args.output} ({args.size}x{args.size} hide, seed {args.seed},"
        f" base {base}, {len(np.unique(rgb.reshape(-1, 3), axis=0))} colours)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
