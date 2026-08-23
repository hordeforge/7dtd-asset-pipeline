#!/usr/bin/env python3
"""Derive a tangent-space normal map and a Unity mask map from an albedo.

Deriving both from the albedo keeps them in register by construction: a
hand-painted normal drifts out of alignment the next time the albedo changes,
while a derived one cannot. The mask map is *variation around the scalar values
the material already used*, not a new look, so the means are pinned to the
`--metallic` and `--smoothness` you pass.

    make-texture-maps.py albedo.png --out-dir Bundle/Textures --stem myModPaint
    make-texture-maps.py albedo.png --out-dir T --stem s --metallic 0.58 --smoothness 0.16

Unity mask-map channel order (Standard shader `_MetallicGlossMap` plus AO):
R metallic, G occlusion, B unused, A smoothness. Import the normal map with
texture type "Normal map" and the mask map as **linear** (`sRGBTexture = false`);
a mask imported as sRGB is numerically wrong even though it looks fine.
Assigning the maps is not enough either — the material must enable `_NORMALMAP`
and `_METALLICGLOSSMAP`, which `GeneratedAsset.StandardMaterial` does.

Requires Pillow and NumPy.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

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
            "ERROR: the texture lane needs Pillow and NumPy ({}).\n"
            "  Install it with: uv pip install 'sevendtd-asset-pipeline[authoring]'".format(MISSING)
        )


def save_atomically(array: "np.ndarray", path: Path, mode: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".png", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        Image.fromarray(array, mode).save(temporary_path, "PNG")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def luminance(image: "Image.Image") -> "np.ndarray":
    rgb = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def normal_map(height: "np.ndarray", strength: float) -> "np.ndarray":
    """Sobel gradients of the height field, wrapped so the result tiles."""
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * strength
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * strength
    normal = np.stack([-dx, -dy, np.ones_like(height)], axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    # Unity/OpenGL convention: +Y is up. DirectX-convention maps need G flipped.
    return np.clip((normal * 0.5 + 0.5) * 255.0, 0, 255).astype(np.uint8)


def pinned(values: "np.ndarray", mean: float, spread: float) -> "np.ndarray":
    """Rescale to the requested mean without exceeding [0, 1]."""
    centered = values - values.mean()
    scale = spread / (np.abs(centered).max() or 1.0)
    return np.clip(mean + centered * scale, 0.0, 1.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("albedo", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--stem", required=True, help="output stem; files get Normal/Mask suffixes")
    parser.add_argument("--strength", type=float, default=4.0, help="normal-map relief")
    parser.add_argument("--metallic", type=float, default=0.5, help="target mean of the R channel")
    parser.add_argument("--smoothness", type=float, default=0.3, help="target mean of the A channel")
    parser.add_argument("--spread", type=float, default=0.18, help="maximum swing around each mean")
    parser.add_argument("--flip-green", action="store_true", help="emit a DirectX-convention normal")
    args = parser.parse_args(argv)
    require_imaging()

    if not args.albedo.is_file():
        raise SystemExit(f"ERROR: no such albedo: {args.albedo}")
    for name, value in (("--metallic", args.metallic), ("--smoothness", args.smoothness)):
        if not 0.0 <= value <= 1.0:
            raise SystemExit(f"ERROR: {name} must be in [0, 1]")

    image = Image.open(args.albedo)
    height = luminance(image)

    normal = normal_map(height, args.strength)
    if args.flip_green:
        normal[..., 1] = 255 - normal[..., 1]
    normal_path = args.out_dir / f"{args.stem}Normal.png"
    save_atomically(normal, normal_path, "RGB")

    # Brighter, cleaner albedo pixels read as bare, glossier metal; dark grimy
    # ones as dull. Occlusion is the inverse of local brightness.
    metallic = pinned(height, args.metallic, args.spread)
    smoothness = pinned(height, args.smoothness, args.spread)
    occlusion = np.clip(0.5 + (height - height.mean()) * 0.5, 0.0, 1.0)
    mask = np.stack(
        [metallic, occlusion, np.zeros_like(height), smoothness], axis=-1
    )
    mask_path = args.out_dir / f"{args.stem}Mask.png"
    save_atomically((mask * 255.0).astype(np.uint8), mask_path, "RGBA")

    print(f"albedo:     {args.albedo} ({image.width}x{image.height})")
    print(f"normal:     {normal_path}  ({'DirectX' if args.flip_green else 'OpenGL'} green)")
    print(f"mask:       {mask_path}  (R metallic, G occlusion, A smoothness)")
    print(f"metallic:   mean {metallic.mean():.4f}  range {metallic.min():.3f}..{metallic.max():.3f}")
    print(f"smoothness: mean {smoothness.mean():.4f}  range {smoothness.min():.3f}..{smoothness.max():.3f}")
    print("import:     normal as 'Normal map'; mask as linear (sRGBTexture = false)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
