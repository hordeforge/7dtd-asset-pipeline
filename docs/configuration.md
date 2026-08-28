# Configuration

`shamway init` writes `.shamway.toml` at the mod root. Paths are
relative to that file unless absolute. Environment variables are expanded;
`~` is expanded for user convenience.

What `init` writes by default — no Unity editor, no Unity project:

```toml
schema_version = 1
mod_root = "."
mod_name = "ExampleMod"
bundle_name = "examplemod.unity3d"
bundle_source = "synthesized"
source_root = "assets-src/bundle"
build_dir = ".shamway/build"
manifest_dir = "tools/shamway/manifests"
resources_dir = "Resources"
config_dir = "Config"
target = "StandaloneWindows64"
compress_textures = false
code_references = []

[unity]
version = "2022.3.62f2"

[game]
directory = ""
```

What `--bundle-source unity` writes instead. The two extra keys are the whole
difference, and `[unity] editor` is the only one that names an editor:

```toml
bundle_source = "unity"
unity_project = "tools/shamway/UnityProject"
source_root = "Assets/ModAssets/Bundle"

[unity]
editor = ""
version = "2022.3.62f2"
```

| Key | Meaning |
|---|---|
| `schema_version` | Configuration contract. Must be `1`. |
| `mod_root` | Deployable 7DTD modlet root containing `ModInfo.xml`. |
| `mod_name` | Exact `ModInfo.xml` `<Name value>` and `@modfolder(...)` id. |
| `bundle_name` | Lowercase staged file name ending in `.unity3d`. Must be empty when `bundle_source = "none"`. |
| `bundle_source` | Where the bundle comes from: `"synthesized"` (this tool writes it directly, no editor), `"none"` (the mod ships no bundle), `"external"` (an editor elsewhere builds it and `shamway stage` gates it here), or `"unity"` (a local editor builds it). **Default `"synthesized"`** — an absent key means no editor, because Unity is opt-in. `shamway init --adopt PROJECT` is the one place an unstated source means `"unity"`, since pointing at a project the mod already has *is* the opt-in. See [no-unity.md](bundles/no-unity.md). |
| `unity_project` | Non-deployed Unity project owned by the mod. `init` creates it for the `"external"` and `"unity"` sources so the editor build has committed source and settings. Only the effective `bundle_source = "unity"` uses it on this machine; an `"external"` host stages an artifact built elsewhere. It is empty for `"synthesized"` and `"none"`. |
| `source_root` | The folder whose files become bundle members. With `bundle_source = "unity"` it is a Unity `AssetDatabase` path *inside the project*; with `"synthesized"` there is no project, so it is read against the mod root (scaffolded as `assets-src/bundle`). |
| `build_dir` | Ignored raw output and Unity log directory. |
| `manifest_dir` | Tracked copy of Unity's per-bundle manifest. |
| `resources_dir` | Modlet destination for the deployed bundle. |
| `config_dir` | Root recursively scanned for XML bundle references. |
| `target` | Unity `BuildTarget`; use `StandaloneWindows64` for normal 7DTD clients. |
| `compress_textures` | Whether the editorless writer block-compresses textures: `DXT1` when an image is fully opaque, `DXT5` when it has alpha, 8x and 4x smaller than RGBA32. Off by default because it is **lossy** — this pipeline does not quietly change what an author signed off on. Both sides of every texture must then be a multiple of four, and the build refuses rather than padding. Ignored by the `unity` and `external` backends, where Unity's own importer decides. |
| `code_references` | Bundle stems the mod's own C# loads (`DataLoader.LoadAsset`, a particle Lights prefab, a scripted clip). No XML names them, so `validate` sees them only when listed; each is checked for membership, uniqueness, and exact case like an XML reference. Stem only, no extension. |
| `unity.editor` | Optional machine path; `UNITY_EDITOR` overrides it. Unused unless the mod opted into an editor, or `verify-bundle`/`render-icon` is run. |
| `unity.version` | The revision recorded at scaffold time. With a Unity project it is a human-readable record only — `ProjectSettings/ProjectVersion.txt` and the installed game's bundles are authoritative. With `bundle_source = "synthesized"` there is no project file, so the editorless writer falls back to this value when no game directory is configured, and `doctor` warns that it did. |
| `game.directory` | Optional machine path; `SEVEN_DAYS_TO_DIE_DIR` overrides it. |

Commit the TOML file, everything under `source_root`, the tracked manifest, and
the staged bundle. A mod that opted into an editor also commits the Unity
project's source and settings and every asset's `.meta` file. Ignore raw build
output and machine paths.

## Environment variables

Machine-local paths never go in the TOML. The pipeline reads these, and no
`.local.env` or other dotenv file — export them in the shell or the CI job:

| Variable | Meaning |
|---|---|
| `SEVEN_DAYS_TO_DIE_DIR` | the installed client, containing `Data/Config/items.xml`; read-only evidence |
| `SHAMWAY_BUNDLE_SOURCE` | `synthesized`, `external`, or `unity`: where *this machine* gets the bundle from, overriding `bundle_source`. It cannot give a mod a bundle it does not have, or take one away — that stays the mod's decision, in the file |
| `UNITY_EDITOR` | the game-matched editor executable. Read only by `bundle_source = "unity"`, `verify-bundle` and `render-icon`; unset is not a problem anywhere else |
| `SEVEN_DAYS_TO_DIE_LOG_DIR` | overrides where `shamway client` looks for `output_log_client__*.txt` (derived from the game dir's Steam library on Proton hosts otherwise) |
| `SEVEN_DAYS_TO_DIE_MODS_DIR` | overrides the per-user `Mods/` folder `shamway client deploy` writes to |
