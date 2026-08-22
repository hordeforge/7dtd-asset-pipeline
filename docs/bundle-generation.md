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
.asset-pipeline/build/bundle/<name>.unity3d + .manifest + Unity log
        |
        | log gate + UnityFS revision gate + class-142 gate
        v
Resources/<name>.unity3d + tools/7dtd-assets/manifests/<name>.manifest
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
7dtd-assets build
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
7dtd-assets build
sha256sum Resources/examplemod.unity3d tools/7dtd-assets/manifests/*
7dtd-assets build
sha256sum Resources/examplemod.unity3d tools/7dtd-assets/manifests/*
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
