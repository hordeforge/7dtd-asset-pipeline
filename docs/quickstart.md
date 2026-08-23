# Quickstart: bare machine to a validated bundle

This is the complete path from a host with nothing installed to a modlet that
ships a validated asset bundle. Every step states what it costs and how you
know it worked. [Setup](setup.md) explains each choice in more detail.

Times and sizes below are the realistic case on a Linux host. The Unity editor
download is the only large one.

## 0. What you need before starting

- Linux, macOS, or Windows. The scripted install path is Linux; the CLI itself
  is portable.
- An installed 7 Days to Die client. It is the authority for which Unity
  revision your bundle must use, and it is only ever read.
- A Unity account you can sign in to. Unity Personal is sufficient.

You do **not** need the game running, a server, or any mod already made.

## 1. Host tooling (about a minute)

```bash
git clone https://github.com/ywy50/7dtd-asset-pipeline
cd 7dtd-asset-pipeline
scripts/install-tools.sh --check --with-authoring --with-unity-prereqs
```

`--check` installs nothing; it prints `OK`/`MISS` per tool so you can see what
the host is missing. Then install for real:

```bash
scripts/install-tools.sh --with-unity-prereqs     # required for step 4
scripts/install-tools.sh --with-authoring         # art and inspection tooling
```

`install-tools.sh` installs uv first, since every Python step runs through it.
`--with-authoring` then installs Blender, OpenSCAD, ImageMagick, FFmpeg, the
Khronos glTF validator, and the Python capabilities (UnityPy, Pillow, NumPy,
trimesh). Blender and the glTF validator fall back to official
checksum-verified builds where the distribution has no package. Check what is
usable at any time with `7dtd-assets capabilities --json`.

Supported package managers are `pacman`, `apt-get`, and `dnf`. On anything
else, install the tools `--check` lists by hand; the script refuses to guess
package names rather than installing the wrong thing.

## 2. The pipeline CLI (seconds)

```bash
scripts/bootstrap
.venv/bin/7dtd-assets --help
```

`scripts/bootstrap` creates `.venv/` in this checkout and installs the package
into it with uv, including the optional capabilities (`--no-extras` for the
core alone). It never uses `sudo` and does not touch shell startup files. For a
user-wide command instead, use `uv tool install .`.

Put `.venv/bin` on `PATH`, or call `7dtd-assets` by its full path in the steps
below.

## 3. Scaffold a modlet (seconds)

Point at the directory containing `Data/Config/items.xml`:

```bash
export SEVEN_DAYS_TO_DIE_DIR="/path/to/7 Days To Die"
7dtd-assets init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
```

`MyMod` must already exist and contain `ModInfo.xml`. The command reads the
Unity revision out of a shipped game bundle's header rather than trusting a
wiki page, then writes:

```text
MyMod/
├── .7dtd-assets.toml                       # configuration; commit it
├── Makefile.assets                         # assets / assets-probe / ... targets
├── assets-src/                             # editable sources + provenance; never ships
│   ├── README.md                           # what each lane holds and must record
│   └── icons/ textures/ meshes/ audio/ vfx/
└── tools/7dtd-assets/
    ├── AGENTS.md                           # the agent contract, in your repo
    └── UnityProject/                       # the Unity project the mod owns
        ├── Assets/ModAssets/Bundle/        # put selected source assets here
        ├── Assets/SevenDaysToDieAssetPipeline/Editor/BundleBuilder.cs
        ├── Assets/SevenDaysToDieAssetPipeline/Editor/GeneratedAsset.cs
        ├── Assets/SevenDaysToDieAssetPipeline/Editor/IconRenderer.cs
        ├── Packages/manifest.json          # engine modules; these are build inputs
        └── ProjectSettings/ProjectVersion.txt  # the game-matched revision
```

It refuses to overwrite any of those if they already exist. Every path is
configurable — see [Configuration](configuration.md).

## 4. Unity editor (30-60 minutes, several GB)

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

## 5. Prove the environment before touching art (a few minutes)

```bash
export UNITY_EDITOR="/path/to/Unity/Hub/Editor/<revision>/Editor/Unity"
cd /path/to/MyMod
7dtd-assets doctor
7dtd-assets build --probe
```

