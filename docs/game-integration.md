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
entry can point `ClipName` at a mod-folder bundle URI, because
`Audio.Manager.LoadAudio` resolves it through the same
`DataLoader.LoadAsset<AudioClip>` path as meshes. Validate in the actual
game because an AudioSource's `maxDistance`, sound-group fade ranges, looping,
voice limits, and distant clip decide whether a correctly loaded clip is
heard. A long-range event usually needs a deliberately authored source rather
than a grenade-scale vanilla source.

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

## Clients and servers

Asset-bearing mods must be installed on every client; servers do not transfer
bundles or icons as a substitute for client installation. A headless server
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
├── Config/
├── Resources/examplemod.unity3d
└── UIAtlases/                  # when used
```

Do not deploy `.7dtd-assets.toml`, `tools/`, editable sources, Unity project
state, manifests, build logs, scripts, or documentation unless the mod's
release policy explicitly includes authoring material.
