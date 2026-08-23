# Agent instructions

This repository is the reusable asset pipeline for 7 Days to Die modlets. It
is designed to be driven by coding agents, so these rules are the contract.
Read them before inspecting, planning, editing, or testing anything here.

## What this repository is

`shamway` turns editable Unity assets into a validated
`Resources/<name>.unity3d` inside a standalone modlet, and fails loudly on the
silent-corruption modes a plain successful Unity build does not catch. It owns
tooling only. It owns no art, no mod, and no game install.

Read [README.md](README.md) and the relevant page under [docs/](docs/) before
changing behavior. [docs/architecture.md](docs/architecture.md) explains the
trust boundaries; [docs/research-provenance.md](docs/research-provenance.md)
records where each 7DTD-specific rule came from.

## Working on this repository

- `scripts/bootstrap` — uv venv + uv pip install --editable, with extras
- `make check test` — compile, shellcheck, and the unit suite

```bash
scripts/bootstrap
make check test
```

Use **uv** for every Python step — environments, installs, and runs. Do not
add `pip`, `pipx`, `venv`, or `python -m pip` invocations to scripts, docs, or
CI; `scripts/install-tools.sh` installs uv itself, from the distribution
package or the official checksum-verified release.

`make check test` must pass before you hand work back. It needs no network,
no Unity, and no game install.

- Changes to `unityfs.py` require generated fixtures for **both** acceptance
  and rejection. Never loosen a parser bound to make a real file work without
  first proving what that file actually contains.
- Changes to bundle generation (`build.py`, `BundleBuilder.cs`) require
  `make check test` plus a game-matched `shamway build --probe` when Unity
  is available on the host.
- Changes to the editor-side C# (`GeneratedAsset.cs`, `IconRenderer.cs`,
  `ShamwayPreBuild.cs`, `BundleBuilder.cs`) are not covered by the Python suite.
  `make check` compiles them against the installed editor's assemblies when
  `mcs` and an editor are present (`scripts/compile-editor-scripts.sh`); run
  that, then state plainly which grade the change reached — compiled, probed,
  or executed by an editor — and never describe a compiled-only change as
  verified.
- Those four files are what a consuming mod vendors. Adding a fifth means
  adding it to `scaffold.PIPELINE_EDITOR_SCRIPTS`, or an adopted project silently
  will not get it.
- New engine facts need a named source: `Data/Config/*.xml` (and `XML.txt`)
  in the installed game, `ilspycmd`/`monodis` on `Assembly-CSharp.dll`
  (`scripts/install-tools.sh --with-research` installs them), or
  `maci0/7dtd-research`. Record which tool produced the fact. "It seemed to
  work in game" is not a source and the next session cannot re-verify it; a
  `strings` hit proves a name exists, not a behaviour. Decompiled evidence
  beats a wiki or a monorepo doc: `Localization.csv` was documented in the
  mod root for a year and the engine reads it from `Config/`.
- Keep the consumer scaffold standalone. A modlet built with this pipeline
  must never need a relative checkout of this repository, another mod, or a
  sibling project at build time. That is why the generators and the
  documentation are packaged and reachable as `shamway generate` and
  `shamway docs`: a mod calls them, never copies them. Anything general
  belongs here; anything mod-specific belongs in the mod. See
  [docs/mod-repo-layout.md](docs/mod-repo-layout.md).
- Adding a generator means adding it to `generators.GENERATORS`; adding a doc
  page means adding it to `docs.TOPICS`. The tests fail when either drifts, and
  both are published in `shamway schema`.

## Gates you must not weaken

These exist because each one caught a real failure. Removing one needs
stronger evidence than the evidence that introduced it, recorded in
`docs/research-provenance.md`.

| Gate | What it catches |
|---|---|
| class-142 `AssetBundle` object | a container the runtime rejects as incompatible |
| disabled-module log rejection | Unity reporting success while stripping engine classes |
| game-matched Unity revision | an editor that silently produces an unloadable bundle |
| file-stem collision rejection | assets made unreachable by 7DTD's stem-only lookup |
| atlas-cell and `CustomIcon` checks | icons the bundle gates cannot see at all |
| clip format checks | a clip that is stereo, silent, clipping, or DC-offset |
| fresh-client acceptance | everything an offline parse cannot prove |

The offline gates are necessary, not sufficient. Never describe a bundle as
working, verified, or accepted on offline output alone: acceptance always ends
with a fresh client and a human look or listen at the changed asset.

## Safety rules

- **Never write to a 7 Days to Die install.** It is read-only evidence for the
  Unity revision and engine behavior. The client's per-user data directory
  (`compatdata/251570/pfx/…/AppData/Roaming/7DaysToDie/`) is *not* the
  install: that is where `shamway client deploy` writes, and where a Proton
  client loads mods from.
- **Never launch a client over someone else's.** `shamway client launch`
  refuses while `7DaysToDie.exe` runs; do not work around that. One machine
  has one client, and a reused process proves nothing about a rebuild.
- **Never automate, request, print, log, or commit Unity credentials or
  license data.** Sign-in and activation are user-owned actions.
  `scripts/install-unity-editor.sh` deliberately stops and waits for a human.
- Never commit Unity `Library/`, machine-local paths, copyrighted game assets,
  or third-party assets lacking their license and attribution.
- Commit Unity source assets together with their `.meta` files.
- Do not add `Co-Authored-By` trailers or generated-with tool fluff to commit
  messages or pull-request descriptions.

## Using the pipeline in a mod

Full walkthrough: [docs/quickstart.md](docs/quickstart.md). The short form:

