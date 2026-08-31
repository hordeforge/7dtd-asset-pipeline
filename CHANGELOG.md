# Changelog

All notable changes to `7dtd-asset-pipeline` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are
the tags (`vX.Y.Z`) that drive the release workflow.

Releases are tag-driven: bump `__version__` in
[src/sevendtd_asset_pipeline/_version.py](src/sevendtd_asset_pipeline/_version.py),
move this file's `[Unreleased]` entries under the new version heading, land
both on `main`, then push the matching tag. The release workflow fails if a
tag has no changelog section.

## [Unreleased]

### Added

- **`shamway check-patches`** replays every structural operation XPath in
  `Config/*.xml` against the installed game's read-only `Data/Config/<stem>.xml`
  and fails the ones selecting zero nodes. The engine silently no-ops a
  zero-match XPath (`XmlFile.GetXpathResultsInList` returns false, the operation
  returns 0), so a typo'd/renamed selector ships unapplied with no error; the
  decompiled rules are in research-provenance. An XPath the standard-library
  subset cannot evaluate is reported as not checked rather than guessed.
- **`ModInfo.xml` schema is gated** — `validate` now checks `<Version>` is
  present and a dotted-numeric version and `<Description>` is non-empty
  (`references.check_mod_info_schema`). A missing/malformed version ships a
  stale mod version and a missing description a blank mod-list row, neither of
  which errors in game.
- **Property-based tests for the UnityFS reader** (`tests/test_property.py`,
  Hypothesis, dev-group dep). `inspect_bundle` must succeed or raise the
  reader's own `PipelineError` on arbitrary bytes, hostile class IDs, hostile
  node sizes / archive flags / truncation, and hostile LZ4 payloads — never a
  leaked `struct.error`/raw exception that a caller turns into a traceback.
- **`shamway check-localization`** reconciles every localization key Config/
  references (item/block/entity_class names plus bare-token
  `display_name`/`Description`/`desc_key`/`tooltip` values) with the mod's
  `Config/Localization.csv` and the game's vanilla table, failing a referenced
  key provided by neither when the mod ships a CSV (a dropped row is a bug —
  `Localization.Get` returns the key itself on a miss, so it shows as a raw
  name). A mod with no CSV is reported as untranslated rather than failed;
  `--no-vanilla-keys` fails vanilla keys too.
