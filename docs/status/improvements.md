# Known gaps and next improvements

What this pipeline does not do yet, why each gap matters, what closes it, and
which open-source tool belongs to it. This is a working list, not a promise:
each item names the gate or surface it touches so an agent can tell whether it
has since been done. Verification-shaped gaps live separately in
[blockers.md](blockers.md); this page owns capability gaps.

Closed recently, kept here so the pattern is visible:

- *Packaged docs drifting from repo docs* — an agent in a mod reads
  `src/sevendtd_asset_pipeline/docs/`, this repository edits `docs/`, and the
  copies had drifted within a day of both existing. Closed by a suite test
  comparing every `TOPICS` page byte-for-byte (`tests/test_assets.py`,
  `DocumentationTests`); it caught seven drifted pages on its first run.

## 1. XML patches are never applied, only scanned

`validate` discovers every bundle URI in `Config/**/*.xml` and checks it
against the tracked manifest, but it never parses a patch file as XML and
never applies one. A patch whose XPath matches nothing — a typo'd attribute,
a renamed parent, a mod load-order surprise — is a silent no-op in the game
and passes every check here. This is the same failure class the stem gates
exist for, on the other half of the Config lane.

**Close it with:** a dry-run that loads the installed game's matching
`Data/Config/*.xml` read-only, applies each mod patch with ElementTree +
the engine's own match semantics, and fails on any `<patch>` selector that
matches zero nodes. Needs the decompiled patch-application rules recorded in
[research-provenance.md](../research/research-provenance.md) first, so the dry-run
implements what the engine does rather than what seems natural. Until then:
grep every XPath you author against `$SEVEN_DAYS_TO_DIE_DIR/Data/Config/`
by hand.

## 2. Localization keys are not reconciled  — **done (2026-08-31)**

**Closed.** `shamway check-localization` is the text half of `icon_check`,
with the same reconciliation shape: it collects every localization key
Config/ references (item/block/entity_class names + bare-token
`display_name`/`Description`/`desc_key`/`tooltip` values), subtracts the mod's
`Config/Localization.csv`, subtracts the game's vanilla table by default
(`--allow-vanilla-keys`, `--no-vanilla-keys` to fail those), and reports the
rest as `missing`. It fails a referenced key in neither table **only when the
mod ships a `Localization.csv`** (a mod that localizes anything clearly meant
to localize this, so a dropped row is a bug); a mod with no CSV reports that
its names are untranslated instead of failing. The engine fact —
`Localization.csv` lives in `Config/` and `Localization.Get(key)` returns the
key itself on a miss — is recorded in `docs/research/research-provenance.md`.

*Why this shape:* a `Description` value of "A sturdy tool" is passed to
`Localization.Get` too, but it is not a key the author must provide (it is
shown as-is on a miss), so only bare tokens (single, no spaces/commas) are
reconciled as keys.

## 3. ModInfo.xml Version is unread  — **done (2026-08-31)**

**Closed.** `validate` now runs `check_mod_info_schema` on `ModInfo.xml`
(`references.py`): `<Version>` must be present and a dotted-numeric version
(`N.N` / `N.N.N`), and `<Description>` must be present and non-empty. A missing
or malformed `Version` ships a stale mod version (the client logs it, a mod
manager shows it); a missing `Description` shows a blank row in the server
list. Neither errors anywhere in the game, which is why the gate is here.
`<Name>` is still compared with the configuration. `read_mod_info` (a small
`ModInfo` dataclass covering Name/DisplayName/Version/Description) backs both.

## 4. The synthesized lanes are uncompressed

**Textures: closed 2026-08-24.** `block_compress.py` encodes BC1 (`DXT1`, 8x)
and BC3 (`DXT5`, 4x) in NumPy with no new dependency, and `texture_2d`
takes it through `compress_textures` in `.shamway.toml` or
`shamway pack --compress-textures`. It is **off by default** because it is
lossy and this pipeline does not quietly change what an author signed off on.

Two traps are designed out rather than documented, and both are in the tests:

- a flat block quantizes to `c0 == c1`, which flips the decoder into
  three-colour mode where index 3 is *transparent black* — holes in an opaque
  texture. Every index in such a block is forced to 0;
- **grading by raw RGB PSNR reports a failure that is not there.** A rendered
  icon's fully transparent pixels carry renderer noise (measured on real
  `generate mesh-icon` output: min 0, max 255, σ 27.7), and BC1's shared
  endpoints spend precision on it. That icon scored 16.9 dB raw and **39.9 dB
  composited**. `visible_psnr` composites first, so the number means what a
  viewer sees.

