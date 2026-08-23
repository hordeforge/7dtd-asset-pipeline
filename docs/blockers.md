# Blockers

Things that need a human, a licence, or a machine this session cannot reach.
Each entry says what is blocked, why, exactly what to run, and how to confirm
it worked. Nothing here blocks writing code; it blocks *proving* code.
Capability gaps — things no one has built yet, with the tools that would close
them — live in [improvements.md](improvements.md) instead of here.

Keep this file honest: delete an entry once its verification passes, and add
one the moment something is claimed but not verified.

## Open

### 1. The Unity editor download path is unexercised

**Not blocked:** the editor itself is present and proven. This host has
Unity **2022.3.62f2** with Windows Build Support (Mono) installed at
`~/Unity/Hub/Editor/2022.3.62f2/`, `doctor` passes against it, and real
`build --probe` and `build` runs have produced class-142 bundles with it. A
second editor, 6000.5.9f1, is also installed and is **not** usable here: wrong
revision, no Windows module.

**Blocks only this:** because that editor was already installed,
`scripts/install-unity-editor.sh` took its reuse path, so its own
download-verify-unpack branch has never executed. The resolution half *is*
verified — it produces the same changeset (`7670c08855a9`) and windows-mono
MD5 (`b5adce741fb7633c039e216348110332`) that Atomic Doomsday had hardcoded.

**You run** (on a host without that editor, or with `UNITY_EDITOR_INSTALL_DIR`
pointed somewhere fresh):

```bash
UNITY_EDITOR_INSTALL_DIR=/tmp/unity-test \
  ./scripts/install-unity-editor.sh --version 2022.3.62f2 --skip-hub
```

**Confirms it worked:** the script prints `OK: checksum verified` twice, then
`OK: Windows Build Support (Mono) is installed`.

### 2. Unity Hub sign-in and license activation

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

### 3. No fresh-client acceptance has been run

**Blocks:** the only gate that actually proves a bundle loads. Every offline
gate in this repository is verified, and the docs are explicit that offline
gates are necessary but not sufficient. Nothing here has been through a real
client.

**You run:** build a bundle in a real mod, deploy it, start a genuinely fresh
client, and load each changed asset by its real URI. The plumbing exists now
(`shamway client deploy`, `shamway client launch --mod-name …`, which refuses
a running client and classifies the log this launch wrote); what is missing
is a human running it against a pipeline-built bundle. See
[validation.md](validation.md) and [release-checklist.md](release-checklist.md).

**Confirms it worked:** the asset renders or sounds correct, and the client log
has no bundle-load, incompatibility, wrong-name, shader, or particle errors.

### 4. The icon renderer has not been run in a real editor

**Blocks:** any claim that `shamway render-icon` works. Its Python side is
exercised — prefab resolution, the missing-editor and missing-Pillow errors,
the coverage gate, and the atlas-cell check — and since 2026-08-23 all four
editor scripts **compile** against Unity 2022.3.62f2's own assemblies
(`scripts/compile-editor-scripts.sh`, run by `make check`; it immediately
found and fixed a hard-obsolete `AudioImporter.preloadAudioData`). On the same
day a `shamway build --probe` with Unity 2022.3.62f2 opened a freshly
scaffolded project, compiled all four scripts with no `error CS` line,
executed `BundleBuilder`, and produced a class-142 bundle. A non-probe
`shamway build` on the same throwaway mod, with one `[ShamwayPreBuild]`
generator, then proved the hook end to end — `pre-build: 1 generator(s)`,
`running SmokeGenerators.Touch`, `Shamway.SourceRoot` reaching the generator —
and executed `StandardMaterial` (with the `_OcclusionMap` slot), `Tile`,
`EmissiveMaterial`, `Primitive`, `RootCapsuleCollider`, `SavePrefab`,
`LightPrefab`, `ImportNormalMap` and `ImportLinearMap`; the `.mat` files carry
`_NORMALMAP`, `_METALLICGLOSSMAP`, `_EMISSION` and the tiling, and
`inspect --deep` shows the `CapsuleCollider` and `Light` survived
serialization. What remains unproven is *execution* of the rest:
`IconRenderer.cs` and the remaining `GeneratedAsset` helpers
(`ImportColorMap`, `ParticleMaterial`, `ZeroCurve`, `BudgetParticles`,
`ImportAudioClip`, `AudioSourcePrefab`) have never been *run* by an editor
from this repository, and nothing built here has yet been loaded by a client.

