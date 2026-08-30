#!/usr/bin/env python3
"""Emit a bone-structure template as a glTF armature.

The armature is the authoring half of the skinned-mesh lane: a skeleton a
modeller skins a mesh onto in Blender, with the joint hierarchy and inverse
bind matrices already in place. Import `armature.glb` into Blender, skin your
mesh to it (the joint names travel with the file), export the whole scene as
a GLB, and `shamway build` writes the skinned prefab — the writer reads the
skin straight off that GLB. A rig is also what `shamway generate entity`
skins primitives to procedurally, with no Blender at all.

    shamway generate rig armature.glb
    shamway generate rig armature.glb --rig myRig.json
    shamway generate rig armature.glb --rig humanoid --name MyEntityRig

The default `--rig humanoid` is the shipped template: a ~1.75 m standing
humanoid T-pose, 20 bones, named conventionally (Root, Hips, Spine, Chest,
Neck, Head, shoulders/arms/hands, thighs/shins/feet). It is a starting
point, not a law: the bone names in a rig are the mod's choice, because they
bind inside the prefab and nothing in the engine renames them.

Two cases where the names stop being free, both documented in
`shamway docs entities` and `docs/research/research-provenance.md`:

- **SDCS gear** binds a garment to the wearer's skeleton *by name*, so an
  entity that should wear armor must use the player rig's exact bone
  spellings. Those are not readable offline; read them off a live client
  with `Helpers.RigBoneNames` (7dtd-playtest) and rename this rig.
- **TFP animation clips** are keyed to TFP's rigs and cannot ship in a mod
  bundle anyway, so matching TFP names buys nothing until clips are
  authorable at all. A rig without clips yields an entity that stands in its
  authored pose; animation is the editor-owned lane.

The output is a *template*, not a bundle asset: an armature has no mesh, so
it is not something `shamway build` packs. The bundle input is the skinned
mesh you export after skinning, or the output of `shamway generate entity`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..atomic import write
from ..errors import PipelineError
from ..rigs import Rig, load_rig, rig_to_glb


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path, help="destination armature .glb")
    parser.add_argument(
        "--rig",
        default="humanoid",
        help="rig template name (humanoid) or a path to a .json rig spec",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="skin name written into the armature (default: the rig spec's name)",
    )
    args = parser.parse_args(argv)

    if args.output.suffix.lower() != ".glb":
        raise SystemExit("ERROR: the armature must be written as .glb")
    try:
        rig: Rig = load_rig(args.rig)
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.name:
        rig = Rig(name=args.name, bones=rig.bones)

    write(args.output, rig_to_glb(rig))
    print(f"wrote {args.output} ({len(rig.bones)} bones, rig {rig.name!r})")
    print(f"root: {rig.root().name}")
    for bone in rig.bones:
        parent = bone.parent or "-"
        x, y, z = bone.pos
        print(f"  {bone.name:<16} parent={parent:<16} pos=({x:.3f}, {y:.3f}, {z:.3f})")
    return 0
