# Bundle generation

> **This page is the opt-in editor path — `bundle_source = "unity"`.** It is
> not the default and not the shortest route. By default `shamway build`
> writes the bundle itself, with no editor, no project, no `.meta` files and
> none of the engine-module obligations below;
> [no-unity.md](no-unity.md) owns that path and is the one to read first.
>
> Read this page when the bundle needs shading the writer does not author —
> lit, shadowed, transparent, normal-mapped or multi-pass — or when a mod that
> already has a Unity project is adopted with `shamway init --adopt`.

## Artifact flow

```text
editable source + .meta
        |
        v
Unity project: Assets/ModAssets/Bundle/**
        |
        | BundleBuilder.cs (batch mode)
        v
.shamway/build/bundle/<name>.unity3d + .manifest + Unity log
        |
        | log gate + UnityFS revision gate + class-142 gate
        v
Resources/<name>.unity3d + tools/shamway/manifests/<name>.manifest
```

Only `Resources/<name>.unity3d` is deployed. The Unity project, editable art,
raw build directory, logs, and tracked manifest are authoring inputs/evidence.

## Bundle membership

Every non-folder asset below `source_root` is included, except `.meta` and
`.gitkeep`. Membership does not depend on Unity's per-asset AssetBundle field.
This makes membership reviewable by directory and prevents inspector state
from silently adding or removing content.

Commit every source asset with its `.meta` file. Unity GUIDs live in `.meta`;
losing one can break prefab/material/texture relationships while leaving
filenames unchanged.

## Generating part of the bundle at build time

Most real mods build some of their bundle from code — prefabs composed from
primitives, materials, particle systems. Those generators have to run **before**
the folder is collected, or the build ships whatever was there last time.
Silently, because a stale prefab is a perfectly valid prefab.

`BundleBuilder` is pipeline-owned and should not be edited: it carries the
stem-collision rejection, the graphics-API set, and the forced rebuild, and a
mod that forks it inherits none of the later fixes. So the seam is an attribute:

```csharp
[ShamwayPreBuild(Order = 10)]
public static void EnsureGeneratedPrefabs()
{
    // the mod's own generator, in the mod's own editor script
}
```

Every marked method runs before assets are collected, ascending by `Order`,
ties broken alphabetically so a build is reproducible. Use `Order` when one
generator consumes another's materials. The method must be `static` and take no
parameters, and anything it throws fails the build — which is the point: a
generator that could not run must not produce a bundle that looks finished.

Two deliberate behaviours:

- **A probe skips them.** `shamway build --probe` proves the environment with a
  throwaway cube; running the mod's generators there would be slow and
  meaningless.
- **The count is always logged**, including zero. `pre-build: 0 generators` in
  the log distinguishes a mod that has none from a mod whose attribute sits on
  a method the compiler never saw.

A generator that writes into the bundle folder should read the path from
`Shamway.SourceRoot` rather than hardcoding it — otherwise the same
value lives in both `.shamway.toml` and the C#, and drifts the first time
either moves.

Keep the generators idempotent. A common pattern is a stamp constant that the
generator compares before rebuilding, so an unchanged build does not reassign
Unity's internal IDs on every run — but then remember to bump the stamp when
you change the generator's output, or the committed prefab silently keeps its
old shape.

### A complete generator, proven in an editor

The editor script below is the one this repository ran through a real
`shamway build` on Unity 2022.3.62f2 (see [blockers.md](../status/blockers.md)); every
helper it calls executed and every state it sets was read back out of the
built `.mat` and the bundle. It lives in a folder of the mod's own — it
**must** be under an `Editor/` directory, because `UnityEditor` APIs are
editor-only — beside the vendored pipeline scripts, and it writes only under
`Shamway.SourceRoot`, the bundle-membership folder.

