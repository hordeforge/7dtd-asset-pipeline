# What lives in the mod, and what lives here

Two repositories, one rule: **this one owns the tooling, your mod owns the
content.** Nothing mod-specific belongs here, and nothing generalized needs to
be copied into your mod. A mod never contains a path into a checkout of this
repository — it calls the installed command.

## Quick start

Install the pipeline once, per machine:

```bash
uv tool install '7dtd-asset-pipeline[all] @ git+https://github.com/hordeforge/7dtd-asset-pipeline'
```

The `[all]` extra brings Pillow, NumPy, trimesh, and UnityPy's versioned writer
type trees, which the icon, texture, mesh, and synthesized-writer lanes need;
without it the core still inspects and validates through the base unityz tool,
and `shamway capabilities --missing` prints the exact command to add them.

Scaffold it into a mod that already has a `ModInfo.xml`:

```bash
shamway init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
```

From then on, everything is a command inside the mod:

- `shamway status --json` — where this mod stands
- `shamway generate --list` — the asset generators, ready to call
- `shamway docs` — this repository's documentation

```bash
cd /path/to/MyMod
shamway status --json
shamway generate --list
shamway docs
```

Everything below is detail.

## The split

| This repository owns | Your mod owns |
|---|---|
| the `shamway` command and every gate | the `ModInfo.xml`, `Config/`, and gameplay XML |
| the editorless writer that produces the bundle | the source files in `assets-src/bundle/` it produces it from |
| *(opt-in)* the Unity project template and `BundleBuilder.cs` | *(opt-in)* the assets in `Assets/ModAssets/Bundle/` and their `.meta` files |
| *(opt-in)* `GeneratedAsset.cs` and `IconRenderer.cs` | *(opt-in)* the editor scripts that *use* them to build this mod's prefabs |
| the generators (`shamway generate …`) | the prompts, seeds, commands, and source art in `assets-src/` |
| the art-direction, audio, and VFX contracts | this mod's own art direction, if it narrows them |
| the engine facts, and the gates that encode them | the acceptance evidence for this mod's bundle |
| proof that the **game reads** every bundle member | proof that the asset **works**: scale, orientation, audibility, behaviour |

The test for which side something belongs on: **would a second, unrelated mod
want it verbatim?** A blast synthesizer, yes — it is here. *Your* blast, with
its seed and its design notes, no — that is yours.

### The last row is the one mods get wrong

`shamway acceptance-provider` generates in-client cases from your tracked
manifest and proves the engine loads every member of your bundle. That is as
far as this repository can go, because it knows what is *in* the bundle and
nothing about what any of it is *for*. Every generated case passes on a texture
that loads upside down, a clip at the wrong pitch, a mesh at ten times scale.

So a mod that ships assets **writes its own scenario cases**: a second
`IScenarioProvider` with its own suite id, beside the generated one rather than
edited into it — the generated file is rewritten on every run. Assert what your
content promises: the item is held at the right scale, the block's collider
matches its model, the sound group actually fires and carries, the icon
resolves for the item that names it, the particle system emits and stops. The
generated cases are the precondition; if `load_<stem>` fails, nothing above it
means anything.

And no suite retires the person. Passing every case proves the game read your
bytes and ran your logic, never that the art reads well at inventory scale.
`shamway client capture` is where that judgement gets filed.

## What `init` writes into the mod

By default — no Unity project, because none is needed:

```text
MyMod/
├── ModInfo.xml                          # yours, and required before init runs
├── Config/                              # yours: blocks, items, sounds, recipes
│   └── Localization.csv                 # yours; must be inside Config/
├── Resources/mymod.unity3d              # BUILD OUTPUT — commit it, never edit it
├── UIAtlases/ItemIconAtlas/*.png        # yours: 160 x 160 atlas cells
│
├── .shamway.toml                        # written by init; commit it
├── Makefile.assets                      # written by init; make -f Makefile.assets assets
├── assets-src/                          # written by init; YOURS from then on
│   ├── bundle/                          #   every file here becomes a bundle asset
│   ├── README.md                        #   the provenance contract
│   └── icons/ textures/ meshes/ audio/ vfx/
└── tools/shamway/
    ├── AGENTS.md                        # written by init: the agent contract
    └── manifests/                       # BUILD OUTPUT — commit alongside the bundle
```

With `--bundle-source unity`, one more tree appears, and it is the mod's from
then on:

```text
└── tools/shamway/UnityProject/
    ├── Assets/ModAssets/Bundle/         #   your assets + every .meta file
    ├── Assets/SevenDaysToDieAssetPipeline/Editor/   # pipeline-owned; do not edit
    ├── Packages/manifest.json           #   engine modules — these are BUILD INPUTS
    └── ProjectSettings/ProjectVersion.txt
```

`init` refuses to overwrite any of it, and never touches `Config/`,
`Resources/`, or `UIAtlases/`.

Some of those need a word:

- **`assets-src/bundle/` is the default membership folder.** Every file in it
  becomes one asset named by its stem, and a mesh becomes a prefab with its
  mesh, material and shader. Nothing else in `assets-src/` ships or enters the
  bundle — that is the point of the split.
- **`Resources/` and `manifests/` are build outputs you commit.** They are one
  logical artifact — the bundle and the manifest that records its membership —
  so commit them together, and never hand-edit either.

The rest apply only to a mod that opted into an editor:

- **`Assets/SevenDaysToDieAssetPipeline/Editor/` is pipeline-owned.** It is
  copied in, not linked, so the mod builds standalone — but treat it as
  vendored: an upgrade replaces it. Put *your* editor scripts in a folder of
  your own that calls `GeneratedAsset` helpers, so an upgrade cannot lose them.
- **`Packages/manifest.json` is yours to extend.** Declare a module for every
  component type your assets use; an absent module makes Unity strip those
  classes while still reporting success.
- **`ProjectSettings/ProjectSettings.asset` churns.** Unity rewrites it on
  every experiment (`targetPixelDensity`, `buildNumber`, platform strings).
  Review those hunks and discard the noise deliberately; never bulk-revert
  the project directory, which also discards real `.meta` changes.

### Committing, and what never ships

Commit: `.shamway.toml`, `Makefile.assets`, `assets-src/`, the built bundle,
and its tracked manifest. A mod with a Unity project commits that too,
including every `.meta`.

Do not ship in the released modlet: `.shamway.toml`, `tools/`,
`assets-src/`, `.shamway/`, `.local/`, or a Unity project. The deployable modlet
is `ModInfo.xml`, `Config/` (with `Localization.csv` inside it), `Resources/`, and `UIAtlases/`
— see [game-integration.md](game-integration.md).

Add to the mod's `.gitignore`:

```gitignore
.shamway/
.local/
```

A mod with a Unity project adds its machine-local directories:

```gitignore
tools/shamway/UnityProject/Library/
tools/shamway/UnityProject/Temp/
tools/shamway/UnityProject/Logs/
tools/shamway/UnityProject/UserSettings/
```

`.local/` is where `shamway client capture` writes acceptance screenshots and
their manifest. Whether those belong in git is the mod's call — they are
evidence, and evidence that is only ever local is evidence nobody else can
check — but they are never part of the deployable modlet either way. If you do
commit them, commit them somewhere other than `.local/`.

## The four shapes, and which one you get

`--bundle-source` picks it, and three of the four involve no editor at all:

- **`synthesized`, the default** — the bundle is written by shamway itself. No
  Unity project is created; `source_root` points at `assets-src/bundle/` in the
  mod, and every file there becomes one asset: images (`.png`, `.jpg`, `.tga`,
  `.bmp`, plus `.svg`/`.psd`/`.exr`/`.webp`/`.avif` through ImageMagick), clips
  (`.wav`, plus `.ogg`/`.mp3`/`.flac`/`.aiff`/`.m4a`/`.opus`/`.wma` through
  FFmpeg), text (`.txt`/`.json`/`.csv`), and a mesh (`.glb`, `.gltf`, `.obj`,
  `.stl`, `.ply`) becoming a **prefab** with its mesh, material and an unlit
  textured shader. That last lane needs `vkd3d-compiler`; without it the mesh
  is packed bare and `build` says so.
- **`none`** — the mod ships no bundle at all (XML, loose `UIAtlases/` PNGs, a
  DLL). No Unity project is created, `Makefile.assets` has no build targets,
  and no editor is needed for any part of the mod.
- **`external`** — a Unity project and an editor exist, but on another machine;
  `shamway stage` gates and stages what it built. This host needs no editor.
- **`unity`, opt-in** — a local editor builds it, and the Unity project tree
  above appears. Choose it when the bundle needs shading the writer does not
  author: lit, shadowed, transparent, normal-mapped or multi-pass.

See [no-unity.md](bundles/no-unity.md) for all four in full, and
[improvements.md](status/improvements.md) for what is still unbuilt inside the
shader lane.

## Adopting a mod that already has a Unity project

This is the one place `init` chooses the editor lane for you, because pointing
at a Unity project *is* the choice: `--adopt` scaffolds `bundle_source =
"unity"` without `--bundle-source unity` after it.

A mod with assets already has a Unity project, its own editor scripts, and a
committed bundle. Do **not** scaffold a fresh project and move things into it.
Moving a Unity project means moving every `.meta` with it, and any slip
re-imports each asset under a fresh GUID, silently breaking every prefab
reference — and it forces a bundle rebuild, which invalidates whatever
fresh-client acceptance you had recorded, for a change that produced no new art.

Adopt it in place instead. Every path is configuration:

```bash
shamway init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR" \
    --adopt _meta/unity/MyModAssets \
    --source-root Assets/MyMod/Bundle \
    --manifest-dir _meta/unity/manifests
```