- Generated entity bones **carry colliders**: the writer adds a small
  `BoxCollider` to every skinned bone GameObject, so the game's physics body
  builds real colliders instead of `NullCollider`s
  (`PhysicsBodyInstance.bindCollider` looks for a Box/Capsule/Sphere collider
  on each referenced bone and, finding none, created a null collider — the
  real root cause of a generated creature floating). A generated creature is
  now physically solid and grounds when the engine simulates it (e.g.
  server-side). **Grounded walking is still not demable in the client-side
  look harness:** the client does not gravity-simulate a client-spawned
  entity — measured, the creature holds its +3 m spawn offset (y=64.08) with
  the colliders present. A server-side spawn (or a harness that simulates the
  spawned entity's gravity) is the outstanding, non-asset step; recorded in
  research-provenance.
- **`shamway generate hide`** draws a seeded fur/hide albedo for a
  generated entity — mottled patches, anisotropic fur clumps, hair grain
  (periodic by construction, so a primitive's default UVs never show a
  seam) — with no image model and no host packages beyond Pillow and
  NumPy. Same seed, same bytes. `--patch` adds a second, darker tone
  (spots), which is what keeps a creature readable against whatever the
  biome is — a single flat hue disappears into the forest or the dirt.
  The self-test creature's skin is the two-tone coat (`--base 192,180,152
  --patch 70,55,40`), so the leg-boundary is judgeable in a look run.
- Generated quadruped **paws are now chunky and visible**: the default
  quadruped parts had 0.045 m-tall paw boxes that read as nothing at the
  distance a look run photographs from — the creature looked legless and
  "clipped into the floor". The front paws are now 0.10×0.15×0.09 m and
  the rear 0.11×0.17×0.10 m, so the feet read at a glance.
- Generated entities **attack, die and jump**: `--anim` grows `attack`,
  `death` and `jump` — `Attack1` jabs the head forward and back (a
  half-sine, never past rest — that overshoot is the nervous-bob look —
  with a quarter body pitch), `Death` rolls the body over once and stays
  down (`loop: false` → `m_WrapMode` 1), and `Jump` hops the body.
  `parse_anim` accepts them plus `loop` and `body_bone`; `clip_fields`
  picks the wrap mode from the entries. The self-test creature carries
  all six kinds, and the attack and death clips were signed off in a live
  client on 2026-08-30.
- Staged look prefabs **sit on the ground**: the generated look case
  grounds its prefab at `World.GetHeight` + 1 — the chunk's actual
  top-block height map, the exact query the game's own spawner uses for
  ground entities (`chunk.GetHeight(...) + 1`, reverse-engineered from
  `World.FindRandomSpawnPointNearPosition`), rebased to absolute
  coordinates with `Origin.position`. An animated entity now moves against
  the terrain instead of hovering in front of the camera. (Three wrong
  ground queries are recorded in research-provenance: `GetHeightAt` is the
  uncarved generator heightmap, `GetTerrainHeight` is the generator's
  cached height that ignores voxel edits — it sat the entity ~2 blocks
  under the visible surface — and a raw rebased query hit the map-origin
  column. The staging rotation also no longer pitches the prefab by the
  camera's look angle.)
- Generated entities **walk and look around**: `--anim idle,head,walk`
  writes legacy clips — `Idle1` (a body bob merged with a slow head yaw)
  and `Walk` (a trot: upper legs swing, knees bend the opposite way, the
  body dips between steps, diagonal pairs move together) — with the bone
  paths picked rig-aware from the rig's own names. The `.anim.json`
  declaration is the extension point (any clip name the engine's
  controller plays; entries merging by name). The self-test creature's
  turntable clip was signed off for motion, the gait as a recorded
  milestone.
- Generated entities **move**: `generate entity --anim` writes a
  `{stem}.anim.json` (a looping `Idle1` bob on the rig's first bone) and
  sets `AvatarController=GameObjectAnimalAnimation` on the entity class;
  the writer attaches a legacy `Animation` component with the declared
  clips to the prefab root. Legacy clips serialize their curves directly
  (`m_MuscleClipSize = 0`, measured from the game's animals.bundle), so
  they are synthesized through the type tree with no editor. The self-test
  creature is animated and its turntable look suite captures a motion clip;
  the rig looks and the motion were signed off in a live client on
  2026-08-30.
- The generated entity is now spawnable and visibly textured:
  `generate entity --xml` emits `UserSpawnType="Menu"` (the console
  `spawnentity` command lists only non-`None` classes — verified from IL),
  and the self-test creature ships a 256×256 albedo. The creature's look
  is its own suite (`shamwayselftest_shamwaySelfTestCreature_look`), not
  stacked with every other prefab. The default `playtest-synthesized` run
  asserts the creature's texture loads at its authored size.
- `examples/SelfTestMod` ships a hierarchy (`timedNuke` / `armedLamp`), a
  skinned `gear` prefab, and a looping `burst` VFX graph whose cards come
  from `shamway generate particle-card` (haze flash/smoke, streak sparks).
  `playtest-synthesized` runs `shamwayselftest_editorless` and asserts the
  live client found the named child, bound both skinned bones, and
  instantiated the particle prefab. Visual sign-off of the looping VFX is
  `playtest-synthesized.sh --look` (`shamwayselftest_burst_look` only —
  never comma-listed with `*_block_*`, never stacked with other prefabs).
- The entity lane: `shamway generate rig` emits a bone-structure template as
  a glTF armature (a shipped 20-bone `humanoid` rig, any custom spec, rigid
  validation), and `shamway generate entity` skins procedural primitives to a
  rig and writes the `entityclasses.xml` patch (mandatory `Prefab` + `Mesh`
  bundle URI). Both feed the writer's skinned lane, and the generated
  prefab is proven by UnityPy read-back.
- Seven more shipped rigs, each with its own default part set:
  `quadruped` and its `quadruped-small`/`quadruped-large` size variants
  (one-line `"base"` + `"scale"` specs), `bird`, `dinosaur`, `arachnid` and
  `crocodile`. A rig spec can now carry `"scale"` and extend another rig by
  `"base"`, and both generators take `--scale` on top — bones and parts
  scale together.
- The self-test fixture (`examples/SelfTestMod`) now carries a generated
  skinned entity beside the prop: `playtest-synthesized` asserts in a live
  client that the entity prefab comes back with its `SkinnedMeshRenderer`
  and that its weighted mesh loads with its vertex stream, and `validate`
  cross-checks the entity's `entityclasses.xml` URIs against the manifest.
- Editorless `bundle_source = "synthesized"` now writes named glTF prefab
  hierarchies (including an `armedLamp` child), `SkinnedMeshRenderer` from a
  glTF skin (bind poses, weights, bone-name hashes; never flattened to
  MeshRenderer), and ParticleSystem / ParticleSystemRenderer graphs from a
  versioned `.vfx` declaration, with transparent and additive particle
  shaders that do not reuse the opaque `Shamway/Unlit` pass.

### Changed

- Usage docs for this session's surfaces: `docs/authoring/vfx.md` field
  reference and `--look` recipe; `no-unity.md` `.vfx` membership;
  `validation.md` `PLAYTEST_CONCERN_SUITES`; `consumer-api.md` /
  `quickstart.md` synthesized vs `--look`; troubleshooting for mixed
  suites and the unsigned-off burst haze.
- The self-test `burst` look stages flash, smoke and sparks as one prefab
  (that is allowed). They used to share one origin, so the additive gold
  flash hid the other layers. Each system now has a distinct
  `shape.position` (smoke left, flash centre, sparks right).
  `docs/authoring/vfx.md` documents that as the reusable `.vfx` surface
  (`shape.position` / `shape.rotation`, `shamway generate particle-card`);
  any synthesized mod uses the same commands. Grey haze is still not
  readable at `--look` — parked as improvements.md §8.
- AGENTS.md and CONTRIBUTING.md state the uv rule as a run contract: bootstrap
  **this** checkout, then `uv run --project . shamway` / `.venv/bin/shamway`.
  A sibling clone's venv or the system interpreter is a different environment.
- One concern per playtest run: `playtest-synthesized` declares its
  default trio as `PLAYTEST_CONCERN_SUITES` so the harness can refuse an
  undeclared comma-list of unrelated features. `--look` is a separate
  invocation. A child that is part of a built prefab is not a second
  suite.
- `make check` enables the ruff rule groups the tree already passed
  (debugger leftovers, builtin shadowing, naive datetimes, blanket
  ignores, and the pie/return/raise/logging/version-compare sets) and
  extra mypy codes (bare `# type: ignore`, truthy-bool, possibly-undefined,
  exhaustive-match, and related) plus `strict_bytes` and
  `strict_equality_for_none`.

