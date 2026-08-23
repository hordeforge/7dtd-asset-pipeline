# 7 Days to Die integration

## Asset URI form

```xml
<property name="Model"
  value="#@modfolder(ExampleMod):Resources/examplemod.unity3d?exampleModWorkbench.prefab" />
```

The four pieces are contractual:

1. `ExampleMod` is the `ModInfo.xml` `Name`, not merely a folder label. The
   game also accepts the bare `@modfolder:` form, which resolves to the mod
   that owns the patch file; validation treats it as a self-reference and
   accepts it. Prefer the explicit named form, because it fails loudly when a
   file is copied into a different mod.
2. `Resources/examplemod.unity3d` is the path below the deployed modlet.
3. `?` separates the bundle from its asset request.
4. `exampleModWorkbench` is resolved by file-name stem. The displayed
   extension/subfolder after `?` is not the unique key, though an accurate
   readable path is recommended.

Bundle file lookup is case-insensitive, while later object-name checks can be
case-sensitive. Keep exact case everywhere rather than relying on the first
half of that behavior.

### How the engine resolves it

The chain, decompiled from V 3.1.0 b14 with `ilspycmd` (see
[research-provenance.md](research-provenance.md)):

1. `DataLoader.ParseDataPathIdentifier` runs `ModManager.PatchModPathString`
   **first**, which rewrites `@modfolder(Name):` to the loaded mod's real path.
   When no loaded mod has that name, `ModManager.TryPatchModPathString` logs
   `[MODS] Mod reference for a mod that is not loaded` — grep for that line
   before suspecting the bundle.
2. It then splits the `#…?…` form at `?` into bundle path and asset request.
3. `AssetBundleManager.LoadAssetBundle` treats a rooted path as final and a
   relative one as `Data/Bundles/Standalone<BundleTags.Tag>/…` — which is why a
   mod must use the `#@modfolder` form and can never reach its bundle with a
   bare relative path.
4. `AssetBundleManager._get` reduces the asset request to its file-name stem:
   `GameIO.GetFilenameFromPathWithoutExtension` splits on
   `ResourcePathSeparators = { '/', '\\', '?' }`, so `?Sub/Dir/stem.prefab`
   and `?stem` ask for the same object. Folder and extension are display
   only.
5. `BlockShapeModelEntity.getPrefab` compares the loaded object's name with
   that stem and logs `Model has a wrong name` on any difference, substituting
   `block_missingPrefab`; items fall back to
   `@:Other/Items/Crafting/leather.fbx`. A failed load therefore always draws
   *something*. It also registers the prefab with `GameObjectPool.AddPooledObject`,
   so a placed model is a pooled instance — state left on a pooled object
   reappears on the next placement.

`@:` is the other prefix you will see, in vanilla XML and in fallbacks: it
names an **Addressable** vanilla asset (`@:Other/Items/Crafting/leather.fbx`,
`@:Sounds/Prefabs/AudioSource_Explosion.prefab`). A mod can reference vanilla
content that way as a stand-in; it cannot put its own content there.

The bundle itself is opened lazily, by `LoadManager.LoadAsset`, on first use.
On a dedicated server that load runs **synchronously**, so a broken bundle
reference is a server-side error at the moment the server first resolves it,
not a client-only cosmetic one.

Common properties that use the same `DataLoader` asset path include block
`Model` and item `Meshfile`/`HandMeshfile`/`DropMeshFile`. Code loads other
Unity types through the same mechanism with `DataLoader.LoadAsset<T>` —
`GameObject`, `Transform`, `AudioClip` — so one URI form covers meshes,
prefabs, and audio.

### Names are global and baked into saves

Item, block, recipe, and tag names share one namespace across **every**
installed mod, which is the first reason for a mod prefix. The second is
worse: names are written into save data. Renaming an item or block after a
world exists orphans every placed block and every stack of it. Settle the
names — and therefore the asset stems tied to them — before the first world
test, not after.

