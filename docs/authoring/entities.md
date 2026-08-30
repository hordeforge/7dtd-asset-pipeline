# Custom entities: the rig, the skin, and the XML that spawns them

A custom in-game entity is the one 3D asset class that is never one object.
A block is a static mesh; an item is a mesh and a prefab. An entity is a
**skeleton with a skinned mesh on top** — bones, bind poses, weights, a
renderer, and the `entityclasses.xml` wiring that tells the engine what to
spawn and which prefab to show. This page is the entity lane: where the
skeleton comes from, how the parts go on top of it, and what the engine
actually requires of the result. Everything here is either verified from the
installed build's IL (recorded in
[research-provenance.md](../research/research-provenance.md)) or marked
*not checked*.

**Status: the authoring half ships with `shamway generate rig` and
`shamway generate entity`; the writer half is the skinned lane of
[skinned-gear.md](skinned-gear.md).** A generated entity produces a bundle
with a `SkinnedMeshRenderer` whose bones are named, bound, and weighted —
proven by read-back through UnityPy in `tests/test_entity_gen.py`. What no
offline gate can prove is in "What is still unbuilt" below.

## The two ways in

1. **Model it yourself, against a template.** `shamway generate rig` writes
   an armature — the bone hierarchy plus inverse bind matrices — as a GLB.
   Import it into Blender, skin your mesh to it (the joint names travel with
   the file), export the scene, and `shamway build` writes the skinned
   prefab. The rig is the "base one that is then modified":

   ```bash
   shamway generate rig armature.glb
   shamway generate rig armature.glb --rig myRig.json
   ```

2. **Generate it fully.** `shamway generate entity` skins procedural
   primitives to a rig — no Blender anywhere — and writes the
   `entityclasses.xml` patch beside the mesh:

   ```bash
   shamway generate entity myCreature.glb --rig humanoid \
       --mod MyMod --bundle myMod --xml myCreature-entityclasses.xml
   ```

   The default `--rig humanoid` is the shipped template: a ~1.6 m standing
   humanoid T-pose, 20 bones, a primitive per joint (cylinders for limbs and
   torso, sphere for the head, boxes for hands and feet). `--parts
   parts.json` replaces the default part set — each part is a primitive
   rigidly bound to one bone, and the generated GLB is a normal skinned mesh
   a mod can re-skin or replace later.