### Fixed

- The entity lane's "the generated creature is invisible because `Shamway/Unlit`
  does not skin" conclusion was **refuted** (research-provenance, improvements,
  entities, no-unity). A re-run of `verify-bundle --draw` (editor 2022.3.62f2)
  shows the four generated entities draw 6–26% with `Shamway/Unlit` as-is; only
  the flat two-bone `gear` fixture rasterizes nothing, and its own material
  draws on a built-in cube. `Game/SDCS/Skin` (the shader the earlier live swap
  called "the player's skinning shader") binds **no** blend channels in any of
  its 198 d3d11 vertex sub-programs — it draws the mesh in bind pose and does
  not skin — so that swap proved the mesh is renderable, not that a shader must
  skin. Authoring GPU skinning into `Shamway/Unlit` is therefore not the fix;
  the live-client creature invisibility is a separate, un-diagnosed problem.
- `docs/authoring/environment-effects.md` no longer tells a mod to set
  `bundle_source = "unity"` for the particle character layer. That layer is a
  `.vfx` declaration on the synthesized path; weather itself still needs no
  bundle.
- Bone-name hashes are CRC-32 of the slash-separated Transform path starting
  at `Origin` (`Origin/Hips` is 1722913273, matching nomad.bundle
  `bodyCloth`), not of the leaf GameObject name.
- `pack_directory` no longer swallows a glTF parse error and flatten a
  broken skin to MeshRenderer. A skin whose joints are out of range fails
  the pack.
- `playtest-synthesized.sh` asserts the self-test mesh at its authored
  1 × 1 × 1 m bounds, and runs `shamwayselftest_block_model` so the prop is
  `SetBlockRpc`'d onto a grounded voxel and looked at there (AtomicDoomsday's
  placed bomb/detonator pattern). The previous look case instantiated the
  prefab 1.2 m in front of the camera, and the block-model suite then yanked
  the ModelEntity into the same spot.
- Generated prefab look cases are **one suite per prefab**
  (`<mod>_<stem>_look`), 3.5 m off the camera, and call
  `CaseDef.RegisterStaged` so instances cannot overlay. Putting every mesh
  in one `*_look` suite stacked a particle system, a skinned mesh and a cube
  on the same point. `<mod>_bundle` is loads only. An undeclared comma-list
  of suites is refused; `*_look` with `*_block_*` is refused even when
  declared. A ModelEntity block is judged by placing it.

