#!/usr/bin/env python3
"""Derive normal and mask maps from an albedo, or a tileable detail normal from seeded noise.

    texture-maps albedo paint.png --out-dir Bundle/Textures --stem myModPaint
    texture-maps albedo paint.png --out-dir T --stem s --metallic 0.58 --smoothness 0.16
    texture-maps detail --out-dir T --stem myModSteel --size 512 --anisotropy 2.6 --seed 7
    texture-maps detail --out-dir T --stem myModRubber --size 256 --exponent -1.5 --slope 0.42

(The bare form `texture-maps paint.png ...` still means `albedo`.)

**Why derive rather than author.** An albedo's scratches, chipped paint, weld
seams and grime are exactly the features that should also displace and change
reflectance. Deriving the normal and the mask from it keeps the three maps in
register by construction; a hand-painted normal drifts the next time the
albedo is regenerated.

**The reflectance rule, stated once.** The mask map is *variation around the
scalar values the material already used*, not a new look. Unity's Standard
shader ignores `_Metallic` and `_Glossiness` entirely once `_METALLICGLOSSMAP`
is on, so the channel means are pinned to the `--metallic` and `--smoothness`
you pass — which should be the scalars the flat material shipped with. That is
what keeps a signed palette intact while the surface gains relief.

**Only high-frequency detail becomes relief.** The height field is the
luminance minus its own wide blur (`--detail-radius`), so a scratch embosses
and the broad olive-to-charcoal drift of the paint does not. The normal is then
rescaled so its 99th-percentile slope lands at `--slope` (tan 19° ≈ 0.35, a
visible but never rubbery relief), which keeps one tuning constant meaningful
across sources with very different contrast.

**Detail normals are periodic by construction.** `detail` shapes seeded white
noise in the frequency domain and transforms back, so the field wraps exactly —
the property a cylinder primitive's default UVs need. `--anisotropy` above 1
stretches the surviving frequencies along V for a brushed, machined look; 1 is
isotropic and reads as pebbled rubber or cast metal. Use a separate, coarser
and softer detail normal for rubber than for steel, so adjacent parts never
read as the same surface.

Unity mask-map channel order (Standard shader): R metallic, G occlusion,
B unused, A smoothness. One texture feeds **both** `_MetallicGlossMap` (R, A)
and `_OcclusionMap` (G); assign it to both slots or the occlusion is never
sampled. Import the normal as "Normal map" and the mask as **linear**
(`sRGBTexture = false`); a mask imported as sRGB is numerically wrong even
though it looks fine. The material must also enable `_NORMALMAP` and
`_METALLICGLOSSMAP`, which `GeneratedAsset.StandardMaterial` does.

Green channel: this emits the OpenGL/Unity convention (+Y up the texture).
`--flip-green` emits DirectX for a tool that expects it.

`--also DIR` writes a byte-identical second copy — the convention is to keep
the editable source under `assets-src/textures/` and promote the same bytes
into the bundle folder in one run, so the shipped map cannot drift from its
recorded design.

Requires Pillow and NumPy.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

from ..capabilities import extra_install

MISSING = None
try:
    import numpy as np
    from PIL import Image, ImageFilter
except ImportError as error:  # pragma: no cover - depends on host packages
    # Deferred, not fatal: --help must work on a bare host, so someone can read
    # what this needs before installing anything.
    MISSING = str(error)

DEFAULT_SLOPE_P99 = 0.35
DEFAULT_DETAIL_RADIUS = 24.0


def require_imaging() -> None:
    """Fail with the install command, at the point the dependency is used."""
    if MISSING is not None:
        raise SystemExit(
            "ERROR: the texture lane needs Pillow and NumPy ({}).\n"
            "  Install it with: {}".format(MISSING, extra_install("authoring"))
        )


def save_atomically(array: np.ndarray, path: Path, mode: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".png", dir=path.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        Image.fromarray(array, mode).save(temporary_path, "PNG", optimize=True)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def promote(path: Path, also: Path | None) -> Path | None:
    """Copy a finished output byte-for-byte into a second directory."""
    if also is None:
        return None
    also.mkdir(parents=True, exist_ok=True)
    target = also / path.name
    shutil.copyfile(path, target)
    return target


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# ------------------------------------------------------------------ imaging


def luminance(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def blur(field: np.ndarray, radius: float) -> np.ndarray:
    """Gaussian blur through Pillow, so the result matches what an artist sees."""
    image = Image.fromarray(np.clip(field * 255.0, 0, 255).astype(np.uint8), "L")
    return np.asarray(image.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float64) / 255.0


def height_from_albedo(rgb: np.ndarray, detail_radius: float = DEFAULT_DETAIL_RADIUS) -> np.ndarray:
    """High-frequency relief: the albedo's luminance minus its own low-pass."""
    lum = luminance(rgb)
    return lum - blur(lum, detail_radius)