```csharp
using SevenDaysToDie.AssetPipeline;
using UnityEngine;

public static class MyModGenerators
{
    [ShamwayPreBuild(Order = 10)]
    public static void EnsureThing()
    {
        var folder = Shamway.SourceRoot + "/Generated";
        var normal = GeneratedAsset.ImportNormalMap(Shamway.SourceRoot + "/Textures/myModSteelNormal.png");
        var mask = GeneratedAsset.ImportLinearMap(Shamway.SourceRoot + "/Textures/myModPaintMask.png");
        var steel = GeneratedAsset.StandardMaterial(folder + "/myModSteelMaterial.mat",
            new Color(0.5f, 0.5f, 0.52f), null, normal, mask, 0.58f, 0.16f);
        GeneratedAsset.Tile(steel, 4f, 4f);
        var lamp = GeneratedAsset.EmissiveMaterial(folder + "/myModLampMaterial.mat", Color.red, Color.red);
        var root = GeneratedAsset.Root("myModThing");
        GeneratedAsset.Primitive(root.transform, PrimitiveType.Cylinder, "body",
            Vector3.zero, Vector3.zero, new Vector3(0.2f, 0.3f, 0.2f), steel);
        GeneratedAsset.Primitive(root.transform, PrimitiveType.Sphere, "lamp",
            new Vector3(0, 0.35f, 0), Vector3.zero, new Vector3(0.05f, 0.05f, 0.05f), lamp);
        GeneratedAsset.RootCapsuleCollider(root, new Vector3(0, 0.3f, 0), 0.2f, 0.6f);
        GeneratedAsset.SavePrefab(root, folder, "myModThing");
        GeneratedAsset.LightPrefab(folder, "myModFlashLight", Color.yellow);
    }
}
```

The textures come from `shamway generate texture-maps` (`detail` for the
steel normal). `myModFlashLight` is referenced by no XML, so it goes in
`code_references`. Before starting an editor, prove the script compiles:

```bash
shamway script compile-editor-scripts --scripts tools/shamway/UnityProject/Assets/SevenDaysToDieAssetPipeline/Editor --with tools/shamway/UnityProject/Assets/MyMod/Editor
```

## Names are an engine contract

7DTD resolves a requested asset by its **file-name stem**, after discarding
directory and extension. Therefore:

- every stem must be unique across the whole bundle, case-insensitively;
- the referenced stem's case must equal the loaded object's name;
- two files such as `Meshes/Radio.fbx` and `Prefabs/radio.prefab` are a
  collision even though their paths and extensions differ;
- a material and the texture or card it uses naturally want the same name,
  so name materials with a `Material` suffix;
- use a mod-specific prefix on every shippable asset.

The C# builder rejects collisions before serialization. The Python validator
checks the tracked manifest independently.

## Export settings

The template calls `BuildPipeline.BuildAssetBundles` with one explicit
`AssetBundleBuild` and:

- `BuildAssetBundleOptions.ChunkBasedCompression` (LZ4);
- `StrictMode`;
- `ForceRebuildAssetBundle`;
- `StandaloneWindows64` by default;
- D3D11, OpenGLCore, and Vulkan graphics APIs;
- `PlayerSettings.stripEngineCode = false` during serialization, restored in
  a `finally` block.

`ForceRebuildAssetBundle` is not a performance preference. Unity's incremental
cache can reuse a bundle after package/module or player-setting changes. A
full reserialization ensures a corrected project does not restage old broken
bytes.

## Required engine modules

Unity built-in engine features are packages. The scaffold's
`Packages/manifest.json` includes the standard module set, especially:

- `com.unity.modules.assetbundle` — required for the class-142 container;
- `com.unity.modules.particlesystem` — required when bundling particles;
- `com.unity.modules.audio` — required for AudioClips/AudioSources;
- `com.unity.modules.physics` — required for 3D colliders/rigidbodies;
- `com.unity.modules.imageconversion` — common texture support.

Do not “minimize” that manifest without proving the emitted object table and a
fresh client. The editor can author a component whose module is absent from
build dependencies; serialization then strips it and may only warn.

## Build command

```bash
shamway build
```

With `bundle_source = "unity"`, the CLI:

1. verifies editor, project, installed-game revision, and Windows module;
2. runs Unity in batch/no-graphics mode;
3. requires a zero editor exit and expected output files;
4. rejects any disabled-module warning in the Unity log;
5. checks the built bundle's revision and class-142 type;
6. parses the generated manifest and rejects bundle-wide stem collisions;
7. atomically stages the manifest first, then makes the validated deployed
   bundle the final commit point.