- Shared-client lock heartbeats are parsed the way `7dtd-playtest` writes
  them (Z, numeric epoch, offset, naive-as-UTC). A `running=yes` record whose
  stamp cannot be read stays held, so a live claim is not overwritten.
- `latest_client_log` accepts a log whose mtime falls in the launch's whole
  second, so a 1-second-resolution filesystem no longer reports "the client
  did not start" for a client that did.
- Capture `captured_at` is the file mtime in UTC regardless of the host
  timezone, including during EDT in `America/New_York`.
- `playtest-capture.sh` times its wait against `/proc/uptime`, so an NTP
  step cannot fire or stall the 900s timeout.
- `doctor` and `build` locate Windows Build Support from the editor binary's
  real assembly root (`Editor/Data` on Linux and Windows, `Unity.app/Contents`
  on macOS) instead of always looking next to the executable.
- Scratch directories honour the host cache directory (`~/Library/Caches` on
  macOS, `%LOCALAPPDATA%` on Windows) when `XDG_CACHE_HOME` is unset.
- The zmol-v search and `install-tools.sh` copy the shared library Zig actually
  emits (`.so` / `.dylib` / `.dll`), not only `libzmolv.so`.
- `render-icon` passes `-force-glcore` only on Linux, where Xvfb needs it;
  macOS and Windows editors keep Metal and D3D11.

## [0.2.0] - 2026-08-26

### Added

- `acceptance-provider` operation and `shamway acceptance-provider` command:
  generates the 7dtd-playtest scenario provider that loads every bundle member
  through the game's own `DataLoader` in a live client.
- `check-texture` operation (`shamway check-texture`): checks a generated
  texture against what generation actually gets wrong — its mean colour against
  the `material.color` it replaces, compared in sRGB.
- `review-audio` / `review-video` operations (`shamway review-audio`,
  `shamway review-video`): advisory model-assisted semantic review of a clip or
  recording; refuse without explicit network consent and never replace the
  human listen or look.
- `ConfigNotFoundError` in the package's public exports, so scripts can catch
  a missing `.shamway.toml` without catching every pipeline error.
- `make locked`, run by `make check`: fails when `uv.lock` has drifted from
  `pyproject.toml`, which is what every CI job dies on.

### Fixed

- Every CI job had failed at install since the version became dynamic:
  `uv.lock` still recorded a literal `0.1.0` and `uv sync --locked` refused it.
- `make check test` never returned. `test_the_wait_expires_and_names_the_stale_log`
  mocked `time.monotonic` to a constant and `time.sleep` to a no-op, so
  `latest_client_log`'s poll loop spun forever. That file now runs in 0.004s.
- A built wheel shipped stale documentation and host scripts. The sdist
  carried no top-level `docs/` or `scripts/`, so `setup.py`'s staging step
  found nothing and silently kept whatever was already staged in the build
  tree. `MANIFEST.in` grafts the sources and prunes the staged copies, and
  the release workflow now compares the built wheel against the tagged tree.
- The coverage-badge step ran `git remote add origin` outside the `else`
  branch its comment places it in, so it also ran on the clone path, where
  the remote already exists, and failed the step under `set -e`.
- CI ran under the implicit `bash -e`, which has no `pipefail`, so
  `shamway build | tee log` reported `tee`'s exit code and passed on a
  failed build.

### Changed

- Scratch work is staged under `$XDG_CACHE_HOME/shamway` (`~/.cache/shamway`)
  instead of `/tmp`, which is tmpfs on most Linux hosts. This covers the
  decoded WAV, the rasterized sheet, the Blender render, the three shader
  compiles, and the multi-gigabyte editor archive `install-unity-editor.sh`
  downloads. An exported `TMPDIR` is respected.
- The shell scripts and the CI workflow call sibling `.py` helpers instead of
  embedding Python in heredocs and `python -c`, so each file stays one
  language and the CI assertions are linted and type-checked like the rest of
  the tree.

## [0.1.0] - 2026-08-24

Initial tagged release: synthesized UnityFS bundle writing with no editor,
offline gates (revision match, class-142 object, stem collisions, mesh UVs,
clip format, icon atlas), the `shamway` CLI and its JSON operation surface,
and the scaffolded standalone modlet layout.