## One mod-owned bundle

One bundle per small/medium mod is a good default:

- one deployable artifact and one manifest;
- one uniqueness namespace that validation can exhaustively check;
- fewer lazy-open boundaries and less packaging drift;
- source remains owned by the mod.

Split bundles only for a measured reason such as optional content, substantial
memory lifetime differences, or platform-specific shaders. When splitting,
each bundle needs its own config/build/manifest/acceptance evidence; schema 1
currently models one bundle per config file.

## Item icons are not bundle assets

Current 7DTD mod UI atlases load individual PNGs placed under:

```text
UIAtlases/<AtlasName>/<CustomIconName>.png
```

`ModManager.LoadUiAtlases` loads **each immediate subfolder** of a mod's
`UIAtlases/` directory as a runtime-packed atlas: the folder name is the atlas
name, and each `.png` inside is keyed by its filename stem. The game already
registers `ItemIconAtlas`, so a mod extends it by adding files to a folder of
that name rather than declaring anything.

`ModManager.LoadUiAtlases` does this through
`UIAtlasFromFolder.CreateUiAtlasFromFolder`; the legacy single `ItemIcons/`
folder and pre-packed atlas sheets are the superseded alternatives. The cell
size, 160 × 160, was measured against the vanilla atlas's `mip0` cells.

The filename stem is the atlas key. Two XML properties name one: `CustomIcon`
on an item or block, and `display_entry icon=` in `progression.xml`. When an
item names **no** `CustomIcon`, the engine looks the sprite up by the item's
own name — `CustomIcon` exists for the cases where the sprite name differs,
such as a block that should show an item's icon. So an item whose atlas PNG is
named exactly like the item needs no property at all, and a typo in that PNG's
name is invisible to any check that only reads `CustomIcon`.
`shamway check-icons` reconciles `CustomIcon`, `display_entry icon=`, and
every item or block name against the atlas for exactly this reason. Keep icon
source and provenance outside the deployable path and commit the final PNG. A bundle rebuild is
unnecessary for icon-only changes, and `shamway validate` does not cover
icons because they are not bundle members.

`CustomIconTint` multiplies the icon's colour. If the PNG already carries an
authored palette, leave the property off; a leftover tint from an earlier
design silently recolours the new art.

## Audio

Audio clips and AudioSource prefabs can live in the bundle. A `sounds.xml`
entry points `ClipName` at a mod-folder bundle URI, because
`Audio.Manager.LoadAudio` resolves it through the same
`DataLoader.LoadAsset<AudioClip>` path as meshes — so `shamway validate`
checks a `ClipName` exactly as it checks a `Model`:

```xml
<configs>
	<append xpath="/Sounds">
		<SoundDataNode name="myModBlast">
			<AudioSource name="Sounds/AudioSource_Explosion" />
			<AudioClip ClipName="#@modfolder(MyMod):Resources/mymod.unity3d?myModBlastNear.wav" />
			<DistantClip ClipName="#@modfolder(MyMod):Resources/mymod.unity3d?myModBlastDistant.wav" />
			<Noise ID="myModBlast" range="40" volumeScale="1" heardBy="Enemy" />
		</SoundDataNode>
	</append>
</configs>
```

Generate that block with
`shamway generate sound sounds-xml <stem>`.

A correctly loaded clip can still be inaudible: `LoadAudio` plays nothing past
the AudioSource prefab's `maxDistance`, and `DistantFadeStart` defaults to `-1`
(never), so a `DistantClip` authored without setting it never plays. A
long-range event needs a deliberately authored source rather than a
grenade-scale vanilla one. The whole lane, with the gates and the listening
checklist, is in [audio.md](audio.md).

## Models and item state

Author axes, root scale, colliders, and named child transforms against the
specific consuming game path. The engine applies its own corrections *after*
loading, so the prefab root must stay at identity and let them apply:

- `ItemClass.CloneModel` resolves the mesh in a fixed order: `DropMeshFile`
  for the dropped form, then `HandMeshfile` for the held form, then `Meshfile`.
  One authored mesh can serve all three; a variant that differs only when
  dropped needs only `DropMeshFile`.
- `ItemClass.GetDroppedCorrectionRotation` lays a dropped item flat — measured
  as `(-90, 0, 0)` on V 3.1.0 b14, applied by `EntityItem.createMesh` as the
  mesh's local rotation. Author the item standing along local +Y, the way a
  held grenade does, and the engine puts it on its side when dropped.
- `DropScale` is applied by `EntityItem.createMesh` as a uniform local scale,
  so the held and dropped readings of one mesh differ by that factor.
- `EntityItem.createMesh` **enables every collider it finds in the mesh** on
  layer 13 (adding `RootTransformRefEntity` to each) and disables the entity's
  own root collider only when it found one; a mesh with no collider rides on
  the entity's default collider. Vanilla's `GrenadePrefab` carries one root
  `CapsuleCollider`. Ship one deliberate collider on the root, and no
  accidental ones on children — each would become a physics body.
- `ItemClass.CloneModel` always adds `UpdateLightOnAllMaterials` and calls
  `SetTintColorForItem` with the item's `TintColor` or the default
  `255,255,255`; `Block.StringToVector3` divides by 255 and
  `UpdateLight.SetTintColor` writes the result into **every material's
  `_Color`**. White is a no-op, so omitting the property and setting white are
  equivalent — the hazard is an *inherited* non-white tint multiplying an
  authored palette. Omit `TintColor` on anything with its own paint, and
  exclude it from inheritance (below).
- Vanilla's `GrenadePrefab` and `timedChargePrefab` are identity-transform
  prefabs (root scale 1, no rotation) whose mesh children sit at the origin —
  read with UnityPy from
  `Data/Addressables/Standalone/automatic_assets_other/items.bundle`. A held
  item is therefore authored **at hand scale**, in world axes, local +Y up,
  and the installed game's own item prefabs are the calibration reference for
  "how big is held".
- `BlockShapeModelEntity` reads `Model`, `ModelOffset`, and `LODCullScale`
  but **no scale property**. A placed model that is too small cannot be fixed
  in XML; it must be authored at world scale. (The source project's first
  prototype reused a vanilla mine prefab and needed a 5× model to read at all.)

Test held, dropped, and placed forms separately; they are three different code
paths over the same asset. For a placed model, a fresh client must also show
correct placement bounds, orientation, and — when the block is powered — wire
endpoints. Keep a model override separate from gameplay inheritance: never
swap a block's base class just to borrow a visual.

### Inherited properties are the quiet failure here

`ItemClassesFromXml` and `BlocksFromXml` copy every parent property that the
`Extends` `param1` list does not name. **Not restating a property does not stop
it being inherited** — it has to be excluded:

```xml
<property name="Extends" value="thrownGrenadeContact" param1="Meshfile,TintColor" />
```

That is how a mod item with an authored olive palette ends up multiplied by
vanilla's red grenade tint after the tint line was "removed", and how a new
variant ends up wearing another variant's mesh. Exclude `Meshfile`, `Model`,
`CustomIcon`, and `TintColor` on anything that owns its own art.

The edges of that rule, all from the same decompile:

- `param1` can exclude a whole `<property class="…">` block by its class name,
  and a single nested key by its dotted `Class.Property` form
  (`DynamicProperties.CopyFrom`).
- `effect_group` is **not** inherited: `ItemClassesFromXml` builds `Effects`
  from the child node alone. A child that restates nothing has no effects.
- `CreativeMode` is never inherited.

