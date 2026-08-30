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
proven by read-back through UnityPy in `tests/test_entity_gen.py` — and
every shipped rig has been staged in a live client (see "End-to-end
confirmation"). Movement ships too: `--anim` wires a legacy `Animation`
component with synthesized clips and `AvatarController =
GameObjectAnimalAnimation` (see "Making it move"), proven live by the
self-test creature's signed-off turntable clip.

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

The shipped rigs, all usable as `--rig NAME` with their own default part
sets (forward is +Z; the humanoid is symmetric):

| Rig | What it is | Bones |
|---|---|---|
| `humanoid` | ~1.6 m standing biped T-pose | 20 |
| `quadruped` | ~0.8 m shoulder four-legged animal (deer/wolf-ish) | 19 |
| `quadruped-small` | `quadruped` at 0.45× — rabbit-sized | 19 |
| `quadruped-large` | `quadruped` at 1.5× — bear-sized | 19 |
| `bird` | flying creature: wings, tail, perched legs | 19 |
| `dinosaur` | bipedal theropod: heavy tail, big legs, tiny arms | 19 |
| `arachnid` | eight-legged crawler: prosoma, abdomen, pedipalps | 29 |
| `crocodile` | long low reptile: multi-segment body and tail, short legs | 22 |

A rig spec can carry `"scale": <factor>` and `"base": <other-rig>` — the
three quadruped sizes are exactly that, one line each. The `--scale` flag on
either generator multiplies a rig's own size on top, bones and parts
together, so a giant or a micro creature is one argument away. A rig without
its own default part set refuses `generate entity` until `--parts` names one,
because a creature with no geometry on its bones is not what anyone asked for.

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
- **Without `UserSpawnType` the class cannot be spawned from the console.**
  The `spawnentity` command lists only classes whose `userSpawnType` is not
  `None` (verified from `ConsoleCmdSpawnEntity.il.txt`; the enum is
  `None`/`Console`/`Menu`). The generator emits `UserSpawnType="Menu"` so
  the creature is listable; `Console` is the alternative for a class that
  should only come from code or a spawn file.

So the minimal wiring for a generated entity is exactly what
`shamway generate entity --xml` writes:

```xml
<append xpath="/entity_classes">
    <entity_class name="myCreature">
        <property name="Prefab" value="#@modfolder(MyMod):Resources/myMod.unity3d?myCreature"/>
        <property name="Mesh" value="#@modfolder(MyMod):Resources/myMod.unity3d?myCreature"/>
        <property name="UserSpawnType" value="Menu"/>
    </entity_class>
</append>
```

What the fragment deliberately leaves out — `PhysicsBody`, `MaxHealth`,
`sounds`, `MoveSpeed`, AI, loot — is mod-specific and belongs in the mod's
own XML, exactly like the properties a prop or item needs. A class with only
the three properties loads, lists in the console spawn menu, and stands
still.

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
- **Animation clips are keyed to the rig they were authored against.** A
  synthesized clip targets your rig's own bone paths, so the names in the
  rig spec are the names the clip animates. TFP's clips still cannot ship in
  a mod bundle — the game's bundles embed their assets same-file — so
  matching TFP's rig names buys nothing.

One *not checked*: `Mesh.m_BoneNameHashes` (the crc32 the writer stores for
each joint name) does not equal the hash the game's own rig meshes carry
(1722913273 for `Hips` — no standard crc32/×31 hash reproduces it, so Unity
uses a different digest). Nothing in the engine's binding path has been shown
to read these hashes — SDCS binds by name — so the discrepancy is recorded,
not acted on.

## Making it move

A generated entity stands still unless its prefab carries animation. How the
engine moves an animal, verified from the dedicated-server IL
(`GameObjectAnimalAnimation.il.txt`, recorded in research-provenance.md):

- the entity class sets **`AvatarController = GameObjectAnimalAnimation`**
  (the animal classes in the game's own `entityclasses.xml` do exactly
  this);
- the controller grabs the model's **legacy `Animation` component** and
  plays clips **by name** — `Idle1`, `Idle2`, `Attack1/2`, `Pain`, `Jump`,
  `Death`, `Run`, `Walk`, `Swim` — switching on motion state.

So an animated animal is the skinned prefab plus a legacy `Animation`
component carrying looping clips under those names, and
`AvatarController = GameObjectAnimalAnimation` on the class. Both halves
are synthesized:

```bash
shamway generate entity myCreature.glb --rig quadruped --anim idle,head,walk \
    --mod MyMod --bundle myMod --xml myCreature-entityclasses.xml
```

`--anim [KINDS]` (comma list, default `idle`) does three things:

1. writes a **`{stem}.anim.json`** beside the GLB — one looping legacy clip
   per name — and the writer's skinned lane picks up that sibling file and
   attaches the legacy `Animation` component (class 111) with the declared
   clips (class 74, `m_Legacy = true`, `m_MuscleClipSize = 0`) to the
   prefab root;
2. adds **`AvatarController = GameObjectAnimalAnimation`** to the
   `entityclasses.xml` patch;
3. so the entity **moves in game**: the controller plays the clips by name
   as its state changes.

The kinds select the curve builders (all rig-aware — the bone paths come
from the rig's own names):

| Kind | Clip | What moves |
|---|---|---|
| `idle` | `Idle1` | a 0.03 m bob of the body's first bone (Hips/Pelvis/Prosoma) |
| `head` | merged into `Idle1` | a slow side-to-side yaw of the `Head` bone (≈20°, 4 s) |
| `walk` | `Walk` | a trot: each upper leg (`Thigh`/`Upper` bones) swings about its local X, left and right legs out of phase (0.5 rad, 1.2 s) |

The declaration is a small JSON you can extend — the clip names are the
ones the controller plays, and entries sharing a name merge into one clip,
so an `Idle1` can combine a bob and a head turn:

```json
{
  "clips": [
    {"name": "Idle1", "kind": "bob", "bone": "Root/Pelvis",
     "amplitude": 0.03, "seconds": 1.5},
    {"name": "Idle1", "kind": "head", "bone": "Root/Pelvis/Spine/Chest/Neck/Head",
     "amplitude": 0.35, "seconds": 4.0},
    {"name": "Walk", "kind": "walk",
     "bones": ["Root/Pelvis/LeftRearUpper", "Root/Pelvis/RightRearUpper"],
     "amplitude": 0.5, "seconds": 1.2}
  ],
  "play_automatically": true
}
```

`kind` selects the curve builder (`bob` position, `head` yaw, `walk` trot);
`bone` is the rig's own slash-separated path (`Root/Hips` on the humanoid),
`bones` the upper-leg paths for `walk`. Why this works at all: **legacy
clips carry their curves directly** (`m_MuscleClipSize = 0`, measured from
the game's `animals.bundle` `_Take 001`) — no compiled `m_Clip` stream,
unlike Mecanim clips. `anim.py` builds the type-tree dicts and
`tests/test_anim.py` round-trips them through `build_bundle` and back
through UnityPy.

To prove motion in a live client, give the entity's look suite a motion
kind in the mod's `.shamway.toml`, so the look run captures a frame
sequence instead of one still:

```toml
[acceptance]
motion_kinds = { shamwaySelfTestCreature = "turntable" }
```

The self-test's animated creature does exactly this (with `--anim
idle,head,walk`), and its turntable clip — spinning while bobbing, turning
its head and trotting — was signed off on 2026-08-30. `turntable` is the
staged-prefab motion kind; `walk-cycle` is for equipped items (see
[`shamway docs video`](video.md)).

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

- **More clip kinds.** `bob`, `head` and `walk` are built in; attack
  chains, death poses, jumps and swims are more curve sets, not a format
  change — the declaration already accepts any name the controller plays.
- **Mecanim / complex locomotion.** `Animator` + controller + compiled
  clips remain the hard lane; the legacy path covers an animal that idles,
  walks and attacks by name.
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
`entityclasses.xml` is asserted for the mandatory `Prefab`, the `Mesh`, the
`UserSpawnType`, and the bundle URI.

The live half runs through `playtest-synthesized`, and each prefab has its
**own per-prefab look suite** (`<mod>_<stem>_look`), because a suite that
staged every prefab at the same camera offset stacks unrelated pictures:

- the default run asserts the game **reads** the bundle: every entity
  prefab comes back with its `SkinnedMeshRenderer`, its weighted mesh with
  its vertex stream, and its albedo texture at its authored size
  (`examples/SelfTestMod` carries generated creatures from the quadruped,
  bird, arachnid and dinosaur rigs for exactly this);
- `playtest-synthesized --look STEM` runs that one prefab's look suite
  (`<mod>_<stem>_look`) alone — the prefab instantiated in front of the
  camera with a renderer, one picture, a frame to judge. Without `STEM` it
  runs the looping VFX prefab's suite:

  ```bash
  shamway script playtest-synthesized --look shamwaySelfTestBird
  ```

**A load is not a look, and a staged prefab is not a sign-off.** A look
suite proves the prefab renders *something*; that it reads as its rig is a
person's judgement. File it, with the frame and the observable it was
checked against, through `shamway client capture <stem> --observable
"reads as its rig: proportions, facing, not mirrored"` — and the lane is
not complete until that capture exists.

**Ran live on 2026-08-30** (client + dedicated server on the development
host): the default run reported `SUMMARY pass=25 fail=0` — the engine
loaded every bundle member through `DataLoader.LoadAsset<T>`, all four
generated entities' prefabs, meshes and textures included. Each rig's look
suite staged its prefab with a renderer (`pass=1 fail=0` per run), and all
four frames were **signed off** (creature: four legs, head forward, not
mirrored, textured; bird, arachnid and dinosaur read as their rigs). The
animated creature's turntable clip — 48 frames, muxed to
`/home/yannick/motion_creature.mp4` — was **signed off for motion the same
day**: it spins on the turntable and bobs on the `Idle1` legacy clip, so
the movement lane is confirmed in a live client.
