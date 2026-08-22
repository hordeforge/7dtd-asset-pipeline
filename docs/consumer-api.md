# Consumer interfaces

Three ways to drive this pipeline from your own mod repository, in the order
most consumers should reach for them.

## 1. What `init` puts in your mod

`7dtd-assets init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR"` writes:

```text
MyMod/
├── .7dtd-assets.toml                   # configuration; commit it
├── Makefile.assets                     # make -f Makefile.assets assets
└── tools/7dtd-assets/
    ├── AGENTS.md                       # the agent contract, in your repo
    ├── manifests/                      # tracked build membership
    └── UnityProject/                   # the Unity project your mod owns
```

Nothing here points back at a checkout of this repository, so the mod stays a
standalone repo. `init` refuses to overwrite any of those files.

`tools/7dtd-assets/AGENTS.md` is the interface for coding agents: it names the
mod's bundle, the commands and their costs, the rules that cause silent
breakage when ignored, and the URI form. Point your repository's own
`AGENTS.md`/`CLAUDE.md` at it:

```markdown
For asset-bundle work, follow @tools/7dtd-assets/AGENTS.md.
```

## 2. The CLI contract

Every command exits `0` on success and non-zero on failure, printing one
`ERROR: ...` line to stderr. Prefer exit codes over parsing prose.

| Command | Network | Unity | Writes | Purpose |
|---|---|---|---|---|
| `status [--json]` | no | no | no | whole-mod state; exit 1 if invalid |
| `doctor [--json]` | no | runs `-version` | no | host readiness; exit 1 on any `FAIL` |
| `refs` | no | no | no | every bundle URI under `Config/` |
| `inspect [--json] PATH` | no | no | no | one bundle's revision and class IDs |
| `check-log PATH` | no | no | no | reject a Unity disabled-module log |
| `validate [--bundle PATH]` | no | no | no | bundle + all XML references |
| `build --probe` | no | yes | no | prove the environment; stages nothing |
| `build` | no | yes | **yes** | build, gate, stage bundle + manifest |
| `init MOD_ROOT` | no | no | **yes** | scaffold into a modlet |
| `unity-release [--json]` | **yes** | no | no | official editor URL/changeset/MD5 |

`build` is the only command that writes into the modlet, and only after every
offline gate passes.

### `status --json`

The orientation call. It never raises for a mod-state problem; problems are
collected into the structure so one broken thing does not hide the rest.

```json
{
  "mod_name": "MyMod",
  "bundle_path": "/path/to/MyMod/Resources/mymod.unity3d",
  "bundle_present": true,
  "bundle_unity_version": "2022.3.62f2",
  "bundle_has_assetbundle_object": true,
  "game_unity_version": "2022.3.62f2",
  "version_matches_game": true,
  "asset_count": 3,
  "assets": ["Assets/ModAssets/Bundle/myModThing.prefab"],
  "reference_count": 1,
  "references": [
    {"source": "…/Config/blocks.xml", "uri": "#@modfolder(MyMod):…",
     "mod_name": "MyMod", "bundle_path": "Resources/mymod.unity3d",
     "asset_stem": "myModThing"}
  ],
  "valid": true,
  "problems": []
}
```

`doctor --json` emits `[{"status": "OK"|"WARN"|"INFO"|"FAIL", "name": …,
"detail": …}]`. `inspect --json` emits `path`, `unity_version`,
`archive_format`, `class_ids`, `has_assetbundle_object`.

## 3. The Python API

For consumers scripting the pipeline in-process. Only the names re-exported
from the package root are supported; everything else may change.

```python
from sevendtd_asset_pipeline import (
    PipelineError, collect_status, load_config, run_build, validate_mod,
)

config = load_config()               # finds .7dtd-assets.toml upward from cwd
status = collect_status(config)      # never raises for a mod-state problem
if not status.valid:
    for problem in status.problems:
        print(problem)

try:
    bundle = run_build(config)       # returns the staged bundle path
    report = validate_mod(config)
except PipelineError as exc:
    ...                              # one user-actionable message
```

| Name | Use |
|---|---|
| `load_config(path=None)` | resolve `.7dtd-assets.toml` into a `PipelineConfig` |
| `collect_status(config)` | `Status`; the non-raising orientation call |
| `run_doctor(config)` / `failed(checks)` | `list[Check]` and its verdict |
| `run_build(config, probe=False)` | build, gate, stage; returns the bundle path |
| `validate_mod(config)` | `ValidationReport` over bundle and XML |
| `validate_bundle(path, expected_version=None)` | one bundle's gates |
| `inspect_bundle(path)` | `BundleInfo` without any gate |
| `discover_references(config_dir)` | `list[AssetReference]` |
| `manifest_assets(path)` | membership from a tracked manifest |
| `game_unity_version(game_dir)` | `(revision, evidence_path)` |
| `fetch_release(version)` | official editor download for a revision |
| `initialize(root, mod_name, bundle_name, version)` | scaffold |

## Continuous integration

The offline half needs no Unity, no game install, and no network, so it runs
on any hosted runner as a pull-request gate:

```yaml
- run: pipx install 7dtd-asset-pipeline
- run: 7dtd-assets status --json
- run: 7dtd-assets validate
```

`status`/`validate` catch the review-time failures — a bundle committed without
its manifest, an XML reference to an asset nobody built, a case mismatch, a
stem collision. Keep `build` on an authoring host with a licensed Unity; it is
not a CI step.
