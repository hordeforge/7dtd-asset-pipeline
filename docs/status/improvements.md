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

The editorless writer stores textures as raw RGBA32 and clips as PCM16 in
FSB5. Both are correct — the runtime verified both — and both cost size:
RGBA32 is roughly 4–8x a block-compressed format, PCM16 roughly 10x Vorbis at
music rates. A mod shipping many icons or long clips through the synth path
pays for that in download size, not correctness.

**Close it with:** encoders, each independently gated —

- textures: DXT1/DXT5 (and later BC7) via [`bc7enc_rdo`](https://github.com/richgel999/bc7_enc_rdo)
  or [Compressonator](https://github.com/GPUOpen-Tools/compressonator); the
  writer already has the object layout, only the pixel block changes;
- audio: FSB5+Vorbis needs a Vorbis encoder plus FMOD's seek-table quirks —
  [Fmod5Sharp](https://github.com/SamboyCoding/Fmod5Sharp) rebuilds banks and
  is prior art; harder than textures, still bounded.

Until then the advice stands: big or quality-critical audio goes through the
`unity`/`external` path where Unity's importer encodes Vorbis, and the synth
path carries short clips and utility sounds.

## 4b. The editorless writer stops at shaders, materials and prefabs

This entry exists because the documentation used to say this was impossible.
It is not; it was never checked. See
[research-provenance.md](../research/research-provenance.md), "A material's
shader", and the AGENTS.md rule that came out of it.

What is actually closed: **borrowing** a shader. The shipped player carries
six shaders and all are internal, and the game's own bundles embed theirs
`m_Shader.m_FileID: 0`, same-file. A mod bundle must therefore carry its own.

What is open, with the pieces already on the shelf:

| Piece | Status |
|---|---|
| `Shader`/`Material`/`GameObject`/`Transform`/`MeshFilter`/`MeshRenderer` type trees at this revision | available, same UnityPy TPK source the writer already uses for `Mesh` |
| HLSL → SM4/SM5 **DXBC** (what d3d11 sub-programs carry) | [`vkd3d-compiler`](https://gitlab.winehq.org/wine/vkd3d) — WineHQ, MIT, `dxbc-tpf` target |
| GLSL/HLSL → **SPIR-V** (Vulkan sub-programs) | `glslangValidator`, and [Slang](https://github.com/shader-slang/slang) or [DXC](https://github.com/microsoft/DirectXShaderCompiler) as alternatives |
| Sub-program blob container | **decoded** from `Entities/trees`: LZ4 per platform, `u32 count` + 12-byte `(offset, length, segment)` records, code blobs an 8-`u32` header then `DXBC`. Cross-checked against AssetStudio and UnityPy, which both parse it |
| Prior art for the format | [AssetStudio `ShaderConverter.cs`](https://github.com/Perfare/AssetStudio/blob/master/AssetStudioUtility/ShaderConverter.cs), [UnityPy `ShaderConverter.py`](https://github.com/K0lb3/UnityPy/blob/master/UnityPy/export/ShaderConverter.py) — read-side implementations, which is a specification for the write side |
| Cross-object `PPtr` wiring inside one synthesized file | **not built** — `build_bundle` assigns path ids by position and no constructor references another object yet. This is the first thing to add, and prefabs need it regardless of shaders |

**Close it with**, in this order, because each step is verifiable on its own:

1. `PPtr` support in `build_bundle`, proven by a `Material` → `Texture2D`
   reference read back through UnityPy;
2. a `GameObject` + `Transform` + `MeshFilter` + `MeshRenderer` prefab over an
   already-working `Mesh`, with an empty material slot — loadable, invisible,
   and honest about it;
3. the smallest possible shader: one unlit textured pass, HLSL compiled by
   `vkd3d-compiler`, wrapped in the container above. `shamway verify-bundle`
   is the gate — a real runtime reports `Shader.isSupported`, which is the
   first mechanical answer to "did this work";
4. only then a `Material` that binds it, and only then a claim about rendering
   — which, as everywhere else here, ends at a person looking at a client.

**What is genuinely unknown** (unknown, not impossible): the exact bytes of the
Unity header preceding the DXBC in a code blob, whether 7DTD's rendering path
accepts a minimally-authored pass, and which keyword variants the engine
demands. Each is a measurement against the game's own bundles, not a barrier.

Until it is built, a mod with a prefab or a material uses `bundle_source =
"unity"` or `"external"`, and the documentation says **unbuilt**, never
impossible.

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