`doctor` checks mod identity, project revision, engine modules, game revision,
the editor, and Windows Build Support, and reports optional authoring tools.
It exits non-zero if any check is `FAIL`; `--json` gives agents and CI the full
structured report either way.

`build --probe` is the decisive test. Unity creates a throwaway cube prefab,
builds a real Windows bundle from it, the log is checked for stripped engine
modules, the artifact is parsed for a class-142 `AssetBundle` object, and the
prefab is deleted. Nothing is staged into the modlet. Getting this to pass
before art exists is the whole point: a failure here is an environment
problem, never an asset problem.

## 6. Add an asset and ship it

Put source assets **and their `.meta` files** under
`tools/7dtd-assets/UnityProject/Assets/ModAssets/Bundle/`. Name each one with a
mod-prefixed, globally unique stem — 7DTD resolves assets by file-name stem
alone, discarding folder and extension.

```bash
7dtd-assets build      # build, gate, and stage bundle + tracked manifest
7dtd-assets validate   # bundle plus every reference in Config/**/*.xml
```

Reference it from XML using the mod's `ModInfo.xml` name:

```xml
<property name="Model"
  value="#@modfolder(MyMod):Resources/mymod.unity3d?myModThing.prefab" />
```

`validate` proves the mod name, bundle path, manifest membership, exact case,
and stem uniqueness — for a `Model`, an item `Meshfile`, and a `sounds.xml`
`ClipName` alike. See [Game integration](game-integration.md) for the URI form
and server behaviour.

Two deployable asset classes are **not** bundle members and have their own
gates:

```bash
7dtd-assets check-icons                        # UIAtlases cells + every CustomIcon key
7dtd-assets check-sound assets-src/audio/x.wav # format, level, clipping, DC offset
```

## 7. Driving it from a script or an agent

```bash
7dtd-assets status --json
```

```bash
7dtd-assets schema               # every operation, machine-readable
7dtd-assets call status          # run one operation, JSON in and out
7dtd-assets serve                # many operations over one stdio session
```

`status` is one call, no Unity, no network, and it never raises for a
mod-state problem —
it reports what exists, whether the bundle matches the game, what the manifest
lists, which XML references exist, and whether the mod is valid. `init` also
wrote `tools/7dtd-assets/AGENTS.md` into your mod so an agent working there has
the rules. See [Consumer interfaces](consumer-api.md).

## 8. Acceptance

Offline gates are necessary, not sufficient. Finish with a genuinely fresh
client that loads the changed asset by its real URI, and look at or listen to
it. [Validation](validation.md) lists exactly what offline parsing cannot
prove; [Release checklist](release-checklist.md) is the full list.

## Creating the assets themselves

`7dtd-assets generate` ships reproducible generators for
the sound, cutout, icon, texture, and mesh lanes; the scaffolded Unity project
ships `GeneratedAsset.cs` for building prefabs, materials, imports, particle
state, and audio from code, and `IconRenderer.cs` for photographing a prefab
into an atlas cell.

```bash
7dtd-assets generate sound blast assets-src/audio/blast.wav --seed 7
7dtd-assets generate cutout key assets-src/icons/thing-src.png \
    UIAtlases/ItemIconAtlas/myModThing.png --size 160 --pad 0.9 --trim
7dtd-assets render-icon myModThing        # or render the item itself
```

Read these before authoring:

- [Art direction](art-direction.md) — the house style and the prompt patterns
  that produce an asset which looks native rather than merely clean;
- [Sound](audio.md) — synthesis, `sounds.xml`, and why a loaded clip can be
  silent;
- [Visual effects](vfx.md) — budgets, LOD tiers, and two silent material
  failures;
- [Agent workflows](agent-workflows.md) — the lane each asset type follows.

## When something fails

```bash
7dtd-assets status --json                     # whole-mod state; never raises
7dtd-assets doctor --json                     # structured environment report
7dtd-assets inspect Resources/mymod.unity3d   # revision, class IDs, class 142
7dtd-assets check-log .asset-pipeline/build/bundle/unity-build.log
7dtd-assets refs                              # every URI the XML actually uses
```

[Troubleshooting](troubleshooting.md) maps each failure message to its root
cause. Start there rather than changing compression, graphics APIs, or
exporter shape at random.
