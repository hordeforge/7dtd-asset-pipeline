# Consumer interfaces

Ways to drive this pipeline from your own mod repository, in the order most
consumers should reach for them.

Everything below is generated from **one operation registry**
(`operations.py`). The Python facade, the `call` and `serve` endpoints, and the
published `schema` all dispatch through it, so they cannot describe different
behaviour from what they run.

## Which interface

| You are | Use |
|---|---|
| writing Python | `Pipeline` — one object, typed results |
| writing a shell script or CI job | `shamway <command>` with `--json` |
| writing another language, or a tool | `shamway call NAME --params '{...}'` |
| making many calls, or building a wrapper | `shamway serve` |
| discovering what exists, from anything | `shamway schema` |

### Why not a server

This is a local build tool: it reads a game install and drives a Unity editor
on the same machine. An HTTP or RPC server would add a network surface, a port,
and a protocol dependency to something whose consumers are scripts, CI jobs,
and agents that can already start a subprocess. `serve` gives the same
efficiency over stdio with no listener and no dependency, and `schema` publishes
enough for anyone to generate a server, an MCP adapter, or a client library in
whatever protocol they actually need. That choice stays with the consumer.

## 0. The machine-readable contract

- `shamway schema` — the full operation manifest, as JSON

```bash
shamway schema
```

Each operation publishes its name, summary, JSON Schema parameters, what it
returns, and three fields a caller needs before running anything:

| Field | Meaning |
|---|---|
| `cost` | `instant`, `fast`, `seconds`, or `minutes` — `minutes` starts Unity |
| `writes` | whether it modifies files; `build`, `init`, `render_icon`, `client_deploy`, and `client_launch` do |
| `needs_config` | whether it must run inside a scaffolded modlet |
| `capabilities` | optional tools it requires, e.g. `["UnityPy"]` |

Discover the surface without parsing help text or prose:

```bash
shamway schema | jq -r '.operations[] | select(.writes | not) | .name'
```

## 1. `call` — one operation, JSON in and out

```bash
shamway call status
shamway call check_mesh --params '{"mesh":"crate.glb","max_extent":4}'
shamway call build --params '{"probe":true}'
```

Prints the result as JSON on success; on failure prints `ERROR: ...` to stderr
and exits non-zero. Unknown operations list the known ones, unknown parameters
list what is accepted, and a missing one is named — so a caller does not have
to guess from a traceback.

## 2. `serve` — many operations, one process

Each `call` pays process start. `serve` pays it once and then answers one JSON
line per JSON line, in order, for as long as stdin stays open. Measured here:
**73 ms per operation via `call`, 4 ms via `serve`** — about 17x.

```text
in:  {"id": 1, "op": "status", "params": {}}
out: {"id": 1, "ok": true, "result": {...}}
out: {"id": 1, "ok": false, "error": {"type": "PipelineError", "message": "..."}}
```

`id` is echoed untouched and may be omitted. `op: "schema"` and `op: "ping"`
are answered over the same channel, so a client can discover and call without a
second mechanism.

Two safety properties worth relying on:

- **Read-only by default.** Operations declaring `writes` are refused unless
  the server was started with `--allow-writes`. A consumer that only inspects
  cannot accidentally start a Unity build.
- **A malformed line cannot desynchronize the session.** It gets an error
  response; the stream stays aligned and the next request is answered normally.

```python
import json, subprocess

server = subprocess.Popen(
    ["shamway", "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
)

def call(op, **params):
    server.stdin.write(json.dumps({"id": 1, "op": op, "params": params}) + "\n")
    server.stdin.flush()
    reply = json.loads(server.stdout.readline())
    if not reply["ok"]:
        raise RuntimeError(reply["error"]["message"])
    return reply["result"]

print(call("status")["valid"])
```

## 1. What `init` puts in your mod

`shamway init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR"` writes:

```text
MyMod/
├── .shamway.toml                   # configuration; commit it
├── Makefile.assets                     # make -f Makefile.assets assets
├── assets-src/                         # editable sources + provenance; never ships
│   └── README.md                       # what each lane holds, what a row must record
└── tools/shamway/
    ├── AGENTS.md                       # the agent contract, in your repo
    ├── manifests/                      # tracked build membership
    └── UnityProject/                   # the Unity project your mod owns
```

Nothing here points back at a checkout of this repository, so the mod stays a
standalone repo. `init` refuses to overwrite any of those files.

`tools/shamway/AGENTS.md` is the interface for coding agents: it names the
mod's bundle, the commands and their costs, the rules that cause silent
breakage when ignored, and the URI form. Point your repository's own
`AGENTS.md`/`CLAUDE.md` at it:

