# Quickstart: bare machine to a validated bundle

This is the complete path from a host with nothing installed to a modlet that
ships a validated asset bundle. Every step states what it costs and how you
know it worked. [Setup](setup.md) explains each choice in more detail.

**No Unity editor appears in this path.** The bundle is written by `shamway`
itself, which is what `shamway init` configures when nothing tells it
otherwise. Step 4 is where an editor would go, and it is optional and marked as
such. Times and sizes below are the realistic case on a Linux host, and without
step 4 nothing here downloads more than a few hundred megabytes.

## 0. What you need before starting

- Linux, macOS, or Windows. The scripted install path is Linux; the CLI itself
  is portable. CI gates on both Linux and macOS (the tests skip what a
  case-insensitive volume cannot express, such as two casings of one name);
  Windows runs the same Python but no CI job exercises it yet.
- An installed 7 Days to Die client. It is the authority for which engine
  revision your bundle must claim, and it is only ever read.

You do **not** need the game running, a server, any mod already made, a Unity
editor, or a Unity account. Those last two appear only in the optional step 4,
for a mod that opts into `bundle_source = "unity"`.

## 1. Host tooling (about a minute)

```bash
git clone https://github.com/hordeforge/7dtd-asset-pipeline
cd 7dtd-asset-pipeline
scripts/install-tools.sh --check --with-authoring
```

`--check` installs nothing; it prints `OK`/`MISS` per tool so you can see what
the host is missing. Then install for real:

- `scripts/install-tools.sh` — the core, including `vkd3d-compiler`
- `scripts/install-tools.sh --with-authoring` — art and inspection tooling
- `scripts/install-tools.sh --with-desktop-capture` — a screenshot tool for step 8
- `scripts/install-tools.sh --with-unity-prereqs` — only for the optional step 4

```bash
scripts/install-tools.sh
scripts/install-tools.sh --with-authoring
scripts/install-tools.sh --with-desktop-capture
```

The base install carries `vkd3d-compiler`, which is what compiles the shader a
prefab's material needs. Without it a mesh still reaches the bundle, as a bare
`Mesh` rather than as a loadable prefab, and `build` prints a note saying so.

`install-tools.sh` installs uv first, since every Python step runs through it.
`--with-authoring` then installs Blender, OpenSCAD, ImageMagick, FFmpeg, the
Khronos glTF validator, and the Python capabilities (UnityPy, Pillow, NumPy,
trimesh). `--with-desktop-capture` installs `grim` or `maim`, which is what
lets step 8's visual sign-off leave a citable frame; skip it on a headless
build host. Blender and the glTF validator fall back to official
checksum-verified builds where the distribution has no package. Check what is
usable at any time with `shamway capabilities --json`.

Supported package managers are `pacman`, `apt-get`, `dnf`, and `zypper`. On
anything else, install the tools `--check` lists by hand; the script refuses to guess
package names rather than installing the wrong thing.

## 2. The pipeline CLI (seconds)

```bash
scripts/bootstrap
.venv/bin/shamway --help
```

`scripts/bootstrap` creates `.venv/` in this checkout and installs the package
into it with uv, including the optional capabilities (`--no-extras` for the
core alone). It never uses `sudo` and does not touch shell startup files. For a
user-wide command instead, use `uv tool install .`.

Put `.venv/bin` on `PATH`, or call `shamway` by its full path in the steps
below.

## 3. Scaffold a modlet (seconds)

Point at the directory containing `Data/Config/items.xml`:

```bash
export SEVEN_DAYS_TO_DIE_DIR="/path/to/7 Days To Die"
shamway init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
```

`MyMod` must already exist and contain `ModInfo.xml`. The command reads the
bundle revision out of a shipped game bundle's header rather than trusting a
wiki page, then writes:

```text
MyMod/
├── .shamway.toml                           # configuration; commit it
├── Makefile.assets                         # assets / assets-probe / ... targets
├── assets-src/                             # editable sources + provenance; never ships
│   ├── bundle/                             # every file here becomes a bundle asset
│   ├── README.md                           # what each lane holds and must record
│   └── icons/ textures/ meshes/ audio/ vfx/
└── tools/shamway/
    └── AGENTS.md                           # the agent contract, in your repo
```

No Unity project, because none is needed: `.shamway.toml` says
`bundle_source = "synthesized"` and `shamway build` writes the `.unity3d`
itself. `--bundle-source none`, `external` or `unity` scaffold the other three
cases. `external` and `unity` both add a Unity project so its source and
settings can be committed; only `unity` opens that project on this machine.
The `external` host receives the artifact through `shamway stage`. See
[no-unity.md](../bundles/no-unity.md) for the four source modes.