**You run:** in a scaffolded mod with a prefab in the bundle folder, on a host
with a display (or under `xvfb-run -a`):

```bash
shamway render-icon myModThing
shamway check-icons
```

**Confirms it worked:** a 160 x 160 RGBA PNG appears under
`UIAtlases/ItemIconAtlas/`, showing the prefab lit from three sides on a
transparent background, and `check-icons` accepts it. A uniform transparent
square means the render had no graphics device.

### 5. No externally built bundle has made the round trip

**Not blocked:** `shamway stage` itself. It runs the artifact gates the local
build runs — class-142, revision, stem collisions, the build-log gate when a
log is supplied — and the unit suite exercises acceptance and each rejection
against generated UnityFS fixtures, including that a rejected candidate leaves
the previously staged bundle in place.

**Blocks only this:** the claim that the *round trip* works. No bundle built by
an editor on a different machine has been carried back and staged here, and the
build-host half (`SHAMWAY_BUNDLE_SOURCE=unity` on a host whose committed
configuration says `external`) has never run on a second machine.

**You run,** on the host with the editor:

```bash
export SHAMWAY_BUNDLE_SOURCE=unity
shamway build
```

then copy `Resources/<name>.unity3d`, `tools/shamway/manifests/<name>.manifest`
and `.shamway/build/bundle/unity-build.log` to the machine without an editor,
and there:

```bash
shamway stage <name>.unity3d --manifest <name>.manifest --log unity-build.log
shamway validate
```

**Confirms it worked:** `stage` prints `OK:` with no `not run:` line (both the
log and `SEVEN_DAYS_TO_DIE_DIR` were present), `validate` passes, and the
bundle then loads in a fresh client per entry 3.

### 6. No synthesized bundle has been loaded by a client

**Not blocked:** the writer itself, and more of it than expected. A bundle
`shamway build` synthesized with no editor in its path — `Texture2D`,
`AudioClip` and `TextAsset` — was loaded on 2026-08-23 by a real Unity
2022.3.62f2 runtime through `AssetBundle.LoadFromFile`, and every object
deserialized with the engine's own class definitions: the text came back, the
texture as `4x2 RGBA32` with its rows the right way up, and FMOD decoded the
hand-written FSB5 bank to `channels=1 frequency=44100 samples=4410`. That is
`shamway verify-bundle`, and it is repeatable on any host with an editor.

**Blocks only this:** the claim that **7 Days to Die** loads one. A Unity
runtime of the same revision is not the game: it does not exercise
`DataLoader.ParseDataPathIdentifier`, `AssetBundleManager._get`'s stem
reduction, or the block/sound systems that consume the result. And on a
synthesized bundle the class-142 and stem gates are true by construction, so
the fresh client is not a confirmation step here — it is the acceptance. The
mode is exposed anyway, at the user's direction, which is a deliberate
deviation from the phase-4 bar in
[offline-bundle-builder.md](offline-bundle-builder.md); every synthesize prints
what its gates are worth.

**You run:** in a mod with `bundle_source = "synthesized"`, an XML reference to
one of its assets, and a client installed:

```bash
shamway build
shamway validate
shamway client deploy .
shamway client launch --mod-name MyMod
```

**Confirms it worked:** the client log carries `Loaded Mod: MyMod` with no
bundle-load, incompatibility or wrong-name lines, and the asset itself is
right when a person looks at or listens to it — a texture that is the right
way up, a clip at the right pitch.

## Verified, for contrast

These were open and are now closed, so the list above stays meaningful:

- Blender installs from the official checksum-verified build, and
  `shamway generate mesh` exports all three shapes with the pivot at the base.
- The Khronos glTF validator installs and catches a corrupt GLB.
- UnityPy deep inspection reports 547 objects in the shipped Atomic Doomsday
  bundle, including `ParticleSystem=6` on the detonation VFX prefab.
- The UnityFS reader parses real shipped game bundles, including a 650 MB one.
- Every optional capability is installed and reported available:
  `shamway capabilities --missing` prints nothing.
- `scripts/bootstrap` builds a working `.venv` through uv, and the suite also
  passes against a core-only install with no optional capabilities.
- `shamway init` works from a real wheel install, and `doctor` passes every
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