```markdown
For asset-bundle work, follow @tools/shamway/AGENTS.md.
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
| `init MOD_ROOT` | no | no | **yes** | scaffold into a modlet, or `--adopt` its existing Unity project |
| `capabilities [--json]` | no | no | no | optional capabilities and how to install them |
| `inspect --deep [--json]` | no | no | no | every serialized object (needs UnityPy) |
| `check-mesh [--json] FILE` | no | no | no | mesh extents and glTF conformance |
| `check-sound [--json] FILE` | no | no | no | clip format, level, clipping, DC offset |
| `check-icons [--json]` | no | no | no | atlas cells and every `CustomIcon` key |
| `render-icon STEM` | no | yes | **yes** | photograph a prefab into its atlas cell |
| `generate NAME [ARGS]` | no | Blender for `mesh` | **yes** (writes what you ask for) | run a packaged asset generator |
| `docs [TOPIC]` | no | no | no | print packaged documentation |
| `script NAME [ARGS]` | depends | no | host packages | run a packaged host script (install-tools, install-unity-editor, compile-editor-scripts) |
| `client where\|deploy\|launch\|log\|mute\|unmute` | no | no | **deploy/launch** write outside the modlet | fresh-client acceptance plumbing |
| `schema` / `call NAME` / `serve` | no | no | per operation | the machine-readable surface |
| `unity-release [--json]` | **yes** | no | no | official editor URL/changeset/MD5 |

`build` and `render-icon` are the only commands that write into the modlet, and
`build` only after every offline gate passes. `render-icon` needs a **graphics
device** — it never passes `-nographics`, because that combination silently
produces a blank image; run it under `xvfb-run -a` on a headless host.

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

### `capabilities --json`

The pipeline core is dependency-free, so some features are optional. This is
the programmatic interface for asking which are usable **right now**, what each
unlocks, and the exact command to install a missing one. It is the single
source of truth: `doctor`'s capability rows, `status.capabilities`, and the
errors raised by the commands that need one all read from it.

```json
[
  {"name": "UnityPy", "kind": "module", "available": true, "version": "1.25.3",
   "path": null, "purpose": "list every serialized object and per-prefab component…",
   "unlocks": ["shamway inspect --deep"],
   "install": "uv pip install '7dtd-asset-pipeline[inspect]'"}
]
```

`--missing` lists only unavailable ones; `--versions` probes installed
versions. Every command needing a capability fails with a message naming the
capability, what it unlocks, and its install command — never a traceback:

```text
ERROR: shamway inspect --deep needs the optional capability 'UnityPy'
(list every serialized object …). Install it with: uv pip install '…[inspect]'
```

`status --json` carries a `capabilities` map of `{name: available}`, so a
single call answers both "what is the mod's state" and "what can I run".

Install everything at once:

- `uv pip install '7dtd-asset-pipeline[all]'` — UnityPy, Pillow, NumPy, trimesh
- `scripts/install-tools.sh --with-authoring` — Blender, OpenSCAD, glTF validator, …

```bash
uv pip install '7dtd-asset-pipeline[all]'
scripts/install-tools.sh --with-authoring
```

### `inspect --deep --json`

The class-142 gate proves the container; this proves the *contents*. It lists
every serialized object and, per prefab, the component census across the whole
hierarchy — which is how you answer "did my ParticleSystem survive?" after a
stripped-module scare:

```text
atomicdoomsdaynukedetonationvfx (GameObject) name='atomicDoomsdayNukeDetonationVfx'
  [7 objects: ParticleSystem=6, ParticleSystemRenderer=6, Transform=7]
