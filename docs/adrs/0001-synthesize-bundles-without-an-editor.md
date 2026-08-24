# ADR 0001 — Synthesize bundles without an editor

Status: **Accepted** (2026). The page below is the original design record,
written as research *before* the writer existed and kept as written — including
the one prediction that did not survive measurement.

## Building a bundle with no Unity anywhere

[no-unity.md](../bundles/no-unity.md) answers "where does the `.unity3d` come from" four
ways: a local editor, **this tool**, an editor elsewhere, or no bundle at all.
This page is the design record for the second one — synthesizing the bundle
here, with no editor involved at any point.

It was written as research *before* any of it existed, and is kept as the
record of what was expected against what was measured. **It ships now**:
`bundle_source = "synthesized"` builds textures, clips and text files, and
`shamway pack` does the same outside any mod. What did not survive contact with
the format is marked below; the one prediction that was wrong is marked
**measured**, because a research page that quietly edits itself to match the
outcome is worth nothing next time.

The user directed that the mode be exposed rather than held behind the
phase-4 gate at the bottom of this page. That deviation is deliberate and
recorded here and in [blockers.md](../status/blockers.md): every synthesize prints what
its gates are worth, and the fresh-client acceptance is still owed.

## Why this is tractable at all

A 7DTD modlet bundle is the friendliest possible case for an offline writer:

1. **It contains only built-in classes.** A modlet prefab is GameObjects,
   Transforms, MeshFilter/MeshRenderer or skinned variants, AudioSource,
   colliders, ParticleSystems, Materials, Meshes, Texture2Ds and AudioClips.
   No MonoBehaviours from the mod means the classic offline-writer wall —
   generating a valid MonoScript hash for a class the file has never seen
   ([AssetsTools.NET wiki](https://github.com/nesrak1/AssetsTools.NET/wiki/Advanced:-Adding-new-MonoBehaviours))
   — never applies.
2. **The installed game publishes authoritative typetrees.** The game's own
   shipped bundles carry type trees *on* (`Entities/trees`, measured:
   serialized platform 19, UnityFS flags `0x243`; see
   [research-provenance.md](../research/research-provenance.md)). Every class layout the
   writer needs can be harvested read-only from the install the player already
   has, rather than guessed from community notes. A wrong guess about a field
   order becomes impossible if the writer refuses to serialize any class whose
   typetree it did not harvest.
3. **The container object's required shape is known and small.** Exactly one
   class-142 `AssetBundle` object per bundle, `m_RuntimeCompatibility: 1`,
   `m_PathFlags: 7`, a populated `m_Container` (path → PPtr) and
   `m_PreloadTable`. This is what the class-142 gate already asserts, derived
   from the game's own bundles (research/research-provenance.md, "Class-142 finding").
4. **Prior art exists at every layer.** See the table below.

## Prior art

| Tool | What it proves | License | Notes |
|---|---|---|---|
| [AssetsTools.NET v3](https://github.com/nesrak1/AssetsTools.NET) | read+write of SerializedFiles and UnityFS archives; adding whole new objects via typetree-driven fields (`AssetsReplacerFromMemory`); LZ4 repack (`Pack(writer, AssetBundleCompressionType.LZ4)`); new MonoScript creation is the one documented gap (irrelevant here, point 1 above) | MIT | C#/.NET; UABEA is its GUI |
| [UnityPy](https://github.com/K0lb3/UnityPy) (already a capability here) | edit-and-save round trip in Python: parse → modify via typetree dict/class → `env.file.save()` re-serializes the archive; custom block compression hooks | MIT | primarily a patcher; creating files from scratch is not its design centre |
| [Fmod5Sharp](https://github.com/SamboyCoding/Fmod5Sharp) | FSB5 banks can be rebuilt from decoded samples (PCM; Vorbis with care) — the write-side counterpart of python-fsb5 | MIT | C# |
| [FMOD FSBank API](https://www.fmod.com/docs/2.03/api/fsbank-api.html) | official builder of FSB5 from WAV/PCM | FMOD EULA | binary redistribution terms need review before depending on it |
| [python-fsb5](https://github.com/HearthSim/python-fsb5) | documents the FSB5 container layout by parsing it; PCM8/16/32 rebuild path shows the exact header fields | MIT | read-only itself |

## What the writer would have to produce

In dependency order, per lane:

- **Container** (always): UnityFS header with the game-matched revision string,
  block table (LZ4 block compression; the encoder side of what `unityfs.py`
  decodes), one `CAB-<hash>` SerializedFile with platform 19 metadata and type
  trees, and the class-142 object whose `m_Container` lists every asset path.
- **Mesh lane**: `Mesh` objects are fully documented layouts (vertex/index
  streams, AABBs, blend shapes absent for props). The existing `check-mesh`
  gate keeps authored glTF honest *before* conversion, so the converter's input
  quality is already gated.
- **Texture lane**: RGBA32/BGRA32 or DXT-encoded `Texture2D` with `.resS`
  stream data; sizes and formats are measurable, so acceptance evidence is
  cheap.
- **Material/prefab lane**: GameObject + Transform + components + Material
  with correct shader keywords. Two sub-options:
  - author every field (risky: the keyword traps in
    [bundle-generation.md](../bundles/bundle-generation.md#script-authored-materials)
    exist precisely because half-set materials pass every check but render
    wrong), or
  - **clone-and-patch**: harvest complete vanilla `Material` objects from the
    installed game's bundles (read-only) and patch only texture PPtrs, colours
    and tiling. The bytes around the patches come from Unity's own serializer,
    which is exactly the fidelity a hand writer cannot give.
- **Audio lane (predicted hardest — measured: built and loading)**:
  `AudioClip.m_Resource` holds an FSB5 bank, and Vorbis encoding without FMOD
  is indeed not realistic. PCM16-in-FSB5 turned out to be enough: the writer
  emits mode 2 (PCM16), one sample header, `m_CompressionFormat: 0`, and FMOD
  inside a real Unity 2022.3.62f2 runtime decoded it to the right channel
  count, frequency and sample count. The bank layout was taken from the
  `.resource` stream of a bundle this repository's own editor built from the
  same WAV — the 64-bit sample header's frequency index, channel bit, data
  offset and sample count decoded exactly as the file predicted. A rate outside
  FMOD's frequency table is refused with the `ffmpeg` line that fixes it,
  rather than written with a wrong index.

## The evidence problem, stated plainly

Every offline gate survives unchanged — they read the artifact, not its
author. But two change *meaning* when the artifact is our own output:

| Gate | On editor-built bundles | On synthesized bundles |
|---|---|---|
| class-142 container | independent evidence the engine got a real container | true by construction; structural, not evidentiary |
| disabled-module log gate | catches Unity stripping modules while reporting success | cannot run — there is no build log; module stripping cannot happen because nothing was stripped, but neither is there proof the object graph is one the runtime accepts |
| game-revision gate | independent | still meaningful: rejects a writer misconfigured for another revision |
| stem-collision gate | independent (manifest-based) | runs over the writer's own membership record — same by-construction caveat as class-142 |

So for a synthesized bundle **the fresh client stops being confirmation and
becomes the only acceptance**, which is why this stays unbuilt until its
evidence plan exists. The bar, from AGENTS.md and [no-unity.md](../bundles/no-unity.md):

1. generated fixtures for **acceptance and rejection** (a writer that can only
   produce files its own reader accepts has not been tested);
2. structural comparison against an editor-built bundle carrying the same
   assets — same class table, same container entries, same object count;
3. a fresh-client load of a synthesized probe bundle **before** the mode is
   exposed in `shamway init`;
4. the report language may never say "built"; it says **synthesized**, and
   every command touching it prints that fresh-client acceptance is mandatory,
   the way `stage` prints `not run:` lines.

This host happens to have editors installed, which makes phases 1–2 runnable
here without waiting on anyone.

## What shipped

| Piece | Where | State |
|---|---|---|
| UnityFS container writer, SerializedFile v22 with type trees | `bundle_writer.py` | built; the mirror of `unityfs.py` |
| typetree-driven object serialization | `bundle_writer.py`, via UnityPy's per-version database | built; a class without a tree is refused, never guessed |
| class-142 `AssetBundle` object and its `m_Container` | `bundle_writer.py` | built; field values taken from the game's own bundles |
| `Texture2D` (RGBA32, inline pixels, bottom-up rows) | `bundle_writer.texture_2d` | built; pixels read back correctly through a real runtime |
| `AudioClip` (PCM16 in an FSB5 bank in a `.resource` node) | `bundle_writer.audio_clip` | built; decoded by FMOD in a real runtime |
| `TextAsset` | `bundle_writer.text_asset` | built |
| source directory -> bundle + Unity-shaped manifest | `bundle_writer.pack_directory` | built; `validate` cannot tell the backends apart |
| `bundle_source = "synthesized"`, gates, staging | `build.synthesize_bundle` | built; prints what its gates are worth |
| `shamway pack`, `shamway verify-bundle` | `cli.py`, `bundle_verify.py` | built |
| mesh, prefab, material, shader | — | **not built, and not planned as-is**: see below |

The shader is the wall, not the effort. A material references a shader, and a
shader in a bundle is compiled platform bytecode from Unity's shader compiler.
Nothing offline produces that, so a synthesized prefab renders magenta — a
failure no offline gate can see. The clone-and-patch idea above (harvest a
complete vanilla `Material` from the installed game read-only, patch only
texture PPtrs and colours) is the only route that could change this, and it is
recorded, not attempted.

## What the evidence turned out to be

The phased plan below expected structural comparison against an editor-built
bundle as phase 2. What was available was better, and was used instead: a real
Unity 2022.3.62f2 runtime **loading** the synthesized bundle
(`AssetBundle.LoadFromFile`, the call the game makes) and deserializing every
object with the engine's own class definitions. Measured, 2026-08-23, on a
bundle `shamway build` staged with no editor in its path:

```text
synthblast: AudioClip named 'synthBlast'  [channels=1 frequency=44100 samples=4410 seconds=0.1]
synthdata:  TextAsset named 'synthData'   [18 bytes]
synthpanel: Texture2D named 'synthPanel'  [4x2 RGBA32 readable=False]
```

That check is `shamway verify-bundle`, and it is the only offline check in this
repository that this repository did not also author. It is not acceptance: it
proves the container and object graph survive a runtime of that revision, not
that 7DTD loads it or that the asset is right.

### Why a Unity runtime is not the game

The gap between the two is three pieces of engine code that only the game runs,
all decompiled from V 3.1.0 b14 (see
[research-provenance.md](../research/research-provenance.md)):

| Step | What it does | What a runtime load skips |
|---|---|---|
| `ModManager.PatchModPathString` | rewrites `@modfolder(Name):` to the loaded mod's path | the mod-name lookup, and its `[MODS] Mod reference for a mod that is not loaded` failure |
| `AssetBundleManager.LoadAssetBundle` | opens the archive and caches it per path for the process | the game's own opener, and the session-lifetime cache behind the fresh-client rule |
| `AssetBundleManager._get` | reduces the request to its file-name stem | the class-142 `m_Container` table, which is the only thing a stem lookup reads |

`AssetBundle.LoadFromFile` in a bare runtime touches none of them. That is why
the fresh client is the acceptance for a synthesized bundle and not a
confirmation of it, and why `shamway acceptance-provider` exists: it generates
a `7dtd-playtest` scenario provider whose cases call
`DataLoader.LoadAsset<T>` — the entry point the whole chain hangs off — once
per manifest entry, inside the live client, plus one stem the bundle does not
contain that must come back null. Running it is
`scripts/playtest-acceptance.sh`. Even a full pass is not a verdict on the
asset: it says the game read the bytes, never that they are the right bytes.

## Phased plan

- **Phase 0 — this page.** Research recorded; nothing implemented.
- **Phase 1 — fixture harvesting.** A script that reads typetrees and minimal
  exemplar objects out of an installed game's bundles into test fixtures
  (read-only; the install is never written). Proves the reader/writer agree
  with the game's own serializer on real layouts.
- **Phase 2 — probe parity.** Reproduce `build --probe`'s cube bundle through
  the clone-and-patch path from a committed template; assert structural
  equality with the editor-built original. Still invisible to users.
- **Phase 3 — fresh-client proof.** Deploy a synthesized probe behind
  `client deploy`/`launch`; classify the log; human look. Only a pass here
  earns phase 4.
- **Phase 4 — surface it.** `bundle_source = "synthesized"` in config,
  registered in `BUNDLE_SOURCES`, wired through doctor/status/build, an entry
  in `capabilities.REGISTRY` for whatever optional library the writer leans on
  (UnityPy is already one), docs updated, gates' by-construction caveats
  printed in reports.

Phases 1–3 produce fixtures and evidence even if phase 4 is never reached;
none of them touch the command surface.

**Outcome:** phase 1 was met by harvesting layouts from the game's own bundles
and from an editor-built reference bundle; phase 2 was met by a stronger check
(a runtime load, above) than the structural comparison it asked for; phase 4
was surfaced ahead of its evidence at the user's direction.

**Phase 3 is done, as of 2026-08-24.** 7 Days to Die V 3.1.0 b14 loaded a
synthesized bundle through `DataLoader.LoadAsset<T>`, by stem, and returned a
`512x512 RGBA32` texture and an `AudioClip` FMOD decoded from the hand-written
FSB5 bank — `channels=1 frequency=44100 samples=20727`. A fourth request for a
stem the bundle does not contain returned `null`, so the passes are not a
loader answering everything. The evidence and the exact log lines are in
[blockers.md](../status/blockers.md) entry 6; the run is repeatable with
`scripts/playtest-acceptance.sh`.

A reviewer then looked and listened in that client and reported the texture as
a centred, circular ring and the clip as three clean beeps. That closes the
plan's phase 3 completely, and it is worth naming what the person added over
the suite: *not stretched* and *not crackling*. Neither is visible to an
offline gate or to a case that only asks whether the object loaded.

The plan's own wording is worth keeping honest about the order, though: it
called phase 3 "a fresh-client load ... **before** the mode is exposed". The
mode shipped first, at the user's direction, so this is evidence arriving late
rather than a gate that held.

## Sources

- AssetsTools.NET v3 wiki: bundle writing, assets-file writing, adding
  MonoBehaviours (the documented gap we do not hit) — fetched 2026-08-23.
- UnityPy README (edit/save contract, custom compression hooks) — fetched
  2026-08-23.
- python-fsb5 / TriMO-FSB5 (FSB5 layout, PCM rebuild), Fmod5Sharp (FSB5
  rebuild), FMOD FSBank API (official builder) — fetched 2026-08-23.
- Game-shipped bundle facts (platform 19, flags `0x243`, type trees on,
  class-142 contents): this repository's own measurements, recorded in
  [research-provenance.md](../research/research-provenance.md).
