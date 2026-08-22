# Setup

## 1. Install the pipeline CLI

The runtime has no third-party Python dependencies. Python 3.11 is required
because configuration uses the standard-library TOML parser.

From a checkout:

```bash
scripts/bootstrap
.venv/bin/7dtd-assets --help
```

For a user-wide isolated command:

```bash
pipx install /path/to/7dtd-asset-pipeline
```

`scripts/bootstrap` creates only `.venv/` in this checkout and adds the
checkout's `src/` through a local `.pth` file. It is offline and does not need
pip/setuptools, use `sudo`, install OS packages, or modify shell startup files.

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

Use Unity Hub or Unity's standalone CLI to install the exact revision plus
**Windows Build Support (Mono)**. Unity's current CLI is experimental, so the
repository helper prints the action before it runs anything:

```bash
scripts/setup-unity --version 2022.3.62f2 \
  --changeset 7670c08855a9
```

Add `--run` only after reviewing the printed command. The equivalent current
Unity CLI shape is:

```bash
unity install 2022.3.62f2 -c 7670c08855a9 -m windows-mono
```

For newer game revisions, obtain the version from the game and use Unity's
release feed. Supply a changeset only when that revision is absent from the
feed. Unity documents the CLI at
<https://docs.unity.com/en-us/unity-cli/unity-cli-reference> and Hub installs
at <https://docs.unity.com/en-us/hub/install-hub>.

The Hub UI is equally valid:

1. Install Unity Hub from Unity's official distribution.
2. Sign in yourself.
3. Activate an appropriate license through Unity's supported UI.
4. Install the exact editor revision.
5. Add Windows Build Support (Mono) to that editor.

Never place Unity usernames, passwords, tokens, or license files in a mod
repository, pipeline config, CI log, or agent prompt.

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
optional authoring tools. Use `7dtd-assets doctor --json` for CI or agents.

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