```

`object_name` is the name 7DTD compares against, so a silent fallback mesh
shows up here as a mismatch.

### `check-mesh`

For the authored-mesh lane. Reports extents, watertightness, and geometry
counts (trimesh) plus glTF conformance (Khronos validator), exiting non-zero on
a problem. Its most common catch is a mesh authored in centimetres, which
arrives a hundred times too large.

### `check-sound`

For the audio lane, and dependency-free. Reports channels, sample rate,
duration, peak, RMS, DC offset, clipped samples, and edge silence, exiting
non-zero on a format mistake a listener cannot fix. It runs outside a mod, so
CI can gate a clip before it is ever imported.

### `check-icons`

Icons are the one deployable asset class `validate` cannot see, because
`UIAtlases/<Atlas>/*.png` is packed at runtime and never enters the bundle.
This reports each cell's geometry and alpha, which `CustomIcon` keys this mod
resolves, and which are external — a key the mod does not provide is normal
(vanilla keys) and is reported, never failed. It fails on a cell that is not
square, not the expected size, has no alpha channel, is essentially empty, was
never cut out of its background, or whose case does not match its key.

### `generate` and `docs`

These two are argv-passthrough commands rather than JSON operations, and they
exist so a consuming mod needs nothing from this repository's filesystem:

- `shamway generate --list` — sound, audio, cutout, icon, texture-maps, mesh
- `shamway generate sound --help` — each generator's own options
- `shamway docs` — the topics
- `shamway docs art-direction` — one page, in full

```bash
shamway generate --list
shamway generate sound --help
shamway docs
shamway docs art-direction
```

Both are published in `shamway schema` under `generators` and
`documentation`, so a consumer discovers them from the same document as the
operations. A generator writes exactly the output path it is given; none of
them touches the modlet on its own.

### `render-icon`

Renders a bundle prefab into an atlas cell so the icon cannot drift from the
mesh, supersampled 4x and downscaled with Lanczos. Fails when the render is
under 2% covered, which is what a missing graphics device produces.

`doctor --json` emits `[{"status": "OK"|"WARN"|"INFO"|"FAIL", "name": …,
"detail": …}]`. `inspect --json` emits `path`, `unity_version`,
`archive_format`, `class_ids`, `has_assetbundle_object`.

## `Pipeline` — the Python entry point

For consumers scripting the pipeline in-process. `Pipeline` is the recommended
entry point; the individual functions stay available for callers that want one
piece. Only names re-exported from the package root are supported.

```python
from sevendtd_asset_pipeline import Pipeline

pipeline = Pipeline.discover()            # resolve .shamway.toml upward
pipeline, created = Pipeline.scaffold(    # or create one in an existing modlet
    "/path/to/MyMod", game_dir="/path/to/7 Days To Die"
)

status = pipeline.status()                # never raises for a mod-state problem
if not status.valid:
    pipeline.build()
    pipeline.validate()

pipeline.call("inspect_deep")             # same dispatch as `call` and `serve`
```

| Method | Returns |
|---|---|
| `Pipeline.discover(start=None)` | a pipeline bound to the nearest config |
| `Pipeline.scaffold(root, *, game_dir=…, unity_version=…)` | `(pipeline, created_paths)` |
| `.status()` | `Status` |
| `.doctor()` | `list[Check]` |
| `.capabilities(probe_versions=False)` | `list[Capability]` |
| `.refs()` | `list[AssetReference]` |
| `.inspect(bundle=None)` | `BundleInfo` |
| `.inspect_deep(bundle=None)` | `DeepReport` (needs UnityPy) |
| `.validate(bundle=None)` | `ValidationReport` |
| `.check_mesh(path, max_extent, strict)` | `MeshReport` (needs trimesh) |
| `.check_sound(path, max_seconds, require_mono)` | `SoundReport` |
| `.check_icons(atlas_root, cell)` | `IconReport` |
| `.render_icon(prefab, output=None, size=160, …)` | `RenderResult` (needs Unity + Pillow) |
| `.check_log(path)` | raises if the log shows stripped modules |
| `.unity_release(version=None)` | `Release` (uses the network) |
| `.build(probe=False)` | staged bundle `Path` |
| `.client_where(game_dir=None)` | the client's per-user paths, as a dict |
| `.client_deploy(mods_dir=None, mod_name=None, replace=True)` | `{destination, copied}` (writes outside the modlet) |
| `.client_launch(run_seconds=None, mute=False, mod_name=None, …)` | `AcceptanceRun` (starts a real client) |
| `.client_log(path=None, log_dir=None, mod_name=None)` | `LogReport` |
| `.call(name, params)` | the registry operation, JSON-shaped |

### The underlying functions

```python
from sevendtd_asset_pipeline import (
    PipelineError, collect_status, deep_inspect, has_capability,
    load_config, run_build, validate_mod,
)

config = load_config()               # finds .shamway.toml upward from cwd
status = collect_status(config)      # never raises for a mod-state problem
if not status.valid:
    for problem in status.problems:
        print(problem)

try:
    bundle = run_build(config)       # returns the staged bundle path
    report = validate_mod(config)
except PipelineError as exc:
    ...                              # one user-actionable message

# Branch on an optional capability instead of guessing or catching ImportError
if has_capability("UnityPy"):
    for entry in deep_inspect(config.bundle_output).entries:
        print(entry.asset_stem, entry.components)
```

| Name | Use |
|---|---|
| `load_config(path=None)` | resolve `.shamway.toml` into a `PipelineConfig` |
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
| `capabilities(probe_versions=False)` | `list[Capability]`: availability, purpose, install |
| `has_capability(name)` / `require_capability(name)` | branch on, or demand, a capability |
| `deep_inspect(path)` | `DeepReport`: objects and per-prefab components |
| `check_mesh(path, max_extent, strict)` | `MeshReport` for an authored mesh |
| `check_sound(path, max_seconds, require_mono)` | `SoundReport` for a clip |
| `check_icons(mod_root, config_dir, atlas_root, cell)` | `IconReport` for the atlas |

## Continuous integration

The offline half needs no Unity, no game install, and no network, so it runs
on any hosted runner as a pull-request gate:

```yaml
- run: uv tool install '7dtd-asset-pipeline[all] @ git+https://github.com/ywy50/7dtd-asset-pipeline'
- run: shamway status --json
- run: shamway validate
```

`status`/`validate` catch the review-time failures — a bundle committed without
its manifest, an XML reference to an asset nobody built, a case mismatch, a
stem collision. Keep `build` on an authoring host with a licensed Unity; it is
not a CI step.
