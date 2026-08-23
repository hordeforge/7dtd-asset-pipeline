# Configuration

`shamway init` writes `.shamway.toml` at the mod root. Paths are
relative to that file unless absolute. Environment variables are expanded;
`~` is expanded for user convenience.

```toml
schema_version = 1
mod_root = "."
mod_name = "ExampleMod"
bundle_name = "examplemod.unity3d"
unity_project = "tools/shamway/UnityProject"
source_root = "Assets/ModAssets/Bundle"
build_dir = ".shamway/build"
manifest_dir = "tools/shamway/manifests"
resources_dir = "Resources"
config_dir = "Config"
target = "StandaloneWindows64"
code_references = []

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
| `code_references` | Bundle stems the mod's own C# loads (`DataLoader.LoadAsset`, a particle Lights prefab, a scripted clip). No XML names them, so `validate` sees them only when listed; each is checked for membership, uniqueness, and exact case like an XML reference. Stem only, no extension. |
| `unity.editor` | Optional machine path; `UNITY_EDITOR` overrides it. |
| `unity.version` | Human-readable scaffold record only; the pipeline never reads it. `ProjectSettings/ProjectVersion.txt` and the installed game's bundles are authoritative. |
| `game.directory` | Optional machine path; `SEVEN_DAYS_TO_DIE_DIR` overrides it. |

Commit the TOML file, Unity project source/settings, `.meta` files, tracked
manifest, and staged bundle. Ignore raw build output and machine paths.

## Environment variables

Machine-local paths never go in the TOML. The pipeline reads these, and no
`.local.env` or other dotenv file — export them in the shell or the CI job:

| Variable | Meaning |
|---|---|
| `SEVEN_DAYS_TO_DIE_DIR` | the installed client, containing `Data/Config/items.xml`; read-only evidence |
| `UNITY_EDITOR` | the game-matched editor executable |
| `SEVEN_DAYS_TO_DIE_LOG_DIR` | overrides where `shamway client` looks for `output_log_client__*.txt` (derived from the game dir's Steam library on Proton hosts otherwise) |
| `SEVEN_DAYS_TO_DIE_MODS_DIR` | overrides the per-user `Mods/` folder `shamway client deploy` writes to |
