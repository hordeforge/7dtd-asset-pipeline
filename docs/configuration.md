# Configuration

`7dtd-assets init` writes `.7dtd-assets.toml` at the mod root. Paths are
relative to that file unless absolute. Environment variables are expanded;
`~` is expanded for user convenience.

```toml
schema_version = 1
mod_root = "."
mod_name = "ExampleMod"
bundle_name = "examplemod.unity3d"
unity_project = "tools/7dtd-assets/UnityProject"
source_root = "Assets/ModAssets/Bundle"
build_dir = ".asset-pipeline/build"
manifest_dir = "tools/7dtd-assets/manifests"
resources_dir = "Resources"
config_dir = "Config"
target = "StandaloneWindows64"

[unity]
editor = ""
version = "2022.3.62f2"

[game]
directory = ""
```

| Key | Meaning |
|---|---|
| `schema_version` | Configuration contract. Must be `1`. |
| `mod_root` | Deployable 7DTD modlet root containing `ModInfo.xml`. |
| `mod_name` | Exact `ModInfo.xml` `<Name value>` and `@modfolder(...)` id. |
| `bundle_name` | Lowercase staged file name ending in `.unity3d`. |
| `unity_project` | Non-deployed Unity project owned by the mod. |
| `source_root` | Unity `AssetDatabase` path whose files become members. |
| `build_dir` | Ignored raw output and Unity log directory. |
| `manifest_dir` | Tracked copy of Unity's per-bundle manifest. |
| `resources_dir` | Modlet destination for the deployed bundle. |
| `config_dir` | Root recursively scanned for XML bundle references. |
| `target` | Unity `BuildTarget`; use `StandaloneWindows64` for normal 7DTD clients. |
| `unity.editor` | Optional machine path; `UNITY_EDITOR` overrides it. |
| `unity.version` | Human-readable scaffold record. ProjectSettings and game bundles are authoritative. |
| `game.directory` | Optional machine path; `SEVEN_DAYS_TO_DIE_DIR` overrides it. |

Commit the TOML file, Unity project source/settings, `.meta` files, tracked
manifest, and staged bundle. Ignore raw build output and machine paths.
