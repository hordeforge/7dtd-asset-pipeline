# Setup

For the shortest end-to-end path, follow [Quickstart](quickstart.md). This
page explains each step's reasoning and its alternatives.

## 0. Install host tooling

```bash
scripts/install-tools.sh --check --with-authoring
```

`--check` reports `OK`/`MISS` per tool and installs nothing. Drop `--check` to
install through `pacman`, `apt-get`, `dnf`, or `zypper`. Only Python is
required for the CLI itself. The base set also carries `vkd3d-compiler`, which
compiles the shader a synthesized prefab's material needs — the writer's one
host dependency, and it degrades to a bare `Mesh` with a printed note rather
than failing. It has a **minimum version, 1.3**, and Debian and Ubuntu package
1.2; `--with-vkd3d-source` builds a usable one on any distribution and does
nothing where the packaged one already works. `--with-unity-prereqs` covers the **optional** editor
installer's needs, `--with-authoring` the optional art tooling in
[Authoring tools](../authoring/authoring-tools.md) — Blender, OpenSCAD, ImageMagick, FFmpeg,
and Xvfb, plus the Python capabilities (Pillow, NumPy, trimesh, UnityPy) —
`--with-desktop-capture` a screenshot tool (`grim` on Wayland, `maim` on X11)
so `shamway client capture` can record what a person looked at during
acceptance — skip it on a headless build host — and `--with-research` the
decompilers every new engine fact must cite: the
.NET 8 SDK with `ilspycmd` as a global dotnet tool (in `~/.dotnet/tools`,
which goes on `PATH`), and Mono for `monodis` and `mcs`. Never set a global
`DOTNET_ROOT` for ilspycmd; a distribution .NET upgrade can strand the tool,
and Unity Hub ships a fallback SDK under `Editor/Data/DotNetSdk` per editor.
The base set also installs `shellcheck` (for `make check`) and `pactl` (for
`shamway client mute`). The script exits non-zero if Python or uv is still
missing afterwards, rather than leaving a `MISS` line to scroll past.

Xvfb is there for one specific reason: `shamway render-icon` needs a real
graphics device, and Unity run with `-nographics` renders a blank image instead
of failing. On a headless host, run that one command under `xvfb-run -a`.
Nothing else in the pipeline needs a display — `build` uses `-nographics`
deliberately.

## 1. Install the pipeline CLI