Evidence: our blocks decode **byte-identically** in `texture2ddecoder`, the
independent library UnityPy uses on real game textures, and a real Unity
2022.3.62f2 runtime loaded one as `160x160 DXT5`.

Still open, as an upgrade rather than a gap: **BC7**. It has eight block modes
and a partition table, and a mediocre BC7 encoder is worse than a good BC1 one
at the same size, so it is not attempted in Python.
[`bc7enc_rdo`](https://github.com/richgel999/bc7_enc_rdo) (BC1–7 with
rate-distortion optimization, 10–50% further shrink),
[Compressonator](https://github.com/GPUOpen-Tools/compressonator),
[ISPCTextureCompressor](https://github.com/GameTechDev/ISPCTextureCompressor)
and [`ctt`](https://github.com/cwfitzgerald/ctt) are the CLIs for it. None is
packaged on Arch, Debian or Fedora, so wiring one means asking a user to build
from source — worth doing when a mod's texture budget actually demands BC7,
not before.

**Audio: still open.** FSB5+Vorbis needs a Vorbis encoder plus FMOD's
seek-table quirks — [Fmod5Sharp](https://github.com/SamboyCoding/Fmod5Sharp)
rebuilds banks and is prior art; harder than textures, still bounded. Until
then: big or quality-critical audio goes through the `unity`/`external` path
where Unity's importer encodes Vorbis, and the synth path carries short clips
and utility sounds.

## 4b. The editorless writer's shader scope

This entry exists because the documentation used to say a shader was
impossible offline. It was never checked, and it was wrong. It has now been
built: see [research-provenance.md](../research/research-provenance.md) and
the AGENTS.md rule that came out of it.

**Done, 2026-08-24.** One unlit textured pass, authored with no editor:

| Piece | Status |
|---|---|
| `PPtr` wiring inside one synthesized file | **built** — `bundle_writer.Ref(key)`, dangling references refused by name |
| `GameObject`/`Transform`/`MeshFilter`/`MeshRenderer` prefab | **built** — `bundle_writer.mesh_prefab` |
| Sub-program blob container | **decoded upstream** — `hordeforge/7dtd-engine-research`, [`docs/shader-subprogram-blob.md`](https://github.com/hordeforge/7dtd-engine-research/blob/main/docs/shader-subprogram-blob.md), gated by its `tools/shader_blob_dump.py` |
| the 38-byte program-data header | **decoded** — header version, then the SRV, constant-buffer and sampler counts, over 7366 sub-programs |
| the parameter blob | **decoded** — 3403 stock records re-emitted byte for byte |
| the bind-channel block | **decoded** — and it was the one thing standing between a structurally valid shader and a loadable one |
| HLSL → SM4 `DXBC` | **built** — `vkd3d-compiler`, `dxbc-tpf` |
| `Shader` (class 48) | **built** — `bundle_writer.shader`, `shader_blob.py` |
| `Material` (class 21) | **built** — `bundle_writer.material` |
| prefabs in the source-directory lane | **built** — `bundle_writer.prefab_objects`; a mesh file becomes prefab + mesh + material, sharing one shader |
| runtime evidence | **superseded twice over** — the `-nographics` `isSupported = true` first recorded here was withdrawn, then a real device measured `isSupported=True` with pixels drawn (`covered=38.8%`), then a live client was looked at: the prop is visible, textured and solid |

**What is built is a working shader on two of the three desktop platforms.**
The `Shader` and `Material` objects serialize, load, wire to the prefab by
name, and draw: signed off by eye in a live client on OpenGL Core, and on
Direct3D 11 after the constant-buffer layout fix recorded in
[blockers.md](blockers.md). The remaining graphics-API gap is Vulkan's
parameter records — [measured at the bottom of this page](#the-vulkan-sub-program-and-what-is-left-of-it).

**Particle transparent/additive (2026-08-30).** `Shamway/Particles/Alpha` and
`Shamway/Particles/Additive` are a second unlit pass: vertex COLOR0 ×
`_MainTex`, SrcAlpha / OneMinusSrcAlpha or SrcAlpha / One, ZWrite 0, cull
off, queue 3000. They do not reuse the opaque One/Zero mesh pass.

**What is deliberately not built.** Lit, shadowed, cut-out, normal-mapped,
instanced and multi-pass shaders need keyword variants and constant buffers
this writer does not declare; a mod that needs one wants `unity` or
`external`. Particle modules beyond the `.vfx` schema (trails, collision,
noise, lights, sub-emitters, mesh particles) are the same. "Shaders work"
would be a wider claim than the evidence supports.

**~~Skinned meshes are not rendered by `Shamway/Unlit`~~ REFUTED (2026-08-31).**
This entry was written from the same two misreadings the provenance
"Convention found" block had, and it is wrong. `verify-bundle --draw` re-run on
a freshly re-synthesized `shamwayselftest.unity3d` (`7b12af4`, editor 2022.3.62f2)
shows the four generated entities **draw with `Shamway/Unlit` as-is**: creature
15.2%, arachnid 26.0%, bird 6.1%, dino 9.1% coverage, all `SetPass(0)=True`. The
only prefab rasterizing nothing is the `gear` fixture (0.0%) — and its own
material draws fine on a built-in cube (`VERIFY-DRAWN-MATERIAL ... covered=8.4%`,
`SetPass(0)=True`), so `gear`'s blank is a geometry/bind-pose-framing artifact of
that flat two-bone test mesh, not a shader defect. `Game/SDCS/Skin` (the shader
the live swap called "the player's skinning shader") binds **no** blend channels
in any of its 198 d3d11 vertex sub-programs — it draws the mesh in bind pose and
does not skin — so the live swap proved the mesh is renderable, **not** that a
shader must skin. Authoring GPU skinning into `Shamway/Unlit` is therefore **not
the fix**. The live-client creature invisibility is a separate, un-diagnosed
problem; see the near-verbatim correction in
[research-provenance.md](../research/research-provenance.md) (the "CORRECTION"
section) and `docs/authoring/entities.md`.

**RE status (2026-08-31, superseded): the fix is shader-only, and it is Unity
*standard* skinning.** This, too, is wrong — it was built on the refuted
"Convention found" conclusion. The real bind-channel evidence (from
`tools/shader_blob_dump.py` in `hordeforge/7dtd-engine-research` on
`Game/SDCS/Skin`'s 424 records) is: no vertex sub-program binds a blend source
(mesh channel 5/6/7 or BlendWeight/BlendIndices 12/13); the only bind tables are
`(0,0)(1,1)(2,2)(4,5)` and `(...)(3,3)(4,5)`. The earlier "zero shaders with more
than the four base channels" survey and the "it must be Unity standard GPU
skinning" route both follow from reading the *input signature* as the *bind
channels*. The open item is not "reproduce a skinning convention" — it is to
diagnose why the same bundle that draws in the editor draws nothing in a fresh
Proton/d3d11 client (the d3d11 `Shamway/Unlit` cbuffer layout is ruled out by
the prop drawing 81.4% through the same shader).

**TODO (2026-08-31): the synthesized `SkinnedMeshRenderer` + `Shamway/Unlit`
does not rasterize in the live client. Diagnose it as a d3d11-specific draw
failure.** This is the live step the entity lane's invisibility reduces to, and
everything else has been measured and ruled out. Do NOT re-hunt the shader,
skin, bone, or grounding paths — each is closed:

- **Repro:** `SEVEN_DAYS_TO_DIE_DIR=/home/yannick/Games/Steam/steamapps/common/7 Days To Die SEVEN_DAYS_TO_DIE_SERVER_DIR=/home/yannick/steam-server-build-3.2 SHAMWAY=.../shamway examples/SelfTestMod/scripts/playtest-synthesized.sh --look shamwaySelfTestCreature` (run from the fixture, env from `.local.env`). Then
  `grep frame-div "…/logs/output_log_client_7dtd_connect.txt"`.
- **What the `frame-div` line says (measured 2026-08-31):** the creature is
  grounded and healthy but absent from every captured frame —
  `getpos=(510.56, 60.05, 942.90)` `tf=(-1.35, 12.05, 14.62)`
  `meshCenter=(-1.35, 12.55, 14.79)` `meshSize=(0.33, 1.04, 0.83)`
  `smrEnabled=True` `verts=1382` `meshActive=True` `rootActive=True`.
  `getpos` vs `tf` is just `World.Origin` (save-frame vs render-frame), NOT a
  drop — the creature is on the terrain at world y≈60 (player at 61). So the
  old "fell off the world / world-vs-render mismatch puts it under the floor"
  theory is wrong.
- **Already ruled out:** skinning (unityz `skin` reports all 59 game shaders
  `skins:false`, so the engine CPU-skins and `Shamway/Unlit` needs no
  bone-matrix stage); authored bones (SMR `m_Bones` all resolve, the mesh's 19
  `m_BoneNameHashes` exactly equal `CRC32(path)`, root = `CRC32("Root")`, the
  `m_BindPose` are the correct inverse-bind matrices, skeleton geometry +
  `Physics` capsule coherent); shader/mesh (the same prefab draws ~15% in the
  editor's `verify-bundle --draw`).
- **The hypothesis to test: d3d11-specific draw failure of a
  `SkinnedMeshRenderer`+`Shamway/Unlit`.** It draws on the editor's OpenGLCore
  path and rasterizes nothing in the live Proton path. To name the API, re-run
  the same `--look shamwaySelfTestCreature` with the client forced onto the
  other graphics backends — **OpenGL (`-force-glcore`) and Vulkan
  (`-force-vulkan`)** via the client launch (7dtd-fastconnect
  `launch_client.sh` / the 7DTD client arg), and compare coverage + the frames.
  If it rasterizes under GL or Vulkan, the defect is isolated to the d3d11
  sub-program; if absent on all three, it is the engine's `SkinnedMeshRenderer`
  path, not the shader.
- **Extend the live probe** (in `7dtd-playtest` `CaseDef.WalkEntity`'s assert,
  or the generated provider) to also log the creature SMR's `sharedMaterial.shader`,
  `shader.isSupported`, `shader.passCount`, and `material.SetPass(0)` — the
  frame-div block already reports bounds/active/verts, so add the shader/draw
  values and re-run to see whether the pass can be set up at all.

**Settled since this entry was written:**

1. **whether 7DTD's own rendering path accepts this pass.** It does. The
   prop places, collides, and renders in a live client — see
   [blockers.md](blockers.md) for the isolation that proved it and the bug the
   look caught;
2. **what it looks like.** A human checked it against an orientation card
   (arrow up, bar along the bottom, stripes left and right, `R` readable): no
   rotation, no mirroring, no stretch. The mesh lane's UVs are exercised too —
   a generated box carries a whole texture, the right way up.

**Still genuinely unknown** (unknown, not impossible):

1. header byte 4 of the program-data header (UAV-related), and the meaning of
   the three empty `m_PlayerSubPrograms` groups. Neither blocks this lane;
   both are recorded upstream as not decoded.

Two closed borrowing routes stay closed and were not re-tested: the shipped
player carries six shaders and all are internal, and the game's own bundles
embed theirs `m_Shader.m_FileID: 0`, same-file. Authoring made borrowing
unnecessary rather than disproving it.

A mod with a prefab or a material needs no editor: `bundle_source =
"synthesized"` writes this shader itself. What stays on the other side of the
line is everything [deliberately not built](#4b-the-editorless-writers-shader-scope)
above, plus the Vulkan parameter records below.

## 5. No property-based testing of the parser  — **done (2026-08-31)**

**Closed.** `tests/test_property.py` drives the UnityFS/SerializedFile reader
with [Hypothesis](https://hypothesis.readthedocs.io/). Four properties, one
invariant each: `inspect_bundle` must either succeed or raise the reader's own
bounded `PipelineError` — never a leaked `struct.error`/`IndexError`/raw
exception, which a caller turns into a traceback instead of a named gate
failure. The strategies generate arbitrary bytes, hostile class IDs, hostile
file node sizes / archive flags / truncation (a valid bundle cut at a
Hypothesis-chosen byte), and hostile LZ4 block payloads. Hypothesis is a
`dependency-group dev` member; without it the class is skipped so a bare
`make test` still passes.

## 6. No runtime helper for the environment lane

[environment-effects.md](../authoring/environment-effects.md) documents the
capture/clamp/restore discipline the weather and sky controls need, and the
sentinel values (`-1f` for the force fields, alpha `0` for the fog colour)
that make a naive reset pin the sky clear and dry. Documented is not enforced:
every mod that ships an environment effect re-implements the same twenty
lines, and the failure mode is invisible — nothing logs, and the player is
left under permanent forced weather.

**Close it with:** a vendored runtime helper, the way the editor scripts in
`scaffold.PIPELINE_EDITOR_SCRIPTS` are vendored — capture once, clamp against
the entry baseline, restore the sentinels, and reset on a world change. The
open question is whether this repository should ship *runtime* C# at all: it
ships editor scripts today, `make check` can only compile against an editor's
assemblies, and a helper that lands inside a mod's Harmony assembly is closer
to mod content than to tooling. Decide that before writing it — it is an
[RFC](../rfcs/), not a patch.

## 7. Tool additions worth their install

The researched stack in [authoring-tools.md](../authoring/authoring-tools.md) covers the
lanes; these are the additions the current gaps argue for:

| Tool | Lane | What it adds here |
|---|---|---|
| [gltfpack](https://github.com/zeux/meshoptimizer) | mesh | quantization and vertex-cache optimization before import; smaller bundles without Unity's optimizer |
| [AssetRipper](https://github.com/AssetRipper/AssetRipper) | research | full vanilla prefab/material/graph export for reference reading — read-only against the install, never copied into a mod |
| [python-fsb5](https://github.com/HearthSim/python-fsb5) | audio | decode any FSB5 (including vanilla `.resource` streams) to WAV for reference listening |
| [Compressonator](https://github.com/GPUOpen-Tools/compressonator) / bc7enc | texture | measure what block compression would save before deciding a clip-or-texture set stays on the synth path |

Each is optional, installable per mod, and belongs behind
`shamway capabilities --json` when one becomes load-bearing for a command —
never guessed at.

## 8. Self-test burst haze is not visible at `--look`

`examples/SelfTestMod` ships a looping `burst` prefab with three systems
(flash, smoke, sparks) as children of one GameObject — the allowed
together-case, not a mix-gate miss. A 2026-08-30 live
`playtest-synthesized.sh --look` (suite `shamwayselftest_burst_look` only)
showed the gold additive flash and the orange sparks. A person looking
could not see grey smoke. Packing and `LoadAsset` of the ParticleSystem
are proven; the haze as a picture is not.

The systems now have distinct `shape.position` values (smoke left, flash
centre, sparks right in camera-local space after the look stages the
prefab facing the lens). That spread is the reusable `.vfx` surface
(`shape.position` / `shape.rotation` in [vfx.md](../authoring/vfx.md)).
It did not make the haze readable: a white `particle-card haze` on alpha
blend, sitting near additive gold, still reads as nothing.

**Close it with:** a `--look` a person can name as grey haze without
being told where to look — likely a darker/denser smoke card, not
another offset. File the frame with
`shamway client capture burst --observable "grey haze left, gold flash centre, orange streaks right"`.
Do not claim the smoke layer works until that capture exists.

## Ordering

If picked up in one pass: **1** (patch dry-run) buys the most silence removed
per line of code; **5** hardens everything else; **4** is two independent
encoders; **2** and **3** are small once 1's XML-loading machinery exists.
**6** is a decision before it is any code.


## The Vulkan sub-program

`bundle_source = "synthesized"` renders on **OpenGL Core**, **Direct3D 11**,
**Direct3D 12** (it consumes the same DXBC as d3d11) and, since 2026-08-25,
**Vulkan**. The Vulkan lane is confirmed in a live client: the acceptance suite
runs to `SUMMARY pass=6 fail=0 skip=0` under `-force-vulkan` with DONE written,
and the captured frame shows the textured card with zero magenta pixels.

What the lane took, all of it measured against the installed game's own
Vulkan records (`Legacy Shaders/VertexLit` and five more in `data.unity3d`):

| | |
|---|---|
| the container | a type-25 code record carrying both SMOL-V modules behind a 176-byte header, `stageCounts` 1 - matches stock |
| the section order | fragment in section A, vertex in B, read from `OpEntryPoint` |
| the 32-byte field | **not validated** - a live client renders a stock blob with every byte corrupted, and a synthesized record with non-stock bytes there |
| descriptor sets | constant buffers in set 1, texture in set 0, as the stock modules declare |
| the SPIR-V producer | glslang, as Unity uses; the fragment authored in GLSL so it is one combined image-sampler like every stock module |
| the bind-channels tail | present, targets are the vertex-input slots + 13 (measured across seven stock shaders) |
| the parameter-record entries | the crash was here: the entry index is `(stage << 24) \| (kind << 16) \| slot` - `_MainTex` at `0x08000000`, `VGlobals` at `0x04010000` with `array_size 0` - see research-provenance.md |

Vulkan is optional in the writer: without the SMOL-V encoder the bundle carries
the two platforms it always did, and the game reaches for platform 18 only
under `-force-vulkan`. The loop to re-check the lane is one command and nobody
watching:

```bash
scripts/playtest-capture.sh --case look_myProp --label vulkan &
scripts/playtest-acceptance.sh --mod-root .
```

Vulkan is optional in the writer, so none of this blocks a mod: without the
SMOL-V encoder the bundle carries the two platforms it always did, and the game
reaches for platform 18 only under `-force-vulkan`.
