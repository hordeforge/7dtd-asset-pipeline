# Agent instructions

This repository is the reusable asset pipeline for 7 Days to Die modlets. It
is designed to be driven by coding agents, so these rules are the contract.
Read them before inspecting, planning, editing, or testing anything here.

## What this repository is

`7dtd-assets` turns editable Unity assets into a validated
`Resources/<name>.unity3d` inside a standalone modlet, and fails loudly on the
silent-corruption modes a plain successful Unity build does not catch. It owns
tooling only. It owns no art, no mod, and no game install.

Read [README.md](README.md) and the relevant page under [docs/](docs/) before
changing behavior. [docs/architecture.md](docs/architecture.md) explains the
trust boundaries; [docs/research-provenance.md](docs/research-provenance.md)
records where each 7DTD-specific rule came from.

## Working on this repository

```bash
scripts/bootstrap        # create .venv and install this checkout
make check test          # compile, shellcheck, and the unit suite
```

`make check test` must pass before you hand work back. It needs no network,
no Unity, and no game install.

- Changes to `unityfs.py` require generated fixtures for **both** acceptance
  and rejection. Never loosen a parser bound to make a real file work without
  first proving what that file actually contains.
- Changes to bundle generation (`build.py`, `BundleBuilder.cs`) require
  `make check test` plus a game-matched `7dtd-assets build --probe` when Unity
  is available on the host.
- New engine facts need a named source: `Data/Config/*.xml` in the installed
  game, `ilspycmd`/`monodis` on `Assembly-CSharp.dll`, or `maci0/7dtd-research`.
  Record which tool produced the fact. "It seemed to work in game" is not a
  source and the next session cannot re-verify it.
- Keep the consumer scaffold standalone. A modlet built with this pipeline
  must never need a relative checkout of this repository, another mod, or a
  sibling project at build time.

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
| fresh-client acceptance | everything an offline parse cannot prove |

The offline gates are necessary, not sufficient. Never describe a bundle as
working, verified, or accepted on offline output alone: acceptance always ends
with a fresh client and a human look or listen at the changed asset.

## Safety rules

- **Never write to a 7 Days to Die install.** It is read-only evidence for the
  Unity revision and engine behavior.
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

```bash
scripts/install-tools.sh --with-unity-prereqs   # host packages
scripts/bootstrap                               # the CLI
7dtd-assets init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
scripts/install-unity-editor.sh --project /path/to/MyMod/tools/7dtd-assets/UnityProject
7dtd-assets doctor && 7dtd-assets build --probe
```

Then, per asset change:

```bash
7dtd-assets build      # build, gate, stage bundle + tracked manifest
7dtd-assets validate   # bundle and every recursive Config/**/*.xml reference
```

Machine-readable output for agents and CI:

| Command | Contract |
|---|---|
| `7dtd-assets doctor --json` | array of `{status, name, detail}`; exit 1 if any `FAIL` |
| `7dtd-assets inspect --json BUNDLE` | revision, archive format, class IDs, class-142 flag |
| `7dtd-assets unity-release --json` | official editor URL, changeset, and MD5 for a revision |
| `7dtd-assets refs` | one `source: uri` line per discovered XML reference |
| `7dtd-assets status --json` | whole-mod state; never raises for a mod-state problem |
| `7dtd-assets capabilities --json` | optional capabilities, what they unlock, install commands |
| `7dtd-assets inspect --deep --json` | every serialized object and per-prefab components |
| `7dtd-assets check-mesh --json` | authored-mesh extents and glTF conformance |

Every command exits non-zero with a single `ERROR: ...` line on stderr when a
gate fails. Prefer the exit code over parsing prose. The full contract, the
JSON shapes, and the supported Python API are in
[docs/consumer-api.md](docs/consumer-api.md).

## Cost and blast radius

Some steps here are expensive or irreversible. Do not start them speculatively
and never in a loop:

- `scripts/install-unity-editor.sh` downloads several gigabytes and needs an
  interactive desktop for license activation.
- `7dtd-assets build` starts a real Unity editor; a cold project import takes
  minutes.
- `7dtd-assets build` (without `--probe`) is the only command that writes into
  the modlet, and only after every offline gate passes. Use `--probe` for any
  environment question — it never stages anything.

Prefer `doctor`, `inspect`, `refs`, and `validate` when diagnosing. They are
fast, read-only, and need neither Unity nor the network.

## Asset authoring

[docs/agent-workflows.md](docs/agent-workflows.md) defines the reproducible
asset-as-code patterns (mesh, texture, icon, audio, VFX lanes) and the evidence
packet a release candidate must carry.
[docs/authoring-tools.md](docs/authoring-tools.md) lists the researched
open-source tools and which gate each one belongs to.

[scripts/generators/](scripts/generators/) ships working generators for the
audio, icon, texture, and mesh lanes, and the scaffolded Unity project ships
`GeneratedAsset.cs` for asset-as-code prefabs and materials. Extend those
rather than starting a new pattern.

There are **two mesh lanes and both are first-class**: an authored mesh from
Blender or OpenSCAD for organic, rigged, or sculpted geometry, and composed
built-in primitives via `GeneratedAsset.Primitive(...)` for hard-surface props.
Pick by what the shape needs, not by what is installed.

Never guess whether an optional tool is present, and never catch `ImportError`
to find out. Ask the registry:

```bash
7dtd-assets capabilities --json
```

```python
from sevendtd_asset_pipeline import has_capability, require_capability
```

Adding an optional dependency means adding it to `capabilities.REGISTRY` with
what it unlocks and its install command, so `doctor`, `status`, the CLI, and
the raised errors all stay in agreement.

Keep generator sources outside the Unity bundle-membership directory; copy only
selected outputs in, so concepts and unused alternatives never ship.
