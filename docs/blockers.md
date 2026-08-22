# Blockers

Things that need a human, a licence, or a machine this session cannot reach.
Each entry says what is blocked, why, exactly what to run, and how to confirm
it worked. Nothing here blocks writing code; it blocks *proving* code.

Keep this file honest: delete an entry once its verification passes, and add
one the moment something is claimed but not verified.

## Open

### 1. OpenSCAD is not installed (needs sudo)

**Blocks:** the OpenSCAD branch of `scripts/install-tools.sh` is the only
authoring tool whose install path has never executed, and
`7dtd-assets capabilities` reports it as the sole missing capability.

**You run:**

```bash
cd /path/to/7dtd-asset-pipeline
./scripts/install-tools.sh --with-authoring
```

**Confirms it worked:**

```bash
7dtd-assets capabilities --missing    # should print nothing
```

Blender, ImageMagick, FFmpeg, the Khronos glTF validator, UnityPy, Pillow,
NumPy, and trimesh are all installed and verified already.

### 2. The Unity editor download path is unexercised

**Blocks:** `scripts/install-unity-editor.sh` resolves the changeset, URLs, and
MD5s correctly and detects the existing editor, but this host already had
Unity 2022.3.62f2, so the download-verify-unpack branch never ran. The
resolution half is verified: it produces the same changeset (`7670c08855a9`)
and windows-mono MD5 (`b5adce741fb7633c039e216348110332`) that Atomic
Doomsday had hardcoded.

**You run** (on a host without that editor, or with `UNITY_EDITOR_INSTALL_DIR`
pointed somewhere fresh):

```bash
UNITY_EDITOR_INSTALL_DIR=/tmp/unity-test \
  ./scripts/install-unity-editor.sh --version 2022.3.62f2 --skip-hub
```

**Confirms it worked:** the script prints `OK: checksum verified` twice, then
`OK: Windows Build Support (Mono) is installed`.

### 3. Unity Hub sign-in and license activation

**Blocks:** steps 2-4 of `install-unity-editor.sh` (Hub install, license
activation, Flatpak-to-native license copy). These deliberately stop and wait
for a human — account credentials are never automated — so they cannot be
verified from a non-interactive session, by design.

**You run,** from a terminal on the graphical desktop:

```bash
cd /path/to/MyMod
/path/to/7dtd-asset-pipeline/scripts/install-unity-editor.sh
```

**Confirms it worked:** `OK: Unity batch-mode license is active`.

### 4. No fresh-client acceptance has been run

**Blocks:** the only gate that actually proves a bundle loads. Every offline
gate in this repository is verified, and the docs are explicit that offline
gates are necessary but not sufficient. Nothing here has been through a real
client.

**You run:** build a bundle in a real mod, deploy it, start a genuinely fresh
client, and load each changed asset by its real URI. See
[release-checklist.md](release-checklist.md).

**Confirms it worked:** the asset renders or sounds correct, and the client log
has no bundle-load, incompatibility, wrong-name, shader, or particle errors.

### 5. `7dtd-assets build` has never run against a real Unity

**Blocks:** end-to-end proof of `build` and `build --probe`. `doctor` passes
fully against the real editor here, so the environment is ready, but no build
has been executed from this repository.

**You run:**

```bash
cd /path/to/MyMod
export UNITY_EDITOR="/path/to/Unity/Hub/Editor/2022.3.62f2/Editor/Unity"
7dtd-assets doctor && 7dtd-assets build --probe
```

**Confirms it worked:** `OK: .../probe/seven-days-to-die-pipeline-probe.unity3d`.
The probe stages nothing into the modlet, so it is safe to run at any time.

## Verified, for contrast

These were open and are now closed, so the list above stays meaningful:

- Blender installs from the official checksum-verified build, and
  `make-mesh.py` exports all three shapes with the pivot at the base.
- The Khronos glTF validator installs and catches a corrupt GLB.
- UnityPy deep inspection reports 547 objects in the shipped Atomic Doomsday
  bundle, including `ParticleSystem=6` on the detonation VFX prefab.
- The UnityFS reader parses real shipped game bundles, including a 650 MB one.
- `7dtd-assets init` works from a real wheel install, and `doctor` passes every
  check against the installed game and editor.
