# Blockers

Things that need a human, a licence, or a machine this session cannot reach.
Each entry says what is blocked, why, exactly what to run, and how to confirm
it worked. Nothing here blocks writing code; it blocks *proving* code.

Keep this file honest: delete an entry once its verification passes, and add
one the moment something is claimed but not verified.

## Open

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

## Verified, for contrast

These were open and are now closed, so the list above stays meaningful:

- Blender installs from the official checksum-verified build, and
  `make-mesh.py` exports all three shapes with the pivot at the base.
- The Khronos glTF validator installs and catches a corrupt GLB.
- UnityPy deep inspection reports 547 objects in the shipped Atomic Doomsday
  bundle, including `ParticleSystem=6` on the detonation VFX prefab.
- The UnityFS reader parses real shipped game bundles, including a 650 MB one.
- Every optional capability is installed and reported available:
  `7dtd-assets capabilities --missing` prints nothing.
- `scripts/bootstrap` builds a working `.venv` through uv, and the suite also
  passes against a core-only install with no optional capabilities.
- `7dtd-assets init` works from a real wheel install, and `doctor` passes every
  check against the installed game and editor.
- `build --probe` and a full `build` both run against the real Unity
  2022.3.62f2 editor (12 s and 6 s), producing a class-142 bundle at the
  game's own revision, staging bundle plus manifest, and passing `validate`.
- `GeneratedAsset.cs` compiles and runs in that editor: a three-primitive
  prefab with one root collider, two materials, bounds starting at Y = 0.
- Every rejection gate fires on real artifacts: wrong asset case, absent stem,
  wrong mod name, a URI targeting game bundles, and a mismatched game
  revision. The bare `@modfolder:` form is accepted, as the engine does.
- **The central gate is proven.** With an empty `Packages/manifest.json`,
  Unity exits zero while logging that AssetBundle was stripped, and emits a
  bundle with no class-142 object. The pipeline rejects it, names the fix, and
  leaves the previously staged bundle byte-identical.
