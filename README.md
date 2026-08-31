# Shamway (7DTD Asset Pipeline)

## Quick start

Install the host tooling and the CLI. `--check` installs nothing and reports
what is missing; the installer covers `pacman`, `apt-get`, `dnf` and `zypper`:

```bash
scripts/install-tools.sh --check --with-authoring
scripts/install-tools.sh --with-authoring
scripts/bootstrap
export PATH="$PWD/.venv/bin:$PATH"
```

Point two variables at your machine — the installed game, and an existing
modlet folder containing a `ModInfo.xml`:

```bash
export SEVEN_DAYS_TO_DIE_DIR="$HOME/.steam/steam/steamapps/common/7 Days To Die"
export MOD="$HOME/mods/MyMod"
```

Scaffold the pipeline into that modlet. It reads the correct bundle revision
from the installed game — the game is read-only evidence, never a Unity
install — and writes a configuration that needs no editor, because that is the
default:

```bash
shamway init "$MOD" --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
```

Put source files in the `assets-src/bundle/` folder that created, each named
by the stem the game's XML will ask for: images become textures, clips become
`AudioClip`s, `.json`/`.txt`/`.csv` become text assets, and `.glb`/`.obj`/
`.stl` become a **prefab** with its mesh, material and shader — which is what
`Meshfile` and block `Model` load. Compressed and vector formats work too —
`.ogg` and `.mp3` via FFmpeg, `.svg` via ImageMagick — when those are
installed. Then build the bundle and validate the whole mod against it:

```bash
cd "$MOD"
shamway build
shamway validate
```

That is the whole loop, and none of it needed Unity. Everything below is
detail.

`shamway` gets a **7 Days to Die** modlet from source assets to a staged,
validated `Resources/*.unity3d`, and fails loudly on the silent-corruption
modes a successful Unity build does not catch. **Unity is opt-in, not
required**: by default a bundle of textures, sounds, text files, meshes,
materials, shaders and prefabs is written by this tool directly, in
milliseconds, with no editor anywhere.

## Do you need Unity at all?

**No.** Nothing in this pipeline requires a Unity editor, and nothing chooses
one for you: `bundle_source = "synthesized"` is the default, and `"unity"` is
something a mod opts into. The configuration states which of four cases a mod
is in, and `shamway init --bundle-source` sets it:

| `bundle_source` | Where the `.unity3d` comes from | Editor here |
|---|---|---|
| `synthesized` *(default)* | this tool writes it: `shamway build`, seconds | no |
| `none` | nowhere — the mod ships loose XML, icons and CSV | no |
| `external` | an editor on another machine; gated and staged by `shamway stage` | no |
| `unity` *(opt in)* | a local editor: `shamway build` starts it | yes |

The one exception is `shamway init --adopt PROJECT`, which points at a Unity
project a mod already has. Pointing at it *is* the opt-in, so that scaffolds
`"unity"` without repeating it.

The writer covers **`Texture2D`, `AudioClip`, `TextAsset`, `Mesh`,
`Material`** and **`Shader`**, and assembles them into the **prefab** group
(`GameObject` + `Transform` + `MeshFilter` + `MeshRenderer`) that 7DTD's
`Meshfile` and block `Model` actually load. Drop a mesh in the source folder
and you get a prefab under its stem, its mesh, its material, and a shared unlit
textured shader; a texture named `<stem>_albedo` is bound to that material. A
mesh is any file [trimesh](docs/authoring/authoring-tools.md) reads, so
Blender's glTF, OpenSCAD's STL and `shamway generate mesh` all reach a bundle
with no editor between them and it.

The shader is compiled, not borrowed: `vkd3d-compiler` emits the shader-model-4
`DXBC` that a d3d11 sub-program carries, and the writer wraps it in the blob
container decoded out of the game's own bundle. That is the one lane with a
host dependency — without a usable one a mesh is packed as a bare `Mesh` and
`shamway build` prints a note saying so. It needs **vkd3d 1.3 or newer**:
`scripts/install-tools.sh` installs the distribution's package where that is new
enough (Arch 1.19, Fedora 1.17) and builds one where it is not (Debian and
Ubuntu package 1.2):

```bash
scripts/install-tools.sh --with-vkd3d-source
```

What is **not** built yet is lit and transparent shading and keyword variants —
an unlit opaque pass is what ships, and an unlit prop draws at full brightness
at midnight. A Vulkan sub-program rides along when `glslangValidator` and the
SMOL-V encoder are installed, but the client still renders it magenta; only
Metal has none at all. [Improvements](docs/status/improvements.md) tracks both
and [Running without Unity](docs/bundles/no-unity.md) is the full page.

