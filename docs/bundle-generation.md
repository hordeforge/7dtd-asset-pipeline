# Bundle generation

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

## Names are an engine contract

7DTD resolves a requested asset by its **file-name stem**, after discarding
directory and extension. Therefore:

- every stem must be unique across the whole bundle, case-insensitively;
- the referenced stem's case must equal the loaded object's name;
- two files such as `Meshes/Radio.fbx` and `Prefabs/radio.prefab` are a
  collision even though their paths and extensions differ;
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

The CLI:

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

## Script-authored materials

Setting a visible material property is not necessarily enough. Unity's
Inspector GUIs often also set shader keywords, blend factors, depth-write
state, and render queues. Batch builds do not run that GUI.

At minimum, verify generated `.mat` text for:

- `_NORMALMAP` when assigning `_BumpMap`;
- `_METALLICGLOSSMAP` when assigning a packed metallic map;
- correct texture import type and linear/sRGB setting;
- particle `_SrcBlend`, `_DstBlend`, `_ZWrite`, keywords, and render queue;
- compatible curve modes across particle axes.

These states can be wrong with a clean build, a valid bundle, a successful
client load, and no missing asset. Human rendering review remains mandatory.
