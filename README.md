# shamway

A reusable, testable pipeline for building Unity asset bundles for **7 Days to
Die mods**. It gives mod authors one path from editable Unity assets to a
staged `Resources/*.unity3d` file, with the failure gates that a normal
successful Unity build does not provide.

The command is `shamway`, after the game's own food factory — the one visible
production line in 7 Days to Die, and a company that turns questionable inputs
into convincing finished goods. This one refuses to.

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
- recursive `Config/**/*.xml` reference discovery, covering models, item
  meshes, and `sounds.xml` clips alike;
- validation of mod names, bundle paths, manifest membership, exact case, and
  bundle-wide file-stem uniqueness;
- atomic staging of the bundle and its tracked manifest;
- setup, integration, troubleshooting, authoring, agent-workflow, and release
  documentation, plus an `AGENTS.md` contract for coding agents;
- reproducible generators for the sound, icon, cutout, texture, and mesh lanes,
  plus a Unity-side `GeneratedAsset` library for asset-as-code prefabs,
  materials, texture imports, particle blend state, and audio;
- offline gates for the asset classes a bundle check cannot see: atlas icons
  against every `CustomIcon` key, and clips against format, level, and DC
  offset;
- an editor-side icon renderer, so an icon that should *be* the item cannot
  drift from the mesh;
- an art-direction contract with prompt patterns, so generated 2D assets match
  the game rather than merely being clean;
- generators and documentation served from the installed package
  (`shamway generate`, `shamway docs`), so a consuming mod owns only its
  own content and never a path into this repository;
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
.venv/bin/shamway --help
```

Or, for a user-wide command, `uv tool install .`.

Scaffold the pipeline into an existing modlet. The command reads the correct
Unity version from the installed game:

```bash
shamway init /path/to/MyMod \
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
shamway doctor
shamway build --probe
```

Put source assets and their `.meta` files below
`tools/shamway/UnityProject/Assets/ModAssets/Bundle/`, then build and
validate:

```bash
shamway build
shamway validate
```

Author sources in the `assets-src/` tree `init` creates, gate each lane before
importing, and render an icon from the prefab when the icon should be the item.
The generators and the documentation ship **inside the installed package**, so
a mod calls them without a checkout of this repository or any relative path:

```bash
shamway generate --list
shamway generate sound blast assets-src/audio/blast.wav --seed 7
shamway generate cutout key assets-src/icons/thing-src.png \
    UIAtlases/ItemIconAtlas/myModThing.png --size 160 --pad 0.9 --trim
shamway check-sound assets-src/audio/blast.wav
shamway check-icons
shamway render-icon myModThing
shamway docs art-direction
```

Orient in an unfamiliar mod, or drive the pipeline from a script or agent, with
one non-raising call:

```bash
shamway status --json        # whole-mod state
shamway capabilities --json  # which optional tools work, and what they unlock
shamway schema               # every operation, machine-readable
shamway call status          # run one operation, JSON in and out
shamway serve                # many operations over one stdio session
```

See [Mod repo layout](docs/mod-repo-layout.md) for the ownership split between
this repository and a mod, and [Consumer interfaces](docs/consumer-api.md) for
the full programmatic contract.

The offline gates are necessary, not sufficient. Acceptance always ends with
a fresh-client load and a visual/audio check appropriate to the changed asset.

## Documentation

- [Quickstart](docs/quickstart.md) — bare machine to a validated bundle
- [Mod repo layout](docs/mod-repo-layout.md) — what lives in the mod, what lives here
- [Setup](docs/setup.md) — Python, game path, Unity, licensing, Windows module
- [Bundle generation](docs/bundle-generation.md) — the complete build path
- [Configuration](docs/configuration.md) — every `.shamway.toml` key
- [Game integration](docs/game-integration.md) — XML URIs, icons, audio, clients
- [Consumer interfaces](docs/consumer-api.md) — schema, call, serve, Python API
- [Blockers](docs/blockers.md) — what still needs a human, a licence, or a client
- [Contributing](CONTRIBUTING.md) — proof boundaries and the uv toolchain
- [Validation](docs/validation.md) — each gate and its proof boundary
- [Art direction](docs/art-direction.md) — the house style, prompt patterns, and the two icon lanes
- [Sound](docs/audio.md) — synthesis, `sounds.xml`, and why a loaded clip can be silent
- [Visual effects](docs/vfx.md) — budgets, LOD tiers, and the two silent material failures
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