Every Python step in this project goes through [uv](https://docs.astral.sh/uv/):
environments, installs, and test runs. `scripts/install-tools.sh` installs it,
from the distribution package where one exists and otherwise from the official
checksum-verified release.

The runtime itself has no third-party Python dependencies. Python 3.11 is
required because configuration uses the standard-library TOML parser; uv
provisions a suitable interpreter itself if the host has none.

From a checkout:

```bash
scripts/bootstrap
.venv/bin/shamway --help
```

For a user-wide isolated command:

```bash
uv tool install /path/to/7dtd-asset-pipeline
```

`scripts/bootstrap` creates only `.venv/` in this checkout and installs the
package into it with `uv sync --locked`, which resolves from the committed
`uv.lock` and verifies its hashes — including the optional capabilities. The
`--locked` flag fails rather than re-resolving when `pyproject.toml` has
drifted from the lock; re-lock deliberately with `uv lock`. Pass
`--no-extras` for the dependency-free core alone. It never
uses `sudo`, installs OS packages, or modifies shell startup files.

## 2. Identify the game install and its engine revision

The installed game is the authority. Point `--game-dir` or
`SEVEN_DAYS_TO_DIE_DIR` at the directory containing
`Data/Config/items.xml`. The pipeline reads only from it.

```bash
shamway init /path/to/MyMod \
  --game-dir "/absolute/path/to/7 Days To Die"
```

The command opens the first readable shipped bundle, preferring
`Data/Bundles/Standalone/Entities/Entities`, and reads the revision from its
UnityFS header. Do not choose an editor from a wiki page when the installed
game can answer directly.

If the game is not installed on the authoring host, pass an explicitly
verified revision:

```bash
shamway init /path/to/MyMod --unity-version 2022.3.62f2
```

Record how that revision was verified in the mod's documentation.

## 3. (Optional) Install Unity and Windows Build Support

**Skip this whole section unless the mod opted into an editor.** Three of the
four bundle sources need none, and the default is one of them:
`bundle_source = "synthesized"` has this tool write the `.unity3d` itself,
`"external"` has an editor elsewhere build it and `shamway stage` gate it here,
and `"none"` ships no bundle at all. [Running without
Unity](../bundles/no-unity.md) covers all three, including what a build host
does instead.

What is left needing an editor here is `bundle_source = "unity"` — a bundle
whose shading the writer does not author — and the two commands that use an
editor as a tool rather than as a build step, `shamway verify-bundle` and
`shamway render-icon`. Nothing needs either of those to build, gate, stage or
ship.

The editor revision must match the installed game exactly, and **Windows Build
Support (Mono)** is mandatory: the shipped client loads a Windows-target bundle
even when it runs through Proton.

### Known-good pairing

| 7 Days to Die | Unity editor | Changeset |
|---|---|---|
| V 3.1.0 b14 | 2022.3.62f2 | `7670c08855a9` |

This is the pairing the extraction was developed and verified against, and it
is recorded here as **evidence, not a constant**. Every command discovers the
revision from the installed game rather than trusting this table, because the
game dictates it and a new game build can move it:

- `shamway doctor` — FAILs if project and game disagree

```bash
shamway init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
shamway doctor
```

`init` also pins the changeset into the project's
`ProjectSettings/ProjectVersion.txt`:

```text
m_EditorVersion: 2022.3.62f2
m_EditorVersionWithRevision: 2022.3.62f2 (7670c08855a9)
```

Unity writes the second line itself on first open; writing it during scaffold
records the exact build in review and in git history. Pass `--changeset`
explicitly when the release service is unreachable.

Do not assume a newer editor is fine. A host can have several installed — this
one has both 2022.3.62f2 and 6000.5.9f1 — and only the game-matched revision
with Windows Build Support can produce a loadable bundle. `doctor` compares the
project against the game's own shipped bundle header and fails on a mismatch,
which is why `UNITY_EDITOR` must point at the right one.

### Scripted (Linux)

```bash
scripts/install-tools.sh --with-unity-prereqs
cd /path/to/MyMod
/path/to/7dtd-asset-pipeline/scripts/install-unity-editor.sh
```

The script resolves the changeset, archive URL, and MD5 for the project's
revision from Unity's official release service, so it does not go stale when
the game updates its engine. It installs Unity Hub, waits for you to sign in
and activate a license, copies that license to Unity's native Linux location,
installs the checksum-verified editor and Windows module, and proves batch
mode works. It refuses to install any download Unity published no checksum for.

Point it at an existing licensed editor instead with:

```bash
export UNITY_EDITOR="/path/to/Unity/Hub/Editor/2022.3.62f2/Editor/Unity"
scripts/install-unity-editor.sh --skip-hub
```

Inspect exactly what would be downloaded, without downloading anything:

```bash
shamway unity-release --version 2022.3.62f2 --json
```

### Unity's own CLI

Unity ships an experimental CLI that installs an editor plus modules directly.
It is a legitimate alternative to the script above when you would rather drive
Unity's tooling:

```bash
unity install 2022.3.62f2 -c 7670c08855a9 -m windows-mono
```

`-c` supplies the changeset, which is only needed when the requested revision
is absent from the CLI's release feed. Resolve it, and the exact download URLs
and checksums, without installing anything:

```bash
shamway unity-release --version 2022.3.62f2 --json
```

Unity documents the CLI at
<https://docs.unity.com/en-us/unity-cli/unity-cli-reference> and Hub installs
at <https://docs.unity.com/en-us/hub/install-hub>. Sign-in and license
activation remain user-owned actions in every route.

### Manual (any platform)

The Hub UI is equally valid:

1. Install Unity Hub from Unity's official distribution.
2. Sign in yourself.
3. Activate an appropriate license through Unity's supported UI.
4. Install the exact editor revision reported by `shamway init` or
   `shamway doctor`.
5. Add Windows Build Support (Mono) to that editor.

Never place Unity usernames, passwords, tokens, or license files in a mod
repository, pipeline config, CI log, or agent prompt. No script in this
repository reads, prints, or stores them.

## 4. Configure machine-local paths

Environment variables take precedence over blank config values. One is worth
setting on every host:

```bash
export SEVEN_DAYS_TO_DIE_DIR="/absolute/path/to/7 Days To Die"
```

The other only where an editor exists, and only for the three things that use
one — `bundle_source = "unity"`, `verify-bundle`, and `render-icon`. Leaving it
unset is not a problem anywhere else:

```bash
export UNITY_EDITOR="/absolute/path/to/Unity/Hub/Editor/2022.3.62f2/Editor/Unity"
```

On Windows, `UNITY_EDITOR` ends in `Editor/Unity.exe`. On macOS it points at
the executable inside the editor application bundle. Do not commit either
path. The pipeline reads these two variables, `SHAMWAY_BUNDLE_SOURCE`, and the
two `shamway client` overrides in [configuration.md](../configuration.md); it
reads no `.local.env` or other dotenv file, so a mod that keeps one must export
it itself.

`doctor` compares what `UNITY_EDITOR -version` reports against the project's
pinned revision and **fails** on a difference. That check exists because a
wrong editor does not fail: batch mode opens the project, upgrades it
silently, and builds a bundle the game rejects. It runs only for a mod that
opted into an editor; on the default path there is no project to compare
against and the row is absent rather than warning.

## 5. Prove setup

```bash
cd /path/to/MyMod
shamway doctor
shamway build --probe
```

`doctor` reads `bundle_source` first and checks only what that source can
fail on. Synthesized, that is the mod identity, the revision against the
installed game, the source folder, and whether the writer has the type trees it
needs; the Unity rows are absent rather than warning about an editor the mod
never asked for. With `bundle_source = "unity"` it adds the project revision,
the package modules, the editor executable, and Windows Build Support. Each
check reports its own `OK`/`WARN`/`FAIL` verdict, and the command exits
non-zero when any check is `FAIL`, so one broken check never hides the rest.
Use `shamway doctor --json` for CI or agents.

The probe is the decisive setup test, and it stages nothing on either path.
Synthesized, it writes the whole bundle from the source folder in milliseconds
and runs every offline gate on it. With an editor, it asks Unity to create a
cube prefab, build a throwaway Windows bundle, checks the Unity log, parses the
result for class 142, and deletes the source prefab — which also exposes
license failures that `Unity -version` cannot.

## Platform notes

- None of these notes applies to the default path, which starts no editor.
- Linux native Unity can build the Windows-target bundle. Proton is not
  required for the editor; the source project tried a Windows editor under an
  isolated Proton prefix as an escape hatch and proved it unnecessary, so
  that path is not carried here. The final client test may still run under
  Proton.
- Without starting the editor, `scripts/compile-editor-scripts.sh` compiles
  the vendored editor scripts against the installed editor's assemblies
  (needs `mcs` from `--with-research`); `make check` runs it when it can.
- Older Unity 2022 editors may need distribution compatibility libraries.
  If the editor itself fails before writing a log, run `ldd "$UNITY_EDITOR"`
  and install the missing library through the host's package manager; do not
  copy arbitrary shared objects into the project.
- The build target is configurable, but `StandaloneWindows64` is the supported
  and proven default. macOS Metal shader support can require a separate asset
  strategy; see [Game integration](../game-integration.md).