It refuses to overwrite any of those if they already exist. Every path is
configurable — see [Configuration](../configuration.md).

## 4. (Optional) A Unity editor (30-60 minutes, several GB)

**Skip this unless you know you need it.** Three of the four bundle sources
need no editor, and one of those three is the default this quickstart uses. An
editor is worth installing for exactly two reasons:

- the bundle needs shading the writer does not author — lit, shadowed,
  transparent, normal-mapped or multi-pass — so `bundle_source = "unity"`
  compiles it;
- you want `shamway verify-bundle`, which loads a synthesized bundle in a real
  runtime. That is a checker, not a builder, and nothing needs it to ship.

Everything else — including a bundle of textures, clips, text files and
unlit props — is finished without one. [no-unity.md](../bundles/no-unity.md) is
the full page, including what `shamway stage` gates and what it cannot.

If one of those two applies:

```bash
cd /path/to/MyMod
/path/to/7dtd-asset-pipeline/scripts/install-unity-editor.sh
```

This resolves the exact editor for the project's revision from Unity's
official release service, so it stays correct as the game updates. It then:

1. installs Unity Hub from Flathub;
2. **stops and waits** for you to sign in and activate a license in Hub —
   this is a user-owned action and is never automated;
3. copies the active license to Unity's native Linux location;
4. downloads and MD5-verifies the editor archive and installs it;
5. downloads and MD5-verifies **Windows Build Support (Mono)** and installs it;
6. proves the editor can open the project in batch mode with that license.

Windows Build Support is not optional: the shipped game client loads a
Windows-target bundle even when it runs through Proton.

If a licensed editor already exists on the host, skip Hub entirely:

```bash
export UNITY_EDITOR="/path/to/Unity/Hub/Editor/2022.3.62f2/Editor/Unity"
scripts/install-unity-editor.sh --skip-hub
```

## 5. Prove the environment before touching art (seconds)

```bash
cd /path/to/MyMod
shamway doctor
shamway build --probe
```

`doctor` checks mod identity, the bundle revision against the installed game,
whether the writer has the type trees it needs, and which optional authoring
tools are usable. It exits non-zero if any check is `FAIL`; `--json` gives
agents and CI the full structured report either way. It reports Unity rows only
for a mod that opted into an editor — an absent editor is not a finding about a
mod that never asked for one.

`build --probe` is the decisive test: it does everything a real build does and
stages nothing. Synthesized, that is milliseconds. Getting it to pass before art
exists is the whole point — a failure here is an environment problem, never an
asset problem.

With `bundle_source = "unity"` the same command means something slower and
larger: export `UNITY_EDITOR`, and Unity creates a throwaway cube prefab, builds
a real Windows bundle from it, the log is checked for stripped engine modules,
the artifact is parsed for a class-142 `AssetBundle` object, and the prefab is
deleted.

```bash
export UNITY_EDITOR="/path/to/Unity/Hub/Editor/<revision>/Editor/Unity"
shamway doctor
shamway build --probe
```

## 6. Add an asset and ship it

Put source files in `assets-src/bundle/`. Each becomes one asset named by its
file stem — an image a `Texture2D`, a clip an `AudioClip`, a `.json`/`.txt`/
`.csv` a `TextAsset`, and a `.glb`/`.obj`/`.stl` a **prefab** with its mesh,
material and shader, which is what a `Meshfile` or a block `Model` loads. A
texture named `<stem>_albedo` is bound to that prefab's material.

Name each one with a mod-prefixed, globally unique stem — 7DTD resolves assets
by file-name stem alone, discarding folder and extension.

With `bundle_source = "unity"` the folder is different and so are the
obligations: source assets go under
`tools/shamway/UnityProject/Assets/ModAssets/Bundle/`, and each one is
committed **with its `.meta` file**, because Unity identity lives there and a
missing `.meta` silently re-imports as a different asset.

- `shamway build` — build, gate, and stage bundle + tracked manifest
- `shamway validate` — bundle plus every reference in Config/**/*.xml

```bash
shamway build
shamway validate
```

Reference it from XML using the mod's `ModInfo.xml` name:

```xml
<property name="Model"
  value="#@modfolder(MyMod):Resources/mymod.unity3d?myModThing.prefab" />
```

`validate` proves the mod name, bundle path, manifest membership, exact case,
and stem uniqueness — for a `Model`, an item `Meshfile`, and a `sounds.xml`
`ClipName` alike. See [Game integration](../game-integration.md) for the URI form
and server behaviour.

Two deployable asset classes are **not** bundle members and have their own
gates:

