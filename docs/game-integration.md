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

Common properties that use the same `DataLoader` asset path include block
`Model` and item `Meshfile`/`HandMeshfile`/`DropMeshFile`. Code loads other
Unity types through the same mechanism with `DataLoader.LoadAsset<T>` —
`GameObject`, `Transform`, `AudioClip` — so one URI form covers meshes,
prefabs, and audio.

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

The filename stem is the `CustomIcon` key. Keep icon source and provenance
outside the deployable path and commit the final PNG. A bundle rebuild is
unnecessary for icon-only changes, and `7dtd-assets validate` does not cover
icons because they are not bundle members.

`CustomIconTint` multiplies the icon's colour. If the PNG already carries an
authored palette, leave the property off; a leftover tint from an earlier
design silently recolours the new art.

## Audio

Audio clips and AudioSource prefabs can live in the bundle. A `sounds.xml`
entry points `ClipName` at a mod-folder bundle URI, because
`Audio.Manager.LoadAudio` resolves it through the same
`DataLoader.LoadAsset<AudioClip>` path as meshes — so `7dtd-assets validate`
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
`7dtd-assets generate sound sounds-xml <stem>`.

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

- `ItemClass.GetDroppedCorrectionRotation` lays a dropped item flat — measured
  as `(-90, 0, 0)` on V 3.1.0 b14. Author the item standing along local +Y,
  the way a held grenade does, and the engine puts it on its side when dropped.
- `DropScale` multiplies the dropped form's size, so the held and dropped
  readings of one mesh differ by that factor.
- `ItemClass.CloneModel` calls `UpdateLight.SetTintColor`, which multiplies
  **every material's `_Color`** by the item's `TintColor`. On a mesh with an
  authored palette this darkens or recolours the paint, so omit `TintColor`
  rather than relying on a neutral value.

Test held, dropped, and placed forms separately; they are three different code
paths over the same asset.

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

An `ActivationTransformToHide` child (a lamp, an indicator) is authored
**active**: `ItemClassTimeBomb.setActivationTransformsActive` uses
`FindInChilds`, which finds inactive children too, and the engine hides the
child when holding starts.

## Clients and servers

Asset-bearing mods must be installed on every client; servers do not transfer
bundles or icons as a substitute for client installation. Most mods that are
not purely cosmetic also need EasyAntiCheat disabled in the launcher, which is
part of the install instructions a released mod owes its players and part of
setting up a fresh client for acceptance. A headless server
may still traverse an asset reference, so “cosmetic” does not imply that a
broken URI is harmless server-side.

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
├── Localization.csv            # 3.x, not .txt
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

`Localization.csv` (3.x — not `.txt`) belongs in the mod root, with keys
prefixed by the mod id. It is not an asset this pipeline builds, but every
custom item, block, and control needs a string there, and a missing one shows
in game as the raw key.

Do not deploy `.7dtd-assets.toml`, `tools/`, `assets-src/`, editable sources,
Unity project state, manifests, build logs, scripts, or documentation unless
the mod's release policy explicitly includes authoring material. Zip so that
extracting into `Mods/` yields `Mods/MyMod/ModInfo.xml` immediately — no nested
`MyMod/MyMod/`.