Where an editor *does* exist, it is a checker rather than a builder — this is
the one offline check in the project that the project did not also author:

```bash
shamway verify-bundle
```

## The commands

Diagnose with these first. They are fast, read-only, and need neither Unity,
the network, nor a game install:

| Command | What it answers |
|---|---|
| `shamway status --json` | the whole mod's state; never raises for a mod-state problem |
| `shamway doctor --json` | `{status, name, detail}` rows; exit 1 on any `FAIL` |
| `shamway capabilities --json` | which optional tools work, what each unlocks, how to install it |
| `shamway refs` | one `source: uri` line per XML reference found |
| `shamway inspect BUNDLE --json` | revision, archive format, class IDs, class-142 flag |
| `shamway inspect --deep --json` | every serialized object and per-prefab components |
| `shamway validate` | the staged bundle and every recursive `Config/**/*.xml` reference |

These produce or move the bundle:

| Command | What it does |
|---|---|
| `shamway init MOD` | scaffold the pipeline into an existing modlet |
| `shamway build` | build or synthesize, gate, and stage the bundle with its manifest |
| `shamway build --probe` | prove the environment on a throwaway bundle; stages nothing |
| `shamway pack SRC OUT` | synthesize a bundle outside any mod |
| `shamway stage BUNDLE` | gate and stage a bundle an editor elsewhere built |
| `shamway verify-bundle` | load a bundle in a real Unity runtime; needs an editor, proves construction |
| `shamway unity-release --json` | the official editor URL, changeset and MD5 for a revision |

One check is advisory, networked by explicit consent, and writes evidence
beside the asset rather than into the modlet:

| Command | What it does |
|---|---|
| `shamway review-audio CLIP --intent F` | a configured audio model critiques the clip's actual bytes under its recorded intent; refuses without `--allow-network`, and never replaces the human listen |
| `shamway review-video STEM --clip DIR --intent F` | a configured vision model critiques an adopted motion clip through the deadeye gateway; refuses without `--allow-network`, and never replaces the human look |

`build` (without `--probe`), `stage` and `render-icon` are the only commands
that write into the modlet, and the first two only after every offline gate
passes. Each exits non-zero with a single `ERROR: ...` line on stderr when a
gate fails — prefer the exit code over parsing prose.

## Authoring an asset

The generators, the prompts and the documentation ship **inside the installed
package**, so a mod calls them without a checkout of this repository or any
relative path:

```bash
shamway generate --list
shamway prompt --list
shamway docs art-direction
```

Get the house-style prompt for what you are making — it arrives with the key
colour, the negative list, and the commands that consume the model's output:

```bash
shamway prompt item-icon --subject "a squat charcoal welded-steel control box" --stem myModThing
```

Generate the asset, then gate its lane before it goes anywhere:

```bash
shamway generate sound blast assets-src/audio/blast.wav --seed 7
shamway generate sound nuclear-blast assets-src/audio/nuclear.wav --seed 7
shamway generate sound bomb-whistle assets-src/audio/falling.wav --seed 7 --seconds 4
shamway generate mesh assets-src/bundle/myModThing.glb --shape cylinder --size 0.19 0.19 0.42
shamway generate cutout key assets-src/icons/thing-src.png UIAtlases/ItemIconAtlas/myModThing.png --size 160 --pad 0.9 --trim
shamway generate rig armature.glb
shamway generate rig bear.glb --rig quadruped-large
shamway generate entity myCreature.glb --mod MyMod --bundle myMod --xml myCreature-entityclasses.xml
shamway generate entity myRaptor.glb --rig dinosaur --scale 0.7 --mod MyMod --bundle myMod
shamway generate entity myCreature.glb --rig quadruped --anim idle,head,walk --mod MyMod --bundle myMod
shamway generate creature myRaptor.glb --rig dinosaur --coat olive --mod MyMod --bundle myMod --xml myRaptor-entityclasses.xml
```

```bash
shamway check-sound assets-src/audio/blast.wav
shamway check-mesh assets-src/bundle/myModThing.glb
shamway check-icons
```

When the icon should *be* the item, photograph it. With an editor that is the
bundle prefab, materials and all; with no editor it is the mesh file, rendered
by headless Blender as a clay render:

```bash
shamway render-icon myModThing
```

```bash
shamway generate mesh-icon assets-src/bundle/myModThing.glb UIAtlases/ItemIconAtlas/myModThing.png
```

Never guess whether an optional tool is installed. Ask the registry, which is
the same source `doctor`, `status` and every raised error read from:

```bash
shamway capabilities --json
```

## Proving it works

