# Skinned character gear (SDCS armor)

Worn armor is the one asset class in 7 Days to Die that a mod cannot reach
through the prop lane. A held item, a placed block and a VFX card are all
static: a mesh, a material, a prefab, done. A garment has to deform with the
wearer, and the engine binds it to the player's skeleton at the moment it is
equipped. That changes what has to be authored, and it closes the editorless
lane, so it gets its own page.

**Status: the contract is verified against the installed build; this lane has
not yet produced a shipped garment.** The engine behaviour below is reversed
from IL in
[`hordeforge/7dtd-engine-research`](https://github.com/hordeforge/7dtd-engine-research),
`docs/sdcs-character-gear.md`, which is the authority and carries the IL
evidence index. What is written here is what that means for authoring. Where
this page marks something *inferred*, nobody has run it.

## Why this is not the mesh lane

`shamway build` writes bundles without Unity, and for a static mesh that is the
whole story. A skinned mesh is different in two ways that both bite:

- It carries a bind pose, bone weights per vertex, and a `SkinnedMeshRenderer`
  whose `bones[]` array points at transforms. None of that is in the editorless
  writer's scope, and pretending otherwise produces a bundle that loads and a
  garment that does not move.
- The prefab needs Unity components (`GearBoneMap`, optionally `Morphable`,
  rig constraints) that only the editor bakes.

So a mod authoring gear is on `bundle_source = "unity"`. That is not a
temporary gap to route around; it is the honest boundary, and
[authoring-tools.md](authoring-tools.md) already says rigging and animation are
outside the editorless lane.

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

Still true: **no mod has shipped a garment through this path**, so the loading
is settled and the deformation is not.

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
