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
