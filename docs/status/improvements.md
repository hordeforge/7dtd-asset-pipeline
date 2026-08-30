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

## 2. Localization keys are not reconciled

`icon_check` already reconciles every `CustomIcon` and `display_entry icon=`
key against atlas PNGs. The text half of that idea is missing: a
`display_name` or tooltip key referenced by item/block XML is not checked
against `Config/Localization.csv`, and `Localization.Get` returns the key
itself on a miss — so the symptom is raw keys in UI, not an error.

**Close it with:** the same reconciliation shape as `icon_check`: collect
localization keys referenced by the mod's XML, subtract what the CSV provides,
and fail the difference. Vanilla keys resolve through the game's own table, so
the check needs a `--allow-vanilla-keys` default, not an exception list.

## 3. ModInfo.xml Version is unread

Only `<Name>` is compared with `.shamway.toml`. A stale `Version` attribute
ships silently; the client logs it and nothing here notices. Cheap fix, low
value alone — worth doing together with a `ModInfo.xml` schema check
(required attributes present, `Description` non-empty) rather than alone.

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

## 5. No property-based testing of the parser

`unityfs.py`'s rejection fixtures are hand-built vectors — good ones, but
fixed. The parser is the foundation every gate stands on, and a format reader
is exactly the code where generated inputs pay: random truncations, flipped
lengths, hostile string tables.

**Close it with:** [Hypothesis](https://hypothesis.readthedocs.io/) strategies
built on `tests/fixtures.py`'s field-controlled builders — corrupt one field
at a time, assert a bounded error naming the field, never a traceback. No new
dependency in the core: it belongs in a dev extra.

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
