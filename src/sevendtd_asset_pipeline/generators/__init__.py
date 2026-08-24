"""Asset generators, callable from any mod without a checkout of this repo.

These live inside the installed package rather than as loose scripts on
purpose. A mod that uses this pipeline should never need a relative path into
it — the mod owns its art, its prompts, and its seeds; this repository owns the
generalized tooling, and the mod *calls* it:

    shamway generate sound blast assets-src/audio/blast.wav --seed 7
    shamway generate cutout key src.png UIAtlases/ItemIconAtlas/x.png --size 160

Each generator is an ordinary argparse program with a `main(argv)`, so it also
runs directly (`python -m sevendtd_asset_pipeline.generators.sound --help`) and
can be imported by a mod's own script that needs one piece.

A mod that outgrows a generator should write its own in `assets-src/`, using
these as the reference for the contract — explicit paths, a recorded seed,
printed numbers, atomic writes. That is a mod-specific asset script, and it
belongs in the mod's repository, not here.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import TypedDict

from ..errors import PipelineError


class GeneratorInfo(TypedDict):
    """One row of the generator table, as `--list` and the schema publish it."""

    name: str
    summary: str
    capabilities: list[str]


# name -> (module, one-line summary, optional capabilities it needs)
GENERATORS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "sound": (
        "sound",
        "create clips: designed voices (blast, nuclear-blast, tick, whoosh, bomb-whistle, hum, beep) and sounds.xml",
        (),
    ),
    "audio": (
        "audio",
        "measure and convert clips: report, downmix, resample, normalize",
        (),
    ),
    "cutout": (
        "cutout",
        "cut a generated image out of its flat key background, or a grayscale mask into a card",
        ("pillow",),
    ),
    "particle-card": (
        "particle_card",
        "draw a rain/ash streak or a broad haze puff procedurally, no model needed",
        ("pillow",),
    ),
    "icon": (
        "icon",
        "derive an atlas cell from an already-transparent source, with a contact sheet",
        ("pillow",),
    ),
    "texture-maps": (
        "texture_maps",
        "derive a normal map and a packed mask from an albedo",
        ("pillow", "numpy"),
    ),
    "mesh": (
        "mesh",
        "author a parameterized mesh through headless Blender and export GLB",
        ("blender",),
    ),
    "mesh-optimize": (
        "mesh_optimize",
        "simplify and reorder a mesh with gltfpack, gated on how far the shape moved",
        ("gltfpack", "trimesh"),
    ),
    "mesh-icon": (
        "mesh_icon",
        "photograph a mesh file into an atlas cell through headless Blender, with no editor",
        ("blender", "pillow"),
    ),
}


def load(name: str) -> ModuleType:
    """Import one generator module by its public name."""
    try:
        module_name = GENERATORS[name][0]
    except KeyError:
        known = ", ".join(sorted(GENERATORS))
        raise PipelineError(f"unknown generator {name!r}; expected one of: {known}") from None
    return importlib.import_module(f"{__name__}.{module_name}")


def run(name: str, argv: list[str]) -> int:
    """Run a generator with the arguments a caller would have typed.

    `sys.argv[0]` is swapped while the generator builds its parser, because
    argparse derives the program name from it — otherwise `--help` advertises
    the module path rather than the command the user actually typed.
    """
    import sys

    module = load(name)
    original = sys.argv[0]
    sys.argv[0] = f"shamway generate {name}"
    try:
        return int(module.main(argv) or 0)
    finally:
        sys.argv[0] = original


def describe() -> list[GeneratorInfo]:
    """The generator table, for `--list` and for the machine-readable schema."""
    return [
        {"name": name, "summary": summary, "capabilities": list(capabilities)}
        for name, (_module, summary, capabilities) in sorted(GENERATORS.items())
    ]
