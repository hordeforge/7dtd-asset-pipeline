# Skinned character gear (SDCS armor)

Worn armor is the one asset class in 7 Days to Die that a mod cannot reach
through the static prop lane. A held item, a placed block and a VFX card
are a mesh, a material, a prefab. A garment has to deform with the wearer,
and the engine binds it to the player's skeleton at the moment it is
equipped. The editorless writer now emits that deformation graph from a
glTF skin; SDCS extras (`GearBoneMap`, `Morphable`) still want an editor,
so they stay on this page.

**Status: walked end to end on 2026-08-24.** A mod-authored garment now loads
from a mod's own bundle, grafts onto the player rig, deforms with the body and
follows it through a full turn. The two faults that took the longest to find
are in "What bites" below; neither is in the engine research, because neither
is visible from IL. The engine behaviour below is reversed
from IL in
[`hordeforge/7dtd-engine-research`](https://github.com/hordeforge/7dtd-engine-research),
`docs/sdcs-character-gear.md`, which is the authority and carries the IL
evidence index. What is written here is what that means for authoring. Where
this page marks something *inferred*, nobody has run it.

## Why this is not the mesh lane

`shamway build` writes bundles without Unity. A glTF/GLB that actually
contains a skin (joints, inverse bind matrices, `JOINTS_0`, `WEIGHTS_0`)
is synthesized as `SkinnedMeshRenderer` plus the named bone hierarchy —
bind poses, bone weights, bone-name hashes, root bone, no MeshRenderer
fallback. That is the editorless deformation graph.

Two SDCS extras still want an editor:

- Unity components (`GearBoneMap`, optionally `Morphable`, rig constraints)
  that only the editor bakes.
- Animation clips / Animator.

A garment that needs those extras is on `bundle_source = "unity"`. A
deformation-ready skinned prefab that does not is synthesized.

## The one prerequisite: bone names

The engine rebinds a gear prefab's `SkinnedMeshRenderer.bones` to the wearer
**by name**, through a string-keyed catalog. A name that does not match becomes
a null bone, and **no error is raised** — the garment simply does not follow
that joint.

So the base rig's exact bone spellings are a hard input, and they live in the
game's own asset bundles: not in XML, not in IL, not readable offline. Read
them off a real wearer in a running client:

```csharp
// hordeforge/7dtd-playtest
var bones = Helpers.RigBoneNames(player);   // distinct, sorted
```

Record the list in the mod's own docs beside the garment source, with the game
build it came from. It is a versioned fact about an asset, not a constant.

## What the prefab must contain

From the engine research, in the order they are checked:

1. **One root, one child per part**, named exactly `head`, `body`, `hands` or
   `feet` — or `<part>_<variant>` when the piece takes part in the gear variant
   matrix. Matching is on direct children only, case-insensitive, exact.
2. **A baked `GearBoneMap` on the root.** Without it the engine logs a warning
   and falls back to collecting every bone of every renderer under the slot,
   which works and grafts far more bones than the piece needs.
3. **Materials.** Anything skin-adjacent wants a `_Tint` colour property so it
   inherits the wearer's skin tone, and its name decides which base material is
   consulted: `_Body`, `_Head`, `_Hand`.
4. **First-person body gear** needs a non-zero vertex-colour **red channel** on
   the triangles that should survive in first person, and a `_ClipFPV` float on
   the material. Skip this and the garment vanishes from the player's own view,
   or clips through it.
5. **Headgear that needs per-skull fitting** carries a `Morphable` and ships a
   morph asset per race and variant. Skipping it is a legitimate choice; the
   piece then fits one head shape well and the others approximately.

## The XML side

```xml
<property class="SDCS">
    <property name="Prefab" value="@:Entities/Player/{sex}/Gear/.../piece_{sex}.prefab"/>
    <property name="TransformName" value="body"/>
    <property name="Excludes" value="body"/>
</property>
```

`{race}`, `{variant}` and `{hair}` substitute **only on the `head` part**;
everything else gets `{sex}` and nothing more.

**A mod bundle can serve the prefab.** Verified from IL against the installed
build rather than inferred: the slot path is handed to
`LoadManager.LoadAsset<GameObject>`, which parses it with
`DataLoader.ParseDataPathIdentifier`, and that method

1. runs `ModManager.PatchModPathString(uri)` first, which resolves
   `#@modfolder(<Mod>):` to a real path and returns non-null precisely when the
   URI *was* a mod path;
2. then treats any URI beginning `#` and containing `?` as a bundle reference,
   splitting bundle path from asset name and setting `FromMod` from whether
   step 1 patched anything;
3. and `LoadManager.LoadAsset` passes that `FromMod` flag straight to
   `AssetBundleManager.LoadAssetBundle`.

So `#@modfolder(<Mod>):Resources/<bundle>.unity3d?<prefab>.prefab` reaches a
mod's own bundle here exactly as it does for a `Meshfile`. Marker substitution
runs before the load and leaves a URI containing no `{sex}` alone.

A garment has now shipped through this path, so the loading and the
deformation are both settled.

## What bites

Both of these produce a garment that *looks* buried inside the body: a thin
strip down each flank and nothing else. That reading is a trap. It invites
widening and deepening the mesh, which changes nothing, because the dimensions
were never the problem.

**The prefab needs an `Origin` above its bone chain.** `SDCSUtils.MatchRigs`
resolves `Origin` on both the source and the target before walking the
hierarchy, and the wearer's own `Hips` hangs off one. A prefab whose chain
starts at `Hips` under the prefab root gives that walk nothing to match. The
failure is quiet and convincing: the garment loads, the renderer reports the
right number of correctly named **non-null** bones and a sensible bounds, and
the piece then stands still in world space while the wearer moves underneath
it. Nothing logs.

*You will only catch this by turning the subject.* From a fixed camera a
garment that ignores the wearer's rotation is indistinguishable from one that
fits badly. `CaseDef.Staged`'s `onHold` callback in `7dtd-playtest` exists for
this.

**Winding.** A generated tube whose triangles face inward is culled entirely,
and all you see is the far side's interior showing through at the silhouette —
two thin vertical strips, exactly the same symptom. Check the winding before
touching a single dimension.

## Diagnosing one that does not appear

In order, because each step rules out everything before it:

1. **Does the engine load it?** Without a `GearBoneMap` it logs
   `No GearBoneMap found on root <name>, falling back to collecting all bones
   from SMRs under <part>`. That line naming your prefab and your part is proof
   of load, layout and graft in one.
2. **Is the geometry what you think?** `Helpers.GraftedMeshes(player, prefix)`
   (7dtd-playtest) gives the mod-authored meshes on the wearer as
   `name=vertexCount`. **Compare those counts against the generator's own build
   log**, which should print them when it writes each mesh. Equal counts prove
   the client is running the build you just made; anything else is a stale
   bundle, and the usual causes are a build-time cache skipping regeneration or
   a staged copy that was never refreshed.

   Make this an *assertion* in a case, not something you check by eye. Every
   other thing a suite can assert about worn armor is satisfied without the
   garment — the item equips whether or not its prefab loaded, and the wearer
   has a rig whether or not anything grafted — so without this a suite goes
   green, produces frames, and says nothing about whether your meshes were in
   them. One project spent an afternoon judging geometry from pictures that had
   never been shown to contain it.
3. **Did the bones rebind?** `Helpers.GraftReport(player, prefix)` gives bone
   count, null count, names, `rootBone` and `localBounds` per renderer. Nulls
   mean a name mismatch; correct names with a piece that does not move means the
   `Origin` fault; collapsed bounds is neither.
4. **Only then**, dimensions — and see "Fitting it to the body" below, because
   most of what looks like a dimension problem is a clearance problem.

**Keep the client log with the run.** It is the only place steps 1 and 3 are
recorded, and the client truncates it on its next launch — so a run stops being
explainable the moment anybody starts the game again, including the person
opening the frames to look at it. `capture_frames.sh` copies it next to the
frames.

## Fitting it to the body

Everything above gets a garment onto the wearer. This is about making it look
like clothing once it is there, and it is where the time actually goes: one
suit took roughly fifteen client runs, of which two were mechanism faults and
the rest were fit.

### The bind pose says where the joints are, not where the body is

This is the whole difficulty, and it is not obvious because the bind pose is
*exact*. It gives joint positions to six decimal places, and a garment built
faithfully to them sits **inside** the mesh wrapped around those joints. Skin
comes through at the shoulders, the chest, the crotch, the face.

The fix is a clearance: how far the fabric stands off the figure the bind pose
describes. Two constants, not a dozen radii:

```csharp
private const float BodyClearance = 0.032f;   // torso
private const float LimbClearance = 0.026f;   // arms and legs need less
```

One knob per group is the point. A client run can then move the whole garment
at once and you learn something from every frame; tuning radius by radius
against a photograph is how three passes get spent finding out nothing.

A torso ring has to clear a chest, a back, and whatever the wearer is carrying.
An arm is a cylinder about 100 mm across. Giving limbs the torso's clearance
produced 190 mm sleeves and a suit that read as inflated — a pressure suit, not
a coverall.

### A renderer's bounds are not a measurement of the part you care about

`Helpers.RigBounds` (7dtd-playtest) reports each skinned renderer's local AABB,
and it is the obvious place to look for "how wide is the body". It is a trap.

A whole-body renderer's box is bounded by whatever sticks out furthest, and in
an A-pose that is **the toes and the hands**. One reading of
`extents=(0.413, 0.739, 0.279)` treated 0.279 as chest depth and produced a
garment 0.53 m front to back — a barrel. The same file had already rejected the
same reasoning for width, correctly noting that 0.413 is arms; and then applied
it to depth anyway, in the same session.

If you want a chest measurement, the torso bones are all at one z and the body
is roughly symmetric about it. Start from the joint and add clearance.

### Anything lying on a curved shell must be built from that shell's profile

Two rules, and both were learned by doing the opposite.

**A flat quad on a curved surface does not work.** Its centre nearly touches and
its edges stand well off — on a head, a 90 mm half-width panel against a 114 mm
half-width skull leaves the edges floating 58 mm out while the middle clears by
10. The shell then bulges through the middle and the feature renders as a
U-shaped cut-out. Moving it forward or back does not help: the depth was never
the fault, the flatness was. Build a **partial ring off the same profile**,
inflated a few millimetres, and every vertex comes from the same ellipse as the
surface beneath it.

**A band that wraps a profile must be authored from that profile's numbers at
the same height.** A belt authored at half-width 0.178 against a torso that had
since grown to 0.191 sat 13 mm inside the fabric and surfaced only where the
torso happened to narrow — reading as a belt clipping through the suit, when it
was the suit clipping through the belt. Derive the band from the profile, or
leave a note beside it saying to retune it when the profile moves.

### Seams are not stripes

Tape at 6% of a limb's length, standing 8 mm proud, is not a seam. It is a
band, and a garment wearing several of them reads as striped sportswear. Three
things made them read as taped industrial gear instead:

- narrower — about 3.5% of the limb, 3 mm proud
- **only where two pieces of gear actually meet**: wrists, ankles, the collar
- nowhere in the middle of a thigh or an upper arm, because there is nothing
  there for a seam to seal, and a band there is a stripe by definition

### Segment count

Sixteen segments around a ring is a reasonable default for a prop and wrong for
a garment. A 16-sided tube 0.48 m across has 90 mm facets, and worn, a torso
reads as flat panels with hard edges between them. Clothing is also the one
asset a player looks at from a metre away for hours. Twenty-four costs about
half again as many vertices on meshes under a thousand.

### A rig joint is not always where you would put a seam

A shoulder ring is perpendicular to the nearly-horizontal Shoulder→Arm segment,
so it lies in a vertical plane, and its *radius* reaches across the chest and up
past the neck. Widened to bridge an armpit gap, it drove a disc straight through
the torso and rendered as a hard diagonal slab across the upper back.

Check what plane a ring actually lies in before growing it. The armpit was the
torso's job — the torso already reached past the arm joint — not the sleeve's.

### An open tube shows its own inside

Cap the ends of anything the wearer's body does not fill. An uncapped sleeve
renders as a pale hollow exactly where a hand should be, and it is very
convincing as "the wearer's hand is poking through the glove". A cap is only
ever visible if the piece that should cover it does not, which is that piece's
problem.

## Order of work


1. Read the bone names off a running client and write them down.
2. Model and skin in Blender to an armature using those names.
3. Export, import into the Unity project, and build the prefab: parts named,
   `GearBoneMap` baked, materials given their `_Tint` / `_ClipFPV` properties.
4. `shamway build`, then `shamway validate`.
5. Equip it in a fresh client and look at it, in third person and in first.
   `SetFirstPersonView(false, false)` is what the view-toggle key calls, and a
   staged frame is the evidence — see the visual-confirmation section of
   `7dtd-playtest`'s README.

Steps 1 and 5 are the ones a person cannot skip: the first because the names
are unguessable, the last because nothing in any gate can see a garment that
deforms wrongly.

## What has no answer yet

- Whether a garment served from a mod bundle *deforms* correctly once loaded.
  The load path is settled (above); nothing has exercised the bind.
- Whether a garment skinned to an approximate armature, rather than to TFP's
  actual rig asset, deforms acceptably. Bone *names* are what bind; bind poses
  and weights are the authoring problem, and nobody has measured how much
  slack there is.
- Morph assets per race and variant, which multiply the work by the number of
  head shapes and have no generator.