Nothing moves. `init` writes `.shamway.toml` pointing at what you already have,
installs only the pipeline-owned editor scripts into
`<project>/Assets/SevenDaysToDieAssetPipeline/Editor/`, and adds the agent guide
and `assets-src/`. It refuses an adoption that could not build: a directory
with no `Assets/`, a `--source-root` that does not exist in the project, or a
project outside the mod root — the last because a mod that reaches outside
itself to build is not a standalone repository.

Then three changes in the mod:

1. **Delete the mod's own `BundleBuilder`** and let shamway's take over. That
   file is pipeline-owned; a fork of it does not get the gates.
2. **Mark the mod's generators** with `[ShamwayPreBuild]` so they still run
   before the bundle is collected — see
   [bundle-generation.md](bundles/bundle-generation.md). Without this the build
   succeeds and ships whatever the generators produced last time.
3. **Retire the mod's build/validate scripts** in favour of `shamway build`,
   `shamway validate`, `shamway check-icons`, and `shamway check-sound`, and
   point its Makefile targets at those.

Keep everything else: the mod's asset generators, its source art, its prompts
and seeds, and the bundle itself. Those are content.

## Calling the tooling from the mod

Everything generalized is reachable through the one command, from anywhere —
the generators, the documentation, and the host scripts:

```bash
shamway script --list
shamway script install-tools --with-authoring --with-research
```

The editor installer is served the same way, for a mod that opted into one:

```bash
shamway script install-unity-editor --project tools/shamway/UnityProject
```

- `shamway generate --list` — what generators exist
- `shamway generate sound --help` — a generator's own options

```bash
shamway generate --list
shamway generate sound --help
shamway generate sound blast assets-src/audio/blast.wav --seed 7
shamway generate cutout key assets-src/icons/src.png \
    UIAtlases/ItemIconAtlas/myModThing.png --size 160 --pad 0.9 --trim
shamway generate texture-maps assets-src/textures/paint.png \
    --out-dir assets-src/textures/derived --stem myModPaint \
    --also assets-src/bundle
shamway generate mesh assets-src/meshes/crate.glb --shape box --size 1 0.6 0.8
```

The generators live inside the installed package, so this works with no
checkout of this repository and no relative paths. The documentation does too:

- `shamway docs` — the topics
- `shamway docs art-direction` — the style contract, in full
- `shamway docs audio` — the sound lane

```bash
shamway docs
shamway docs art-direction
shamway docs audio
```

That is the answer to "where do I read the rules" for an agent working in a mod
repository: it has the command, so it has the rules.

## Pointing an agent at it

`init` writes `tools/shamway/AGENTS.md` into the mod — the contract for
asset work *in that mod*, naming its bundle, its commands, and the rules whose
violation is silent. Point the mod's own instructions at it, rather than
copying its content:

```markdown
For asset-bundle work, follow @tools/shamway/AGENTS.md.
Generators, prompts and full documentation: `shamway generate --list`, `shamway prompt --list`, `shamway docs`.
```

An agent that starts from those two lines can discover the whole surface
without being told any of it in advance:

- `shamway status --json` — where this mod stands; never raises
- `shamway schema` — every operation, its cost, whether it writes
- `shamway capabilities --json` — which optional tools work, and how to install them
- `shamway docs` — every rule this pipeline knows
- `shamway generate --list` and `shamway prompt --list` — how each asset gets made
- `shamway script --list` — the host installers, served from the package

```bash
shamway status --json
shamway schema
shamway capabilities --json
shamway docs
shamway generate --list
shamway prompt --list
shamway script --list
```

Those seven answer the four questions an agent arriving cold actually has —
what state is this mod in, what may I run, what does it cost, and how is each
asset class made — without a checkout of this repository, a network, or any
content copied into the mod.

## When a mod outgrows a generator

Write your own in `assets-src/`, and keep it there. The packaged generators are
starting points and a reference for the contract — explicit input and output
paths, a recorded seed, printed numbers, atomic writes, no placeholders on
failure, never touching the game install. A mod-specific asset script is
mod-specific content: it belongs in the mod's repository, next to the art it
produces.

If what you wrote turns out to be general — a new lane, a gate, a trap worth
encoding — that is a contribution to this repository, and then every mod gets
it. The dividing line does not move just because the code was written in a mod.

## Multiple mods on one machine

Install the pipeline once; scaffold it into each mod. Each mod carries its own
`.shamway.toml`, its own bundle, its own `assets-src/`, and — only if it opted
into an editor — its own Unity project. The command resolves the configuration
upward from the working directory, so `cd`-ing into a mod is all the context
switching there is.

The shared things are machine-level, configured by `SEVEN_DAYS_TO_DIE_DIR` and
`UNITY_EDITOR`, and never written into any mod's committed files: the game
install, the host tooling, and — for the mods that use one — the Unity editor
install. `SHAMWAY_BUNDLE_SOURCE` belongs to the same layer: it says where *this*
machine gets a bundle from, so one committed configuration works on a build host
with an editor and on a laptop without one.
