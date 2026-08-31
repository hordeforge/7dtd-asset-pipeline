#!/usr/bin/env python3
"""Generate a reusable creature from a shipped rig in one shot.

This is the easy on-ramp for the entity lane: a skinned mesh, a per-part UV
atlas, motion clips, a role-aware hide, and (optionally) the
`entityclasses.xml` patch. It calls `generate entity` and `generate hide`
with the same flags a caller would type — there is no second pipeline.

    shamway generate creature myRaptor.glb --rig dinosaur --coat olive
    shamway generate creature myWolf.glb --rig quadruped --scale 0.5 --coat brown \
        --mod MyMod --bundle myMod --xml myWolf-entityclasses.xml

A size or coat morph of a shipped reference is the same command with
`--scale` and `--coat`; `--parts` still replaces the default primitive set.
Atlas, anim (idle+head+walk) and hide are on by default — that is the
construction bar the self-test quadruped already meets. `--no-anim` /
`--no-hide` drop those halves; `--atlas` / `--hide` redirect the sibling
files (defaults: `{stem}.atlas.json` and `{stem}_albedo.png` beside the GLB).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import entity as entity_gen
from . import hide as hide_gen
from .hide import COATS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "EXAMPLES\n"
            "  shamway generate creature myRaptor.glb --rig dinosaur --coat olive\n"
            "  shamway generate creature myWolf.glb --rig quadruped --scale 0.5"
            " --coat brown --mod MyMod --bundle myMod --xml myWolf-entityclasses.xml\n"
        ),
    )
    parser.add_argument("output", type=Path, help="destination skinned entity .glb")
    parser.add_argument("--rig", default="humanoid", help="rig template name or a .json rig spec")
    parser.add_argument(
        "--parts", default=None, help="path to a parts JSON (default: the rig's own set)"
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=None,
        help="uniform size factor on top of the rig's own scale",
    )
    parser.add_argument(
        "--name", default=None, help="entity and prefab name (default: output stem)"
    )
    parser.add_argument("--mod", default=None, help="mod folder name, for the XML URI")
    parser.add_argument("--bundle", default=None, help="bundle file stem, for the XML URI")
    parser.add_argument(
        "--xml", default=None, help="write the entityclasses.xml patch to this path"
    )
    parser.add_argument("--entity-name", default=None, help="entity_class name (default: stem)")
    parser.add_argument(
        "--entity-class",
        default="EntityAnimalStag",
        help="the C# entity type emitted as Class for an animated creature",
    )
    parser.add_argument(
        "--minimal-entity",
        action="store_true",
        help="emit a bare Prefab+Mesh class even for an animated creature",
    )
    parser.add_argument(
        "--anim",
        nargs="?",
        const="idle,head,walk",
        default="idle,head,walk",
        metavar="KINDS",
        help="legacy clip kinds (default: idle,head,walk). Same list as generate entity",
    )
    parser.add_argument("--no-anim", action="store_true", help="do not write a {stem}.anim.json")
    parser.add_argument(
        "--atlas",
        default=None,
        metavar="JSON",
        help="per-part UV atlas path (default: {stem}.atlas.json beside the GLB)",
    )
    parser.add_argument(
        "--hide",
        default=None,
        metavar="PNG",
        help="albedo path (default: {stem}_albedo.png beside the GLB)",
    )
    parser.add_argument("--no-hide", action="store_true", help="do not paint a hide")
    parser.add_argument(
        "--coat",
        default=None,
        metavar="NAME",
        help="named hide palette: " + ", ".join(sorted(COATS)),
    )
    parser.add_argument("--seed", type=int, default=7, help="hide pattern seed (default 7)")
    parser.add_argument("--size", type=int, default=256, help="hide resolution (default 256)")
    parser.add_argument("--base", default=None, help="hide base colour R,G,B (overrides --coat)")
    parser.add_argument("--fur", default=None, help="hide fur colour R,G,B")
    parser.add_argument("--paw", default=None, help="hide paw colour R,G,B")
    parser.add_argument("--limb", default=None, help="hide limb colour R,G,B")
    parser.add_argument("--outline", default=None, help="hide gutter colour R,G,B")
    args = parser.parse_args(argv)

    if args.output.suffix.lower() != ".glb":
        raise SystemExit("ERROR: the creature must be written as .glb")

    atlas = Path(args.atlas) if args.atlas else args.output.with_suffix(".atlas.json")
    entity_argv: list[str] = [str(args.output), "--rig", args.rig, "--atlas", str(atlas)]
    if args.parts:
        entity_argv += ["--parts", args.parts]
    if args.scale is not None:
        entity_argv += ["--scale", str(args.scale)]
    if args.name:
        entity_argv += ["--name", args.name]
    if args.mod:
        entity_argv += ["--mod", args.mod]
    if args.bundle:
        entity_argv += ["--bundle", args.bundle]
    if args.xml:
        entity_argv += ["--xml", args.xml]
    if args.entity_name:
        entity_argv += ["--entity-name", args.entity_name]
    if args.entity_class:
        entity_argv += ["--entity-class", args.entity_class]
    if args.minimal_entity:
        entity_argv.append("--minimal-entity")
    if not args.no_anim:
        entity_argv += ["--anim", args.anim]

    code = int(entity_gen.main(entity_argv) or 0)
    if code:
        return code

    if args.no_hide:
        return 0
    hide_path = (
        Path(args.hide) if args.hide else args.output.with_name(args.output.stem + "_albedo.png")
    )
    hide_argv: list[str] = [
        str(hide_path),
        "--atlas",
        str(atlas),
        "--seed",
        str(args.seed),
        "--size",
        str(args.size),
    ]
    if args.coat:
        hide_argv += ["--coat", args.coat]
    if args.base:
        hide_argv += ["--base", args.base]
    if args.fur:
        hide_argv += ["--fur", args.fur]
    if args.paw:
        hide_argv += ["--paw", args.paw]
    if args.limb:
        hide_argv += ["--limb", args.limb]
    if args.outline:
        hide_argv += ["--outline", args.outline]
    return int(hide_gen.main(hide_argv) or 0)


if __name__ == "__main__":
    sys.exit(main())