The offline gates are necessary, not sufficient. Acceptance always ends with a
fresh client and a human look or listen at the changed asset.

The mechanical half is automated. `shamway acceptance-provider` generates a
scenario provider for [7dtd-playtest](https://github.com/hordeforge/7dtd-playtest)
with one case per manifest entry, each loading its asset through the game's own
`DataLoader.LoadAsset<T>` inside a live client:

```bash
shamway acceptance-provider --harness-dll /path/to/7dtd-playtest.dll --install
shamway script playtest-acceptance
```

For **this** repository's synthesized writer, `shamway script
playtest-synthesized` is the live regression (load + block on a voxel +
editorless mechanical). A picture of one prefab is a second invocation:
`playtest-synthesized --look` (burst) or `--look STEM`. A walk-entity stem is
engine-spawned; `--prefab-look STEM` is its raw-prefab diagnostic control, and
`--trace-entity` adds per-second pose/render/collision evidence. Load is not
look.

A bare launch proves the mod loads, not that anything read the bundle. It
refuses to start over a client that is already running, because a reused
process proves nothing about a rebuild:

```bash
shamway client deploy .
shamway client launch --mod-name MyMod --run-seconds 120 --mute
shamway client log --json
```

The looking half is a person, every time — a texture that loads upside down
and a clip at the wrong pitch pass every case above. What the pipeline can do
is make the judgement citable: record the frame it was made on, next to the
observable the reviewer was asked to check.

```bash
shamway client capture held-nuke --wait 5 --observable "held upright like a grenade, not sunk into the hand"
shamway client capture --list
```

Between the mechanical half and the person sits one advisory check.
`shamway review-audio` auditions an authored clip's actual bytes against its
recorded intended-use context with a configured audio model, and returns
structured criticism with a hash-addressed evidence document. It uploads an
authored asset to a third party, so it refuses without explicit consent, and
its verdict is evidence for the human listen — never a substitute for one:

```bash
shamway review-audio assets-src/audio/blast.wav \
    --intent assets-src/audio/blast.review.json --allow-network --json
```

The contract is [PRD 0001](docs/prds/0001-contextual-model-audio-review.md),
served as `shamway docs model-audio-review`.

The sight twin is `shamway review-video`: it critiques an adopted motion clip
(frames or a muxed video, captured by a `CaseDef.StagedClip` case and adopted
with `shamway client capture --clip`) against its recorded intent through the
**deadeye** gateway (`hordeforge/7dtd-vision-review`), the shared vision-model
review component. The same advisory posture applies — the verdict is evidence
for the human look, never a substitute:

```bash
shamway client capture thing --clip .local/capture/demo-20260825/thing \
    --observable "grip reads at the right thickness through a full turn"
shamway review-video thing --clip .local/acceptance/thing \
    --intent assets-src/bundle/thing.review.json --allow-network
```

The contract is [PRD 0002](docs/prds/0002-video-based-asset-review.md),
served as `shamway docs model-video-review`, and the authoring lane is
`shamway docs video`.

## Driving it from code or an agent

Do not hardcode the command surface. It is published, and each operation
declares its `cost`, whether it `writes`, whether it `needs_config`, and which
`capabilities` it needs — so a caller can decide what is safe to run before
running it:

```bash
shamway schema
shamway call status
shamway serve
```

`serve` runs many operations over one stdio session, about 17x faster than
repeated process starts, and refuses writing operations unless started with
`--allow-writes`.

In Python, use the facade rather than assembling the individual functions:

```python
from sevendtd_asset_pipeline import Pipeline

pipeline = Pipeline.discover()
```

The full contract and JSON shapes are in
[Consumer interfaces](docs/consumer-api.md). `shamway init` also writes an
`AGENTS.md` into the mod, so an agent arriving in a consuming repository finds
the rules there rather than here.

## What it includes

**Bundle production**

- an **editorless writer** (`bundle_writer.py`), which is the default path:
  UnityFS container, SerializedFile v22 with the engine's own per-revision type
  trees, the class-142 `AssetBundle` object, `Texture2D` (RGBA32 or BC1/BC3),
  `TextAsset`, `AudioClip` as PCM16 in a hand-written FSB5 bank, `Mesh` from
  any interchange file, a `Shader` whose `DXBC` sub-programs are compiled by
  `vkd3d-compiler`, a `Material` binding them, and the `GameObject` prefab with
  its `Transform`, `MeshFilter` and `MeshRenderer` that the game actually
  resolves — every structure read out of a real artifact first, and
  cross-object `PPtr`s resolved by name so a dangling reference is refused
  rather than written as null;
- an **opt-in** editor-side `BuildPipeline.BuildAssetBundles` implementation
  for the bundle that needs one — Windows-target, LZ4, strict, forced-rebuild;
- four bundle sources, three of them editorless — synthesized here by default,
  built elsewhere and staged, no bundle at all, or a local editor — with the
  gates travelling with the artifact in every case, and a CI job that proves
  the default one on a runner that has never had an editor;
- a throwaway probe bundle that tests setup before art is involved;
- atomic staging of the bundle and its tracked manifest, so a rejected
  candidate never replaces what is already in `Resources/`;
- `shamway verify-bundle`, which loads a bundle in a real Unity runtime with
  the engine's own loader — the inversion that makes an editor a verifier
  instead of a builder.

**Gates**

- dependency-free UnityFS metadata inspection and the required class-142
  `AssetBundle` gate;
- build-log rejection when Unity silently strips disabled engine modules;
- installed-game Unity-version discovery instead of a hardcoded version, and
  checksum-verified editor resolution from Unity's release service instead of
  a hardcoded changeset;
- recursive `Config/**/*.xml` reference discovery, covering models, item
  meshes and `sounds.xml` clips alike, plus a declared list of code-loaded
  stems (`code_references`) so assets no XML names are validated too;
- validation of mod names, bundle paths, manifest membership, exact case, and
  bundle-wide file-stem uniqueness;
- offline gates for what a bundle check cannot see: atlas icons against every
  `CustomIcon` key, and clips against format, level, clipping and DC offset;
- a `not run:` line for every gate whose evidence did not arrive — an unrun
  gate reads exactly like a passed one.

**Authoring**

- reproducible generators for the sound, audio-conversion, icon, cutout,
  texture, mesh and mesh-icon lanes, plus a Unity-side `GeneratedAsset`
  library for asset-as-code prefabs, materials, texture imports, particle
  blend state and audio;
- an editor-side icon renderer and a headless-Blender counterpart, so an icon
  that should *be* the item cannot drift from the mesh, with or without Unity;
- an art-direction contract with prompt patterns, and `shamway prompt`, which
  renders them as a ready prompt with the key colour, the negative list and
  the commands that consume the model's output;
- optional OSS capabilities that degrade cleanly: UnityPy object-level
  inspection, trimesh and the Khronos glTF validator for meshes, Blender for
  geometry and icon renders.

**Interfaces**

- one operation registry behind a self-describing `schema`, a `call` endpoint
  for any language, a `serve` stdio loop, a `Pipeline` Python facade, and a
  capability registry — plus an agent contract written into the consuming mod;
- generators, documentation and host scripts served from the installed package
  (`shamway generate`, `shamway docs`, `shamway script`), so a consuming mod
  owns only its own content and never a path into this repository.

**Acceptance**

- fresh-client plumbing (`shamway client`): where a Proton client loads mods
  from and logs to, an allow-listed deploy, a launch that refuses a running
  client, an OS-layer mute, and a log classifier that knows every positive
  line and every silent-failure signature this project has met;
- `shamway acceptance-provider`, which generates in-client cases that load
  every bundle member through the game's own `DataLoader`;
- `shamway client capture`, which files the frame a visual sign-off was made
  on next to the observable it was checked against.

**Project**

- a host-tooling installer that starts from a bare machine, and an *optional*
  Unity-editor installer beside it;
- a mod-scaffolding command, and an opt-in Unity project template it copies
  only when a mod asks for one;
- an editor-script compile gate that needs no running editor
  (`scripts/compile-editor-scripts.sh`, in `make check`);
- unit tests with generated good and broken UnityFS fixtures, and a CI job
  that scaffolds, builds and validates a real mod with no editor on the host.

## Requirements

- [uv](https://docs.astral.sh/uv/) — every Python step runs through it, and
  `scripts/install-tools.sh` installs it;
- Python 3.11 or newer for the pipeline CLI (uv provisions one if needed);
- an installed 7 Days to Die client as read-only version authority.

For a user-wide command with every optional lane instead of a checkout:
`uv tool install '.[all]'` from a clone, or
`uv tool install '7dtd-asset-pipeline[all] @ git+https://github.com/hordeforge/7dtd-asset-pipeline'`.

Nothing above is Unity. The editorless writer covers every asset class this
pipeline knows, so a full mod builds, gates, stages and validates on a machine
that has never had an editor installed. One optional host package unlocks the
prefab lane; `scripts/install-tools.sh` installs it, and `shamway capabilities
--missing` prints the line for your distribution:

- `vkd3d-compiler` **1.3 or newer** (WineHQ, OSS) — compiles the shader a
  prefab's material needs. Debian and Ubuntu package 1.2, which cannot read
  HLSL; `shamway capabilities` probes what the binary actually supports rather
  than whether it exists, and `install-tools.sh --with-vkd3d-source` builds one
  on any distribution. Without a usable one a mesh is packed as a bare `Mesh`
  and `build` says which it wrote.

**Opt in** to a Unity editor only for `bundle_source = "unity"`, or to use
`verify-bundle` and `render-icon`, and then only on the machine that runs them
(see [Running without Unity](docs/bundles/no-unity.md)):

- a legal, activated Unity Editor matching the installed game's own bundle
  revision;
- Unity Windows Build Support (Mono), because the shipped game client loads a
  Windows-target bundle even when it runs through Proton.

Unity credentials and licenses are never stored in scripts, configuration, or
environment variables by this project.

## Documentation

Every page is also served from the installed package with `shamway docs`, so a
consuming mod reads them with no checkout of this repository, and
`shamway docs index` prints the categorized index below from there.

**Start here**

- [Documentation index](docs/README.md) — every page, by category
- [Quickstart](docs/getting-started/quickstart.md) — bare machine to a validated bundle
- [Setup](docs/getting-started/setup.md) — Python, game path, and the optional Unity, licensing and Windows module
- [Mod repo layout](docs/mod-repo-layout.md) — what lives in the mod, what lives here

**Bundles**

- [Running without Unity](docs/bundles/no-unity.md) — synthesizing here, building elsewhere, shipping none
- [ADR 0001: synthesize bundles without an editor](docs/adrs/0001-synthesize-bundles-without-an-editor.md) — the format research, what shipped, and what is still unbuilt
- [Bundle generation](docs/bundles/bundle-generation.md) — the opt-in editor build path, end to end
- [Validation](docs/validation.md) — each gate and its proof boundary
- [Game integration](docs/game-integration.md) — XML URIs, icons, audio, clients

**Authoring**

- [Art direction](docs/authoring/art-direction.md) — the house style, prompt patterns, and the icon lanes
- [Agent workflows](docs/authoring/agent-workflows.md) — reproducible asset-as-code patterns
- [Authoring tools](docs/authoring/authoring-tools.md) — the researched OSS toolchain and which gate each belongs to
- [ADR 0006: icons from the mesh with Blender](docs/adrs/0006-render-icons-from-the-mesh-with-blender.md) — the editorless icon lane and its honest downside
- [Sound](docs/authoring/audio.md) — synthesis, `sounds.xml`, and why a loaded clip can be silent
- [Visual effects](docs/authoring/vfx.md) — `.vfx` graphs, `particle-card`,
  `shape.position`, how to `--look`, budgets, and the two silent material
  failures
- [Environment effects](docs/authoring/environment-effects.md) — weather, fog and light: the effect the bundle cannot carry

**Reference**

- [Consumer interfaces](docs/consumer-api.md) — schema, call, serve, Python API
- [Configuration](docs/configuration.md) — every `.shamway.toml` key
- [Architecture](docs/architecture.md) — design, boundaries, and trust model
- [Research provenance](docs/research/research-provenance.md) — where each 7DTD rule came from
- [Sibling repositories](docs/sibling-repos.md) — the other twelve HordeForge projects

**Status and process**

- [Troubleshooting](docs/runbooks/troubleshooting.md) — failure messages and root causes
- [Release checklist](docs/runbooks/release-checklist.md) — artifact and live acceptance
- [Blockers](docs/status/blockers.md) — what still needs a human, a licence, or a client
- [Improvements](docs/status/improvements.md) — known gaps and the tool that closes each
- [TODO.md](TODO.md) — the order the open blockers and gaps come in, and who can close each
- [AGENTS.md](AGENTS.md) — the contract for coding agents working here
- [Contributing](CONTRIBUTING.md) — proof boundaries and the uv toolchain

See [examples/ExampleMod](examples/ExampleMod) for a minimal consumer layout.

## Scope

This project synthesizes, builds and validates mod-owned asset bundles. Its
shader lane emits an unlit opaque mesh pass and transparent/additive
particle passes per platform — Direct3D 11 and OpenGL Core that render, plus
an optional Vulkan one the client does not accept yet; lit, cut-out,
normal-mapped and keyword-complete shading are unbuilt — a gap with a known
route, not a claim about what is possible. Named glTF hierarchies,
SkinnedMeshRenderer and ParticleSystem graphs are synthesized without an
editor. It does not ship copyrighted game
assets, edit the game install, automate Unity account credentials, guarantee
visual quality, or claim that an offline parse proves runtime compatibility.

## License

MIT. See [LICENSE](LICENSE).
