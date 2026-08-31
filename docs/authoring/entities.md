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
self-test creature's signed-off turntable clip. `--atlas` gives each part
its own UV cell so a `generate hide --atlas` can paint the paws apart from
the body (see "The skin is a sibling albedo"). Grounding ships too: the
writer emits the `Physics` child node (with a feet-aligned `CapsuleCollider`)
the engine reads to settle the creature on the ground (see "What the engine
requires of the model").

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

   **The skin is a sibling albedo.** The writer binds `<stem>_albedo.png`
   to the prefab's material when one sits beside the mesh, and a flat
   colour fill reads as "a green mesh" — the leg-ground boundary vanishes
   against terrain. Give the entity a hide:

   ```bash
   shamway generate hide assets-src/bundle/myCreature_albedo.png --seed 7
   ```

   `shamway generate hide` draws a seeded fur/hide albedo — mottled
   patches, anisotropic fur clumps, hair grain — with no image model:
   same arguments, same bytes. `--base R,G,B` and `--fur R,G,B` set the
   coat colours, `--patch R,G,B` adds a second, darker tone (spots), which
   is what keeps the creature readable against whatever the biome is — a
   single flat hue disappears into the forest or the dirt, and the
   leg-ground boundary with it. `--strength`/`--fur-strength`/
   `--patch-strength`/`--grain` set the contrast, `--size` the resolution
   (256 is plenty for an unlit textured material). The self-test
   creature's skin was first exactly this, seed 7: a cream coat with dark
   spots.

   **A whole-coat hide cannot tell the feet apart.** A generated entity
   merges every part into one mesh where each part's vertices span the
   whole 0-1 UV box, so a single coat covers the entire animal: no colour
   is reserved for the paws, and the paws, the legs and the body read as
   one object — which is why the creature's feet kept disappearing into
   the ground in the look run. The fix is a **per-part UV atlas**, which
   `generate entity --atlas` builds: each part gets its own cell of a
   square UV grid, and a manifest records the cell and a semantic role
   (`body`/`limb`/`paw`/`head`/`tail`) per part. Hand that manifest to
   `generate hide --atlas` and each cell is painted the role colour its
   part demands — paws dark, limbs a shade, body the coat, and the
   gutters an outline colour so every part's silhouette reads against the
   terrain:

   ```bash
   shamway generate entity myCreature.glb --rig quadruped \
       --atlas myCreature.atlas.json
   shamway generate hide assets-src/bundle/myCreature_albedo.png \
       --atlas myCreature.atlas.json --seed 7 \
       --base 205,196,170 --fur 224,214,188 \
       --paw 58,42,32 --limb 150,132,108 --outline 40,34,28 --size 256
   ```

   Each atlas cell is drawn with its own periodic fur field at the cell's
   own pixel size, so a primitive's wrapping default UVs never seam inside
   its cell. `--paw`, `--limb` and `--outline` default to shades of
   `--base`, so a bare `--atlas` invocation is legible without them; pass
   them to set the tone. The manifest is authoring provenance, not a
   bundle member — keep it in `assets-src/` (or wherever an editable
   source lives), never in the bundle source folder. This is what the
   self-test creature now ships: a dark-pawed, light-bodied atlased hide.

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
- **To be grounded, the model needs a `Physics` child node.** The engine
  grounds an entity by its CharacterController capsule, and it reads that
  capsule off a **`Physics` child** of the model root —
  `Entity::PhysicsInit` does `Transform.Find("Physics")`, then
  `AddCharacterController` reads that node's `CapsuleCollider` centre/height
  and calls `SetSize` (verified from `Entity.il.txt`; recorded in
  research-provenance). Without a `Physics` node no CharacterController is
  created and a spawned creature settles wherever the physics body leaves it.
  The writer emits the `Physics` node on every generated entity, sized so the
  capsule's bottom (`center.y - height/2`) is at the mesh's feet, which is
  exactly how the game's own animals (`animalDeerStag`, and the rest) are
  authored.

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

What the fragment leaves out for a bare creature — `MaxHealth`, `sounds`,
`MoveSpeed` tuning, AI behaviour, loot — is mod-specific and belongs in the
mod's own XML, exactly like the properties a prop or item needs. With
`--anim` the fragment now also makes the creature a **real spawnable
animal**: `Class` names a concrete C# entity type, and
`IsAnimalEntity`/`Faction` let the game's spawner and AI treat it as one.

`Class` must be the **mod's own entity type, not a stock animal's** — the
pipeline's whole point is that the mod owns the model, the clips and the C#
class. `EntityClass` resolves `Class` through `Type.GetType(string)`
(`EntityClass.il.txt:349`), which searches all loaded assemblies, so a mod
DLL shipped at the mod root (`shamway client deploy` copies root-level
`*.dll`) can name `Class="<ns>.<Type>, <Assembly>"` and the engine
instantiates the mod's own `EntityAlive` subclass. Reusing `EntityAnimalStag`
would borrow a type that binds a pre-authored model, a stock `PhysicsBody`
with stag bone paths the rig does not have, and a template `AITask` wander
that roams — none of which belongs to the generated asset. The default
`EntityAnimalSnake` is a concrete `EntityAlive` sub-type the generator emits
so a working class is produced out of the box; `--entity-class` names a mod's
own type. No stock `PhysicsBody` is emitted (grounding comes from the
`Physics`-node capsule the writer builds, below), and a slow `MoveSpeed` is
emitted so a spawned creature walks at a visible pace. A bare
`Prefab+Mesh` class is *not* a spawnable `EntityAlive` — without a
`Class` it loads but `EntityFactory.CreateEntity` returns nothing, so it
could never walk in-game. `--minimal-entity` opts back out and emits the
bare stub for a special case.

The generated prefab's animation and grounding are the mod's own too: the
writer attaches a legacy `Animation` component (with the synthesized clips)
to the model root's first active child, and adds an **inactive** `Physics`
child carrying a `CapsuleCollider` whose bottom is at the mesh's feet —
`Entity::AddCharacterController` reads that capsule and grounds the entity
on its feet. See "What the engine requires of the model" and
"Making it move".

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
| `walk` | `Walk` | a trot: each upper leg (`Thigh`/`Upper` bones) swings about its local X, the knee (`Lower`/`Shin` child) bends the other way, and the body dips between steps; diagonal pairs move together (0.35 rad, 1.2 s) |
| `attack` | `Attack1` | a bite: the `Head` jabs forward and returns (0.5 rad at mid-clip, 0.8 s) while the `Chest` pitches a quarter as much — a half-sine, so it never swings past rest (that overshoot is the nervous-bob look). The pitch is on the chest, *not* the pelvis: the legs hang from the pelvis, so a pelvis rotation swings the feet into the ground on every lunge |
| `death` | `Death` | the body rolls over about its own axis and stays down — `loop: false`, so the clip plays once rather than wrapping (1.2 s) |
| `jump` | `Jump` | a hop: the body rises 0.2 m and lands (0.8 s) |

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
     "lower_bones": ["Root/Pelvis/LeftRearLower", "Root/Pelvis/RightRearLower"],
     "body_bone": "Root/Pelvis",
     "amplitude": 0.35, "seconds": 1.2},
    {"name": "Attack1", "kind": "attack",
     "bone": "Root/Pelvis/Spine/Chest/Neck/Head",
     "body_bone": "Root/Pelvis/Spine/Chest",
     "amplitude": 0.5, "seconds": 0.8},
    {"name": "Death", "kind": "death", "bone": "Root/Pelvis",
     "loop": false, "amplitude": 3.14159, "seconds": 1.2},
    {"name": "Jump", "kind": "jump", "bone": "Root/Pelvis",
     "amplitude": 0.2, "seconds": 0.8}
  ],
  "play_automatically": true
}
```

`kind` selects the curve builder (`bob` position, `head` yaw, `attack`
lunge, `death` one-shot roll, `jump` hop, `walk` trot); `bone` is the rig's
own slash-separated path (`Root/Hips` on the humanoid); an `attack` entry
also takes `body_bone` (the body-pitch target); a `death` or `jump` entry
points `bone` at the body; `loop: false` makes a clip play once (a `Death`
should stay down — the serialized `m_WrapMode` is 1 instead of 2); a `walk`
entry takes `bones` (the upper-leg paths, which the generator picks as every
`Thigh`/`Upper` bone), `lower_bones` (each upper leg's child, so the knee
bends), and `body_bone` (the body-dip target). Why this works at all: **legacy
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

The self-test's animated creature carries all six kinds — its
`shamwaySelfTestCreature.anim.json` ships in the fixture — and its turntable
clip (spinning while bobbing, turning its head and trotting with the
knee-bending gait) was signed off on 2026-08-30 (the gait "can still be
improved", signed off as a milestone).
`turntable` is the staged-prefab motion kind; `walk-cycle` is for equipped
items (see [`shamway docs video`](video.md)).

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

- **More clip kinds.** `bob`, `head`, `walk`, `attack`, `death` and `jump`
  are built in; swims are the remaining curve set, not a format change — the
  declaration already accepts any name the controller plays.
- **Mecanim / complex locomotion.** `Animator` + controller + compiled
  clips remain the hard lane; the legacy path covers an animal that idles,
  walks and attacks by name. In this engine revision the shipped animals use a
  Mecanim **`Animator`** (type 95 on the model root, read from
  `automatic_assets_entities/animals.bundle`), while `GameObjectAnimalAnimation`
  (the `AvatarController` the generator wires) drives a **legacy** `Animation`
  by clip name — a legacy-animal path.
- **The synthesized entity shader does not skin (2026-08-31).** A generated
  entity's `SkinnedMeshRenderer` carries the `Shamway/Unlit` material, whose
  vertex stage (`mul(unity_ObjectToWorld, input.vertex)`, `shader_blob.py`)
  applies no bone-matrix skinning, so the creature is invisible in-game even
  though its mesh is valid (verts 1382, meshSize 0.33/1.04/0.83, renderer +
  mesh + root active). The block prop is unaffected (it is a `MeshRenderer`).
  Confirmed live by swapping the creature's material to the player's skinning
  shader `Game/SDCS/Skin` — the creature then drew (before it fell through
  the floor, a separate grounding item). Fix: teach `Shamway/Unlit` to skin
  (per-vertex bone indices/weights + `unity_SkinnedMeshBoneMatrix`) or have
  the entity lane assign a stock skinning shader such as `Game/SDCS/Skin` to
  generated entity materials. See
  [improvements.md §4b](../status/improvements.md) and
  [research-provenance.md](../research/research-provenance.md).
- **Grounding and the controller must be the mod's own.** A generated creature
  spawns as a real `EntityAlive` (its own mod-owned class, not a borrowed stock
  one — `Class` resolves via `Type.GetType`, and the mod DLL at the mod root
  names the type). The engine grounds it by its CharacterController capsule,
  read off an **active `Physics` child node** the writer emits (a
  `CapsuleCollider` whose bottom is at the mesh's feet, radius ≈ the model's
  footprint) — `Entity::AddCharacterController` reads that capsule, then does
  `AddComponent<KinematicCharacterMotor>()` on the node and calls `SetSize`.
  That motor binds its own `Capsule` field in **its** `Awake`, so the `Physics`
  node **must be active**: an inactive node defers the motor's Awake forever
  and `SetCapsuleDimensions` NREs on a null `Capsule` (the measured spawn-time
  NRE before this fix). The stock `GameObjectAnimalAnimation` controller is
  **incompatible** with that active `Physics` node — its `Awake` runs
  `GetChild(reverse-first-active)` (it iterates the model root's children from
  the last down and takes the first active one, so an active `Physics` sibling
  that is the highest-index active child is picked as the figure), then NREs at
  `anim["Idle1"]` because that child carries no `Animation`. So a generated entity
  must use a controller that finds the figure **by name** (the writer's
  `figure` node), not by first-active-child — that is the mod-owned
  `ShamwayAnimalController`, and the stock one cannot be used. This is the
  reason the generator wires a mod-owned `AvatarController` and a mod-owned
  `Class`; a borrowed stock `Class`/controller reintroduces a pre-authored
  model, a stock AI wander, and a stock speed the walk case cannot contain
  (measured: the stock `EntityAnimalSnake` class walked 292 m in a 12 s hold,
  `moveSpeed=0.8` notwithstanding, with a 13 m Y-spread). `physicsbodies.xml`
  remain closed for a procedural skinned mesh — they build bone-centred
  colliders that do not reach the feet. Two environment gates can stop a run
  before the creature is judged, and neither is the asset (recorded in
  research-provenance): (1) a **client/server game-version skew** — the client
  refuses to authorize (`Game Version Mismatch: you have 'V 3.2.0' and server
  has 'V 3.1.0'`) and idles at the menu, so align the dedicated server to the
  client's version (`steamcmd +app_update 294420`); (2) a genuinely missing
  Steam client. The `Steamworks is not initialized` exception near boot is
  **caught and harmless** (the Analytics branch-name probe) — it must not be
  read as "the run never reached the asset". The stock construction path this
  bullet describes — `Entity::AddCharacterController`, the
  `CharacterControllerKinematic`/`KinematicCharacterMotor` wrapper, and the
  `MoveEntityHeaded` motion-lerp constants the walk case measures — is
  documented in `hordeforge/7dtd-engine-research`,
  [entity-movement.md](https://github.com/hordeforge/7dtd-engine-research/blob/main/docs/entity-movement.md).
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