- `shamway check-icons` — UIAtlases cells + every icon key
- `shamway check-sound assets-src/audio/x.wav` — format, level, clipping, DC offset

```bash
shamway check-icons
shamway check-sound assets-src/audio/x.wav
```

## 7. Driving it from a script or an agent

```bash
shamway status --json
```

- `shamway schema` — every operation, machine-readable
- `shamway call status` — run one operation, JSON in and out
- `shamway serve` — many operations over one stdio session

```bash
shamway schema
shamway call status
shamway serve
```

`status` is one call, no Unity, no network, and it never raises for a
mod-state problem —
it reports what exists, whether the bundle matches the game, what the manifest
lists, which XML references exist, and whether the mod is valid. `init` also
wrote `tools/shamway/AGENTS.md` into your mod so an agent working there has
the rules. See [Consumer interfaces](../consumer-api.md).

## 8. Acceptance

Offline gates are necessary, not sufficient. Finish with a genuinely fresh
client that loads the changed asset by its real URI, and look at or listen to
it. On a Linux host the mechanical half of that is three commands:

```bash
shamway client deploy .
shamway client launch --mod-name MyMod --run-seconds 120 --mute
shamway client log --mod-name MyMod
```

`deploy` copies only the deployable modlet into the folder the Proton client
actually reads (its per-user `Mods/`, not the install); `launch` refuses to
start over a running client, starts one through Steam, and fails unless the
log this launch wrote shows the mod, its atlas, and its localization loaded
with no bundle, name, or particle error; `log` classifies the newest log
again. A listening run is never `--mute`. That proves the asset *loads*. Then
look at it, or listen to it, and say that you did. [Validation](../validation.md)
lists exactly what offline parsing cannot prove; [Release
checklist](../runbooks/release-checklist.md) is the full list.

For a C# mod, point `deploy` at the built dist/release modlet, not its source
root. A source tree with `.cs`/`.csproj` inputs but no root-level DLL is
refused: deploying only its XML and resources produces cascading missing-class
errors while looking superficially successful.

## Creating the assets themselves

`shamway generate` ships reproducible generators for
the sound, audio-conversion, cutout, particle-card, icon, texture, mesh,
mesh-icon, and mesh-optimize lanes, and none of them needs an editor. A mod
that opted into one additionally gets `GeneratedAsset.cs`, for building
prefabs, materials, imports, particle state and audio from code, and
`IconRenderer.cs`, for photographing a prefab into an atlas cell.

```bash
shamway generate sound blast assets-src/audio/blast.wav --seed 7 \
    --promote assets-src/bundle/myModBlast.wav
shamway generate cutout key assets-src/icons/thing-src.png \
    UIAtlases/ItemIconAtlas/myModThing.png --size 160 --pad 0.9 --trim
shamway generate texture-maps detail --out-dir assets-src/textures --stem myModSteel --seed 7
shamway generate mesh assets-src/bundle/myModThing.glb --shape cylinder --size 0.19 0.19 0.42
shamway generate mesh-icon assets-src/bundle/myModThing.glb UIAtlases/ItemIconAtlas/myModThing.png
```

`GeneratedAsset.cs`, `IconRenderer.cs` and `shamway render-icon` belong to the
Unity lane and appear only in a mod that opted into it. `generate mesh` and
`generate mesh-icon` are their editorless counterparts: the first writes
primitives to a `.glb` the writer turns into a prefab, the second photographs
that file in headless Blender and says in its own output that the result is a
clay render rather than the in-game look.

Read these before authoring:

- [Art direction](../authoring/art-direction.md) — the house style and the prompt patterns
  that produce an asset which looks native rather than merely clean;
- [Sound](../authoring/audio.md) — synthesis, `sounds.xml`, and why a loaded clip can be
  silent;
- [Visual effects](../authoring/vfx.md) — budgets, LOD tiers, and two silent material
  failures;
- [Agent workflows](../authoring/agent-workflows.md) — the lane each asset type follows.

## When something fails

- `shamway status --json` — whole-mod state; never raises
- `shamway doctor --json` — structured environment report
- `shamway inspect Resources/mymod.unity3d` — revision, class IDs, class 142
- `shamway refs` — every URI the XML actually uses

```bash
shamway status --json
shamway doctor --json
shamway inspect Resources/mymod.unity3d
shamway refs
```

`check-log` joins that list only for a mod with an editor, because the log it
reads is one an editor wrote:

```bash
shamway check-log .shamway/build/bundle/unity-build.log
```

[Troubleshooting](../runbooks/troubleshooting.md) maps each failure message to its root
cause. Start there rather than changing compression, graphics APIs, or
exporter shape at random.
