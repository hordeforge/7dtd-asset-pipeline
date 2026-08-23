# Setup

For the shortest end-to-end path, follow [Quickstart](quickstart.md). This
page explains each step's reasoning and its alternatives.

## 0. Install host tooling

```bash
scripts/install-tools.sh --check --with-authoring --with-unity-prereqs
```

`--check` reports `OK`/`MISS` per tool and installs nothing. Drop `--check` to
install through `pacman`, `apt-get`, or `dnf`. Only Python is required for the
CLI itself; `--with-unity-prereqs` covers the editor installer's needs and
`--with-authoring` the optional art tooling in
[Authoring tools](authoring-tools.md) — Blender, OpenSCAD, ImageMagick, FFmpeg,
and Xvfb, plus the Python capabilities (Pillow, NumPy, trimesh, UnityPy).

Xvfb is there for one specific reason: `7dtd-assets render-icon` needs a real
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
.venv/bin/7dtd-assets --help
```

For a user-wide isolated command:

```bash
uv tool install /path/to/7dtd-asset-pipeline
```

`scripts/bootstrap` creates only `.venv/` in this checkout and installs the
package into it with `uv pip install --editable`, including the optional
capabilities. Pass `--no-extras` for the dependency-free core alone. It never
uses `sudo`, installs OS packages, or modifies shell startup files.

## 2. Identify the game install and Unity revision

The installed game is the authority. Point `--game-dir` or
`SEVEN_DAYS_TO_DIE_DIR` at the directory containing
`Data/Config/items.xml`. The pipeline reads only from it.

```bash
7dtd-assets init /path/to/MyMod \
  --game-dir "/absolute/path/to/7 Days To Die"
```

The command opens the first readable shipped bundle, preferring
`Data/Bundles/Standalone/Entities/Entities`, and reads the revision from its
UnityFS header. Do not choose an editor from a wiki page when the installed
game can answer directly.

If the game is not installed on the authoring host, pass an explicitly
verified revision:

```bash
7dtd-assets init /path/to/MyMod --unity-version 2022.3.62f2
```

Record how that revision was verified in the mod's documentation.

## 3. Install Unity and Windows Build Support

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

```bash
7dtd-assets init /path/to/MyMod --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
7dtd-assets doctor          # FAILs if project and game disagree
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
7dtd-assets unity-release --version 2022.3.62f2 --json
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
7dtd-assets unity-release --version 2022.3.62f2 --json
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
4. Install the exact editor revision reported by `7dtd-assets init` or
   `7dtd-assets doctor`.
5. Add Windows Build Support (Mono) to that editor.

Never place Unity usernames, passwords, tokens, or license files in a mod
repository, pipeline config, CI log, or agent prompt. No script in this
repository reads, prints, or stores them.

## 4. Configure machine-local paths

Environment variables take precedence over blank config values:

```bash
export SEVEN_DAYS_TO_DIE_DIR="/absolute/path/to/7 Days To Die"
export UNITY_EDITOR="/absolute/path/to/Unity/Hub/Editor/2022.3.62f2/Editor/Unity"
```

On Windows, `UNITY_EDITOR` ends in `Editor/Unity.exe`. On macOS it points at
the executable inside the editor application bundle. Do not commit either
path.

## 5. Prove setup

```bash
cd /path/to/MyMod
7dtd-assets doctor
7dtd-assets build --probe
```

`doctor` checks the mod identity, Unity project revision, package modules,
game revision, editor executable, and Windows Build Support. It also reports
optional authoring tools. Each check reports its own `OK`/`WARN`/`FAIL`
verdict, and the command exits non-zero when any check is `FAIL`, so one broken
check never hides the rest. Use `7dtd-assets doctor --json` for CI or agents.

The probe is the decisive setup test. It asks Unity to create a cube prefab,
build a throwaway Windows bundle, checks the Unity log, parses the result for
class 142, and deletes the source prefab. It never stages into the modlet.
It also exposes license failures that `Unity -version` cannot.

## Platform notes

- Linux native Unity can build the Windows-target bundle. Proton is not
  required for the editor. The final client test may still run under Proton.
- Older Unity 2022 editors may need distribution compatibility libraries.
  If the editor itself fails before writing a log, run `ldd "$UNITY_EDITOR"`
  and install the missing library through the host's package manager; do not
  copy arbitrary shared objects into the project.
- The build target is configurable, but `StandaloneWindows64` is the supported
  and proven default. macOS Metal shader support can require a separate asset
  strategy; see [Game integration](game-integration.md).