def normal_map(height: np.ndarray, slope_p99: float = DEFAULT_SLOPE_P99, flip_green: bool = False) -> np.ndarray:
    """Tangent-space normal map, +X right, +Y up, +Z out of the surface.

    Gradients are wrapped central differences, so a tileable height field stays
    tileable. They are rescaled so the 99th-percentile slope is `slope_p99`.
    Image rows grow downward while tangent +Y points up the texture, which is
    why the Y component takes +dy: the surface rising toward the bottom of the
    image tilts the normal toward -Y.
    """
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * 0.5
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * 0.5
    reference = np.percentile(np.hypot(dx, dy), 99)
    if reference > 1e-9:
        scale = slope_p99 / reference
        dx = dx * scale
        dy = dy * scale
    nx, ny, nz = -dx, dy, np.ones_like(dx)
    if flip_green:
        ny = -ny
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    packed = np.stack([nx / length, ny / length, nz / length], axis=-1) * 0.5 + 0.5
    return np.clip(packed * 255.0, 0, 255).astype(np.uint8)


def centred(field: np.ndarray, swing: float) -> np.ndarray:
    """Map a field onto [-swing, swing] by its own 1st/99th percentiles.

    Percentiles rather than the maximum, so one outlier pixel cannot flatten
    everything else.
    """
    low, high = np.percentile(field, 1), np.percentile(field, 99)
    if high - low < 1e-9:
        return np.zeros_like(field)
    return np.clip((field - low) / (high - low) * 2.0 - 1.0, -1.0, 1.0) * swing


def zero_mean(field: np.ndarray) -> np.ndarray:
    """Remove the field's own mean, so adding it to a scalar preserves that
    scalar as the map's mean — the reflectance rule."""
    return field - field.mean()


def mask_map(
    rgb: np.ndarray,
    metallic_mean: float,
    smoothness_mean: float,
    metallic_swing: float = 0.34,
    smoothness_swing: float = 0.20,
    detail_radius: float = DEFAULT_DETAIL_RADIUS,
) -> np.ndarray:
    """Pack R = metallic, G = occlusion, B = 0, A = smoothness.

    Brighter, cleaner albedo pixels (a band-pass of the luminance, so it is
    local brightness rather than the paint colour) read as metal scuffed bare
    and glossier; dark grimy ones as dull. Fine roughness lowers smoothness.
    Occlusion is **cavity only**: the dark side of the relief, softened, so it
    reads as dirt in a seam rather than an outline around every scratch — and
    its mean stays near 1, because a whole surface half-occluded is simply a
    darker albedo.
    """
    lum = luminance(rgb)
    detail = lum - blur(lum, detail_radius)
    tone = zero_mean(centred(blur(lum, 6.0) - blur(lum, 96.0), 1.0))
    roughness = zero_mean(centred(blur(np.abs(detail), 4.0), 1.0))
    metallic = metallic_mean + tone * metallic_swing
    smoothness = smoothness_mean + (tone - roughness * 0.6) * smoothness_swing
    cavity = blur(np.clip(-detail, 0.0, None), 5.0)
    occlusion = np.clip(1.0 - centred(cavity, 0.5), 0.35, 1.0)
    channels = [
        np.clip(metallic, 0.0, 1.0),
        occlusion,
        np.zeros_like(lum),
        np.clip(smoothness, 0.0, 1.0),
    ]
    return np.stack([np.clip(c * 255.0, 0, 255).astype(np.uint8) for c in channels], axis=-1)