Both outputs are inputs to the same lane: a GLB with a skin. The writer
reads it straight off the file — see
[skinned-gear.md](skinned-gear.md#why-this-is-not-the-mesh-lane) for what it
synthesizes and what still wants an editor.

## What the engine requires of the model

Verified from `il/full-v3.1.0/_global/EntityClass.il.txt` and
`EModelBase.il.txt` (7dtd-engine-research, decompiled with `monodis`):

- **Every entity class needs a `Prefab` property.** Missing or empty, the
  class fails to load: `Mandatory property 'prefab' missing in entity_class
  …`. The `Mesh` property is the model the player sees, loaded the same way.
  Both are handed to `LoadManager.LoadAsset<GameObject>`.
- **A bundle URI works in both.** `#@modfolder(Mod):Resources/x.unity3d?stem`
  resolves through the same `DataLoader` chain a `Meshfile` uses (recorded
  in [skinned-gear.md](skinned-gear.md#the-xml-side)). The `Entities/`
  prefix the engine prepends to a *resources* path does not apply to a mod
  URI.
- **The engine walks the loaded hierarchy.** `EModelBase` collects every
  `Renderer`/`SkinnedMeshRenderer` under the model, looks for an `Animator`
  (through `AvatarController`) or a legacy `Animation` component, and finds
  biped/head/neck transforms by name. The animator and animation lookups are
  **null-guarded**: a model with neither loads and renders, standing in its
  authored pose. It simply does not move.

So the minimal wiring for a generated entity is exactly what
`shamway generate entity --xml` writes:

```xml
<append xpath="/entity_classes">
    <entity_class name="myCreature">
        <property name="Prefab" value="#@modfolder(MyMod):Resources/myMod.unity3d?myCreature"/>
        <property name="Mesh" value="#@modfolder(MyMod):Resources/myMod.unity3d?myCreature"/>
    </entity_class>
</append>
```

What the fragment deliberately leaves out — `PhysicsBody`, `MaxHealth`,
`sounds`, `MoveSpeed`, AI, loot — is mod-specific and belongs in the mod's
own XML, exactly like the properties a prop or item needs. A class with only
the two model properties loads and spawns (the debug spawn menu lists
entity classes), and stands still.

## Bone names are the mod's choice — with two exceptions

Nothing in the engine renames or rebinds the bones of a *self-contained*
entity model; the skeleton binds inside the prefab. So the template's
spellings (`Root`, `Hips`, `Spine`, …) are a starting point, not a law, and
the rig format takes any names.

Two cases where names stop being free, both recorded in
[research-provenance.md](../research/research-provenance.md):

- **SDCS gear** rebinds a garment to the *wearer* by name through a
  string-keyed catalog — a name that does not match becomes a null bone with
  no error. An entity that should wear armor must use the player rig's exact
  bone spellings, which are **not readable offline**: read them off a live
  client with `Helpers.RigBoneNames` (7dtd-playtest) and rename the rig.
- **Animation clips** are keyed to the rig they were authored against, and
  TFP's clips cannot ship in a mod bundle anyway — the game's bundles embed
  their assets same-file. Matching TFP's rig names buys nothing until clips
  are authorable at all.

One *not checked*: `Mesh.m_BoneNameHashes` (the crc32 the writer stores for
each joint name) does not equal the hash the game's own rig meshes carry
(1722913273 for `Hips` — no standard crc32/×31 hash reproduces it, so Unity
uses a different digest). Nothing in the engine's binding path has been shown
to read these hashes — SDCS binds by name — so the discrepancy is recorded,
not acted on.

## The dedicated-server caveat

A **custom entity class on a dedicated server gets a negative id and renders
nothing on clients** in the current build: appended human classes are
assigned negative ids, and `EntityClass.AddClass` is absent from the dedi
build (verified: not present in the dedi IL dump; recorded in
`7dtd-fps-bots/config/entityclasses.xml`, whose bots use `zombieSoldier`
bodies for exactly this reason). Test a custom entity class on a
client-hosted game; on a dedi, patch an existing positive-id class or accept
that clients see nothing.

## What is still unbuilt

- **Animation clips / an Animator.** A generated entity stands in its
  authored pose. Clips and controllers are the editor-owned lane
  (`bundle_source = "unity"`), and an entity that must walk, attack, or die
  needs them. The rig format and the skinned mesh are exactly the input that
  lane consumes, so this is the next piece, not a redesign.
- **Physics bodies and collision.** The generated class has none; the mod
  adds `PhysicsBody` and colliders per its own design.
- **SDCS extras** (`GearBoneMap`, `Morphable`) — the editor bakes those; see
  [skinned-gear.md](skinned-gear.md).

## End-to-end confirmation

The unit suite proves the construction half end to end with no editor and no
game: `shamway generate entity` writes a GLB; the writer's own skinned lane
(`mesh_source_objects` → `build_bundle`) turns it into a bundle; and the
result is read back with UnityPy, which parses Unity's format with none of
this repository's code — asserting a `SkinnedMeshRenderer` (never a
`MeshRenderer` fallback), 20 named bone transforms, and a mesh whose
`m_BoneNameHashes` match the authored joint names. The generated
`entityclasses.xml` is asserted for the mandatory `Prefab`, the `Mesh`, and
the bundle URI.

The live half is the same as every lane: a fresh client, a spawn, and a look.
**A load is not a look** — the suite proves the game can read the prefab; it
does not prove the creature reads as a creature. The first live acceptance
of a generated entity, with the frames and the client log, is owed exactly
like the first prop's was.