An `ActivationTransformToHide` child (a lamp, an indicator) is authored
**active**: `ItemClassTimeBomb.Init` splits the property on `;` so several
names are allowed, and `setActivationTransformsActive` finds each with
`FindInChilds` (which finds inactive children too) and toggles it — `Meta != 0`
on mesh creation, `true` while a dropped countdown runs, `false` when holding
starts. Vanilla's `timedChargePrefab` ships its `Armed` child active for this
reason. `ActivationEmissive` is a separate mechanism that keys on a renderer
**tag**; tags are project-level settings, so a bundle built in a different
Unity project cannot rely on it. Layers are the other project-level
setting worth knowing: the engine assigns layer 13 to item colliders itself,
so author on the default layer and let it.

## Clients and servers

Asset-bearing mods must be installed on every client; servers do not transfer
bundles or icons as a substitute for client installation. The mechanism,
confirmed against the V 3.1 assembly: a server sends its **patched XML** to a
joining client through `NetPackageConfigFile`, but `ModManager` loads
assemblies only from the local mod folder and does not load UI atlases on a
dedicated server at all. Nothing transfers a bundle, a DLL, or an atlas at
join, so the identical package is the deployment unit on both sides.

Most mods that are not purely cosmetic also need EasyAntiCheat disabled in the
launcher, which is part of the install instructions a released mod owes its
players and part of setting up a fresh client for acceptance. The switch is
explicit: a `ModInfo.xml` with `SkipWithAntiCheat="true"` makes an EAC-on
client return `Mod.EModLoadState.SkippedDueToAntiCheat` before loading
anything, excluding the **whole** mod — assets included — rather than failing
partway. A headless server still resolves asset references, synchronously, so
"cosmetic" does not imply that a broken URI is harmless server-side.

Presentation code that must run only on a client can key on the fact that
`EntityPlayerLocal` is never constructed on a dedicated server; a hook on it
is client-only by construction, with `GameManager.IsDedicatedServer` as the
belt-and-braces guard.

Build the ordinary Windows-target bundle for Windows and Proton clients. A
native macOS client using Metal may need shader variants from a macOS-target
bundle. The pipeline does not pretend one artifact covers Metal. If the mod
supports native macOS and ships materials/custom shaders, establish a tested
selection/loading strategy and document it explicitly.

## Packaging

Deploy:

```text
MyMod/
├── ModInfo.xml
├── Config/                     # XPath patches: items, blocks, recipes, sounds
│   └── Localization.csv        # inside Config/ — the engine reads nowhere else
├── Resources/examplemod.unity3d
├── UIAtlases/
│   └── ItemIconAtlas/
├── Prefabs/                    # POIs and world prefabs, when the mod ships any
└── UI/                         # custom XUi windows/styles, when the mod ships any
```

Every folder is optional; include only what the mod needs. `Prefabs/` and `UI/`
are outside this pipeline's scope — it builds and validates the bundle, the
atlas, and their XML references — but they belong in the picture, because a mod
that ships them still packages them alongside what this pipeline produces.

`Localization.csv` (3.x — not `.txt`) belongs **inside `Config/`**, with keys
prefixed by the mod id. It is not an asset this pipeline builds, but every
custom item, block, and control needs a string there, and a missing one shows
in game as the raw key. The location is not a convention: `ModManager.LoadLocalizations`
builds `mod.Path + "/Config"` and `Localization.LoadPatchDictionaries` opens
`<that folder>/Localization.csv` — a file at the mod root is never read, no
error is logged, and `Localization.Get` returns each key unchanged, so every
display name silently degrades to its id. The diagnostic is one log line:
`[MODS] Loading localization from mod: <name>` appears whenever the file was
found. Its absence means the file is in the wrong place.

Do not deploy `.shamway.toml`, `tools/`, `assets-src/`, editable sources,
Unity project state, manifests, build logs, scripts, or documentation unless
the mod's release policy explicitly includes authoring material. Zip so that
extracting into `Mods/` yields `Mods/MyMod/ModInfo.xml` immediately — no nested
`MyMod/MyMod/`.