def tileable_noise(size: int, rng: np.random.Generator, exponent: float, anisotropy: float) -> np.ndarray:
    """Periodic noise: white noise shaped in the frequency domain.

    Filtering an FFT and transforming back yields a field that wraps exactly.
    `exponent` is the spectral slope (more negative = smoother, larger
    features); `anisotropy` > 1 stretches the surviving frequencies along V.
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


# ---------------------------------------------------------------------- CLI


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--stem", required=True, help="output stem; files get Normal/Mask suffixes")
    parser.add_argument("--also", type=Path, default=None, help="write a byte-identical copy here too")
    parser.add_argument("--flip-green", action="store_true", help="emit a DirectX-convention normal")
    parser.add_argument(
        "--slope", type=float, default=DEFAULT_SLOPE_P99, help="99th-percentile tangent slope of the normal"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)

    albedo = sub.add_parser("albedo", help="derive a normal and a mask from an albedo")
    albedo.add_argument("albedo", type=Path)
    _add_common(albedo)
    albedo.add_argument("--metallic", type=float, default=0.5, help="mean of the R channel")
    albedo.add_argument("--smoothness", type=float, default=0.3, help="mean of the A channel")
    albedo.add_argument("--metallic-swing", type=float, default=0.34)
    albedo.add_argument("--smoothness-swing", type=float, default=0.20)
    albedo.add_argument(
        "--detail-radius", type=float, default=DEFAULT_DETAIL_RADIUS,
        help="blur radius in source pixels; detail finer than this becomes relief",
    )
    albedo.add_argument("--no-mask", action="store_true", help="emit the normal only")

    detail = sub.add_parser("detail", help="generate a tileable detail normal from seeded noise")
    _add_common(detail)
    detail.add_argument("--size", type=int, default=512, help="512 for steel, 256 for rubber are proven")
    detail.add_argument("--seed", type=int, required=True)
    detail.add_argument("--exponent", type=float, default=-1.05, help="spectral slope; -1.5 is coarser")
    detail.add_argument("--anisotropy", type=float, default=1.0, help=">1 brushes along V; 2.6 reads as machined")
    detail.add_argument(
        "--grit", type=float, default=0.0,
        help="add this much finer isotropic noise on top (0.35 gives pitted steel)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in ("albedo", "detail", "-h", "--help"):
        argv.insert(0, "albedo")
    args = build_parser().parse_args(argv)
    require_imaging()
    if args.mode == "albedo":
        return _run_albedo(args)
    return _run_detail(args)


def _run_albedo(args: argparse.Namespace) -> int:
    if not args.albedo.is_file():
        raise SystemExit(f"ERROR: no such albedo: {args.albedo}")
    for name, value in (("--metallic", args.metallic), ("--smoothness", args.smoothness)):
        if not 0.0 <= value <= 1.0:
            raise SystemExit(f"ERROR: {name} must be in [0, 1]")
    with Image.open(args.albedo) as source:
        rgb = np.asarray(source.convert("RGB"), dtype=np.float64) / 255.0
        width, height = source.size

    normal = normal_map(height_from_albedo(rgb, args.detail_radius), args.slope, args.flip_green)
    normal_path = args.out_dir / f"{args.stem}Normal.png"
    save_atomically(normal, normal_path, "RGB")
    copied = promote(normal_path, args.also)
    print(f"albedo:     {args.albedo} ({width}x{height})")
    print(f"normal:     {normal_path}  ({'DirectX' if args.flip_green else 'OpenGL'} green)  sha256 {sha256(normal_path)}")
    if copied:
        print(f"also:       {copied}")

    if not args.no_mask:
        mask = mask_map(
            rgb, args.metallic, args.smoothness, args.metallic_swing, args.smoothness_swing, args.detail_radius
        )
        mask_path = args.out_dir / f"{args.stem}Mask.png"
        save_atomically(mask, mask_path, "RGBA")
        copied = promote(mask_path, args.also)
        metallic = mask[..., 0] / 255.0
        smoothness = mask[..., 3] / 255.0
        occlusion = mask[..., 1] / 255.0
        print(f"mask:       {mask_path}  (R metallic, G occlusion, A smoothness)  sha256 {sha256(mask_path)}")
        if copied:
            print(f"also:       {copied}")
        print(f"metallic:   mean {metallic.mean():.4f}  range {metallic.min():.3f}..{metallic.max():.3f}")
        print(f"smoothness: mean {smoothness.mean():.4f}  range {smoothness.min():.3f}..{smoothness.max():.3f}")
        print(f"occlusion:  mean {occlusion.mean():.4f}  min {occlusion.min():.3f} (cavity only)")
    print("import:     normal as 'Normal map'; mask as linear (sRGBTexture = false);")
    print("            assign the mask to BOTH _MetallicGlossMap and _OcclusionMap")
    return 0


def _run_detail(args: argparse.Namespace) -> int:
    if args.size < 16 or args.size & (args.size - 1):
        raise SystemExit("ERROR: --size must be a power of two (256, 512, 1024)")
    rng = np.random.default_rng(args.seed)
    field = tileable_noise(args.size, rng, args.exponent, args.anisotropy)
    if args.grit:
        field = field + args.grit * tileable_noise(args.size, rng, exponent=-0.35, anisotropy=1.0)
    normal = normal_map(field * 0.05, args.slope, args.flip_green)
    normal_path = args.out_dir / f"{args.stem}Normal.png"
    save_atomically(normal, normal_path, "RGB")
    copied = promote(normal_path, args.also)
    print(f"detail:     {normal_path}  {args.size}x{args.size}  tileable  sha256 {sha256(normal_path)}")
    print(f"recipe:     seed {args.seed}  exponent {args.exponent}  anisotropy {args.anisotropy}  grit {args.grit}  slope {args.slope}")
    if copied:
        print(f"also:       {copied}")
    print("import:     as 'Normal map'; assign as _BumpMap with a tiling scale on a flat-colour material")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