- `scripts/install-tools.sh --with-unity-prereqs` — host packages
- `scripts/bootstrap` — the CLI

```bash
scripts/install-tools.sh --with-unity-prereqs
scripts/bootstrap
shamway init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
scripts/install-unity-editor.sh --project /path/to/MyMod/tools/shamway/UnityProject
shamway doctor && shamway build --probe
```

Then, per asset change:

- `shamway build` — build, gate, stage bundle + tracked manifest
- `shamway validate` — bundle and every recursive Config/**/*.xml reference

```bash
shamway build
shamway validate
```

Machine-readable output for agents and CI:

| Command | Contract |
|---|---|
| `shamway doctor --json` | array of `{status, name, detail}`; exit 1 if any `FAIL` |
| `shamway inspect --json BUNDLE` | revision, archive format, class IDs, class-142 flag |
| `shamway unity-release --json` | official editor URL, changeset, and MD5 for a revision |
| `shamway refs` | one `source: uri` line per discovered XML reference |
| `shamway status --json` | whole-mod state; never raises for a mod-state problem |
| `shamway capabilities --json` | optional capabilities, what they unlock, install commands |
| `shamway inspect --deep --json` | every serialized object and per-prefab components |
| `shamway check-mesh --json` | authored-mesh extents and glTF conformance |
| `shamway check-sound --json` | clip format, level, clipping, DC offset |
| `shamway check-icons --json` | atlas cells and every `CustomIcon` key |
| `shamway render-icon STEM` | render a prefab into its atlas cell (needs a display) |
| `shamway generate --list` | the packaged asset generators, callable from any mod |
| `shamway docs [TOPIC]` | this repository's documentation, served from the package |
| `shamway script NAME` | the host scripts (install-tools, install-unity-editor, compile-editor-scripts), served from the package |
| `shamway client where --json` | the client's per-user `Mods/` and `logs/` paths |
| `shamway client deploy MOD` | copy the deployable modlet there (writes outside the install only) |
| `shamway client launch --mod-name NAME` | a genuinely fresh client, then its log classified; refuses a running one |
| `shamway client log --json` | classify the newest client log: positive load lines and silent-failure signatures |

Every command exits non-zero with a single `ERROR: ...` line on stderr when a
gate fails. Prefer the exit code over parsing prose.

Do not hardcode the command surface. It is published:

- `shamway schema` — every operation, as JSON
- `shamway call status` — run one, JSON in and out
- `shamway serve` — many, one process, ~17x faster

```bash
shamway schema
shamway call status
shamway serve
```

Each operation declares its `cost`, whether it `writes`, whether it
`needs_config`, and which `capabilities` it needs — so you can decide what is
safe to run before running it. `serve` refuses writing operations unless
started with `--allow-writes`.

In Python, use the `Pipeline` facade rather than assembling the individual
functions:

```python
from sevendtd_asset_pipeline import Pipeline
pipeline = Pipeline.discover()
```

The full contract and JSON shapes are in
[docs/consumer-api.md](docs/consumer-api.md). Adding an operation means adding
it to `operations.OPERATIONS` and `api._DISPATCH`; the tests fail if the two
disagree, which keeps the published schema honest.

## Cost and blast radius

Some steps here are expensive or irreversible. Do not start them speculatively
and never in a loop:

- `scripts/install-unity-editor.sh` downloads several gigabytes and needs an
  interactive desktop for license activation.
- `shamway build` starts a real Unity editor; a cold project import takes
  minutes.
- `shamway build` (without `--probe`) and `render-icon` are the only commands
  that write into the modlet, and `build` only after every offline gate
  passes; `client deploy`/`launch` write outside it, and `schema` marks all
  five writers. Use `--probe` for any
  environment question — it never stages anything.

Prefer `doctor`, `inspect`, `refs`, and `validate` when diagnosing. They are
fast, read-only, and need neither Unity nor the network.

## Asset authoring

[docs/agent-workflows.md](docs/agent-workflows.md) defines the reproducible
asset-as-code patterns (mesh, texture, icon, audio, VFX lanes) and the evidence
packet a release candidate must carry.
[docs/authoring-tools.md](docs/authoring-tools.md) lists the researched
open-source tools and which gate each one belongs to.
[docs/art-direction.md](docs/art-direction.md) is the style contract for
generated and drawn 2D assets — read it before writing any generation prompt.
[docs/audio.md](docs/audio.md) and [docs/vfx.md](docs/vfx.md) own the sound and
particle lanes, including the runtime behaviours that make a correctly built
asset silent or invisible.

`shamway generate` ships working generators for the
sound, audio-conversion, cutout, icon, texture, and mesh lanes, and the
scaffolded Unity project ships `GeneratedAsset.cs` for asset-as-code prefabs,
materials, imports, particles, and audio, plus `IconRenderer.cs`. Extend those
rather than starting a new pattern.

There are **two mesh lanes and both are first-class**: an authored mesh from
Blender or OpenSCAD for organic, rigged, or sculpted geometry, and composed
built-in primitives via `GeneratedAsset.Primitive(...)` for hard-surface props.
Pick by what the shape needs, not by what is installed.

Never guess whether an optional tool is present, and never catch `ImportError`
to find out. Ask the registry:

```bash
shamway capabilities --json
```

```python
from sevendtd_asset_pipeline import has_capability, require_capability
```

Adding an optional dependency means adding it to `capabilities.REGISTRY` with
what it unlocks and its install command, so `doctor`, `status`, the CLI, and
the raised errors all stay in agreement.

Keep generator sources outside the Unity bundle-membership directory; copy only
selected outputs in, so concepts and unused alternatives never ship.
