# 7DTD Asset Pipeline

A reusable, testable pipeline for building Unity asset bundles for **7 Days to
Die mods**. It gives mod authors one path from editable Unity assets to a
staged `Resources/*.unity3d` file, with the failure gates that a normal
successful Unity build does not provide.

The project was extracted from the production asset workflow in Atomic
Doomsday and generalized so it has no dependency on that mod, its art, or its
repository layout.

## What it includes

- host-tooling and Unity-editor installers that start from a bare machine;
- a mod-scaffolding command and generic Unity project template;
- a real editor-side `BuildPipeline.BuildAssetBundles` implementation;
- Windows-target, LZ4, strict, forced-rebuild bundle generation;
- a throwaway probe bundle that tests setup before art is involved;
- build-log rejection when Unity silently strips disabled engine modules;
- dependency-free UnityFS metadata inspection and the required class-142
  `AssetBundle` gate;
- installed-game Unity-version discovery instead of a permanently hardcoded
  version, and checksum-verified editor resolution from Unity's release
  service instead of a hardcoded changeset;
- recursive `Config/**/*.xml` reference discovery;
- validation of mod names, bundle paths, manifest membership, exact case, and
  bundle-wide file-stem uniqueness;
- atomic staging of the bundle and its tracked manifest;
- setup, integration, troubleshooting, authoring, agent-workflow, and release
  documentation, plus an `AGENTS.md` contract for coding agents;
- reproducible generators for the audio, icon, texture, and mesh lanes, plus a
  Unity-side `GeneratedAsset` library for asset-as-code prefabs and materials;
- programmatic interfaces built on one operation registry: a self-describing
  `schema`, a `call` endpoint for any language, a `serve` stdio loop about 17x
  faster for repeated calls, a `Pipeline` Python facade, and a capability
  registry — plus an agent contract written straight into the consuming mod;
- optional OSS capabilities that degrade cleanly: UnityPy object-level bundle
  inspection, and trimesh + the Khronos glTF validator for authored meshes;
- unit tests with generated good and broken UnityFS fixtures.

## Requirements

- [uv](https://docs.astral.sh/uv/) — every Python step runs through it, and
  `scripts/install-tools.sh` installs it;
- Python 3.11 or newer for the pipeline CLI (uv provisions one if needed);
- a legal, activated Unity Editor matching the installed game's own bundle
  revision;
- Unity Windows Build Support (Mono), because the shipped game client loads a
  Windows-target bundle even when it runs through Proton;
- an installed 7 Days to Die client as read-only version authority.

Unity credentials and licenses are never stored in scripts, configuration, or
environment variables by this project.

## Quick start

[Quickstart](docs/quickstart.md) is the complete path from a bare machine to a
validated bundle. The short form:

Install host tooling (`pacman`, `apt-get`, or `dnf`; `--check` installs
nothing and just reports what is missing):

```bash
scripts/install-tools.sh --check --with-authoring --with-unity-prereqs
scripts/install-tools.sh --with-unity-prereqs
```

Install this checkout:

```bash
scripts/bootstrap            # uv venv + uv pip install --editable, with extras
.venv/bin/7dtd-assets --help
```

Or, for a user-wide command, `uv tool install .`.

Scaffold the pipeline into an existing modlet. The command reads the correct
Unity version from the installed game:

```bash
7dtd-assets init /path/to/MyMod \
  --game-dir "/path/to/7 Days To Die"
```

Install the game-matched Unity editor and its mandatory Windows Build Support
(Mono). The revision, changeset, URLs, and checksums come from Unity's official
release service; sign-in and license activation stay user-owned:

```bash
cd /path/to/MyMod
/path/to/7dtd-asset-pipeline/scripts/install-unity-editor.sh
```

Set machine-local paths, then prove the environment:

```bash
export SEVEN_DAYS_TO_DIE_DIR="/path/to/7 Days To Die"
export UNITY_EDITOR="/path/to/Unity/Hub/Editor/VERSION/Editor/Unity"
cd /path/to/MyMod
7dtd-assets doctor
7dtd-assets build --probe
```

Put source assets and their `.meta` files below
`tools/7dtd-assets/UnityProject/Assets/ModAssets/Bundle/`, then build and
validate:

```bash
7dtd-assets build
7dtd-assets validate
```

Orient in an unfamiliar mod, or drive the pipeline from a script or agent, with
one non-raising call:

```bash
7dtd-assets status --json        # whole-mod state
7dtd-assets capabilities --json  # which optional tools work, and what they unlock
7dtd-assets schema               # every operation, machine-readable
7dtd-assets call status          # run one operation, JSON in and out
7dtd-assets serve                # many operations over one stdio session
```

See [Consumer interfaces](docs/consumer-api.md) for the full contract and
[scripts/generators/](scripts/generators/) for the asset-creation lanes.

The offline gates are necessary, not sufficient. Acceptance always ends with
a fresh-client load and a visual/audio check appropriate to the changed asset.

## Documentation

- [Quickstart](docs/quickstart.md) — bare machine to a validated bundle
- [Setup](docs/setup.md) — Python, game path, Unity, licensing, Windows module
- [Bundle generation](docs/bundle-generation.md) — the complete build path
- [Configuration](docs/configuration.md) — every `.7dtd-assets.toml` key
- [Game integration](docs/game-integration.md) — XML URIs, icons, audio, clients
- [Consumer interfaces](docs/consumer-api.md) — schema, call, serve, Python API
- [Blockers](docs/blockers.md) — what still needs a human, a licence, or a client
- [Contributing](CONTRIBUTING.md) — proof boundaries and the uv toolchain
- [Validation](docs/validation.md) — each gate and its proof boundary
- [Authoring tools](docs/authoring-tools.md) — researched OSS tools for humans and agents
- [Agent workflows](docs/agent-workflows.md) — reproducible asset-as-code patterns
- [Troubleshooting](docs/troubleshooting.md) — failure messages and root causes
- [Architecture](docs/architecture.md) — design, boundaries, and trust model
- [Research provenance](docs/research-provenance.md) — where the 7DTD-specific rules came from
- [Release checklist](docs/release-checklist.md) — artifact and live acceptance
- [AGENTS.md](AGENTS.md) — the contract for coding agents working here

See [examples/ExampleMod](examples/ExampleMod) for a minimal consumer layout.

## Scope

This project builds and validates mod-owned asset bundles. It does not replace
Unity as the serializer, ship copyrighted game assets, edit the game install,
automate Unity account credentials, guarantee visual quality, or claim that an
offline parse proves runtime compatibility.

## License

MIT. See [LICENSE](LICENSE).