An old valid artifact therefore survives a failed build. The command never
partially copies a candidate into the modlet.

The same command with the default `bundle_source = "synthesized"` skips steps
1 to 4 entirely — there is no editor to verify, run, wait for, or read a log
from — and does steps 5 to 7 unchanged on a bundle it wrote itself in
milliseconds. It also prints what its own gates are worth, because an artifact
and a checker with the same author cannot cross-examine each other.

## When the editor is on another machine

Steps 3 to 7 above read files, not an editor, so they run anywhere the built
artifact can be copied to:

```bash
shamway stage build/mymod.unity3d --manifest build/mymod.unity3d.manifest --log build/unity-build.log
```

Bring all three files back: the bundle is the artifact, the manifest is the
only offline record of membership, and the log is the only place a
success-while-stripping build admits it. `stage` prints a `not run:` line for
every gate the missing evidence prevented. [no-unity.md](no-unity.md) covers
the whole path, including the `SHAMWAY_BUNDLE_SOURCE` the build host sets so
one committed configuration works on both machines.

## Determinism

Unity is asked to fully rebuild. For a reproducibility check:

```bash
shamway build
sha256sum Resources/examplemod.unity3d tools/shamway/manifests/*
shamway build
sha256sum Resources/examplemod.unity3d tools/shamway/manifests/*
```

If hashes move with unchanged tracked inputs, inspect generated asset scripts,
timestamps embedded by custom importers, nondeterministic procedural seeds,
and uncommitted `.meta` changes. A prefab generator should write only when its
schema/version stamp changes; rewriting otherwise identical prefabs can change
internal IDs.

The stamp has a trap on its other side: **a generator edited without bumping
its stamp silently ships the old prefab**, with a green build and a
matching-looking icon (`render-icon` photographs what is on disk). Only a
live check of the prefab's detail caught it in the source project. Bump the
stamp in the same edit as the geometry, every time.

Unity also rewrites `ProjectSettings/ProjectSettings.asset` on every
experiment — `targetPixelDensity`, `buildNumber`, iOS/tvOS strings, an
automatic `m_BuildTargetGraphicsAPIs` entry — churn unrelated to any fix.
Discard it deliberately, hunk by hunk, never by bulk-reverting the project
directory, which would also throw away a real `.meta`.

## Script-authored materials

Setting a visible material property is not necessarily enough. Unity's
Inspector GUIs often also set shader keywords, blend factors, depth-write
state, and render queues. Batch builds do not run that GUI.

At minimum, verify generated `.mat` text for:

- `_NORMALMAP` when assigning `_BumpMap`;
- `_METALLICGLOSSMAP` when assigning a packed metallic map — and the same
  texture assigned to `_OcclusionMap` as well, because Standard reads
  occlusion from that slot's G channel only;
- `_EMISSION` when assigning `_EmissionColor`, or the lamp is painted, not lit;
- correct texture import type and linear/sRGB setting, with masks capped at
  512 px and normals at 1024 px (mask channels are blurred fields, so extra
  resolution stores noise; two 1024 px normals tripled the source bundle);
- particle `_SrcBlend`, `_DstBlend`, `_ZWrite`, keywords, and render queue;
- compatible curve modes across particle axes.

These states can be wrong with a clean build, a valid bundle, a successful
client load, and no missing asset. Human rendering review remains mandatory.

`GeneratedAsset.StandardMaterial`, `EmissiveMaterial`, `Tile`, and
`ParticleMaterial` set every one of those states; the `.mat` grep in
[vfx.md](../authoring/vfx.md) reads them back.

## Compiling the editor scripts without an editor

The Python suite cannot see a C# mistake, and Unity reports one only as
"Scripts have compiler errors". `scripts/compile-editor-scripts.sh` compiles
the five vendored editor scripts with Mono's `mcs` against the installed
editor's own `Managed/UnityEngine/*.dll` and netstandard 2.1 reference —
about ten seconds, no editor started — and `make check` runs it whenever
`mcs` and an editor are present. It proves the scripts compile for that
revision; it does not prove they do the right thing when run, and a report
must keep that distinction. Its first run found a hard-obsolete API
(`AudioImporter.preloadAudioData`) that would have failed every editor
compile in a consuming mod.
