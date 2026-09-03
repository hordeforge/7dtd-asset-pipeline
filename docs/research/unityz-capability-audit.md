# Research: unityz capability and migration audit

## Question

Which Unity-format work in this repository can move to `unityz`, can UnityPy
be removed completely, and which apparently similar operations must stay
separate because they prove a different thing?

## Method

The source audit used `unityz` `origin/main` at
`9e39fc48d9c7201d3fab265fddfa3ec26dfd443c` (including PR 121) and this
repository's `origin/main` at
`fc9530ad982f824644359b7a78c627ecb3403453`. `unityz` was built with Zig
0.16.0 in `ReleaseSafe` mode, then exercised against the tracked
`examples/SelfTestMod/Resources/shamwayselftest.unity3d` bundle.

The repository sweep searched source, tests, scripts, dependency metadata,
and documentation. It found 209 case-insensitive UnityPy references across 41
files. Each was classified as live code, a test reader, current user guidance,
or historical provenance; historical measurements keep the tool that actually
produced them.

The commands below produced the reader evidence:

```bash
unityz info examples/SelfTestMod/Resources/shamwayselftest.unity3d --json
unityz info examples/SelfTestMod/Resources/shamwayselftest.unity3d --json --objects
unityz stats examples/SelfTestMod/Resources/shamwayselftest.unity3d --json
unityz verify examples/SelfTestMod/Resources/shamwayselftest.unity3d --json
unityz hierarchy examples/SelfTestMod/Resources/shamwayselftest.unity3d --json
```

`verify` reported `checked=604`, `failed=0`. `info --json` reported the
embedded SerializedFile as format 22, Unity `2022.3.62f2`, platform 19, with
17 present class IDs including class 142. This embedded revision is the
relevant value; the outer UnityFS header deliberately says only `5.x.x`.

Warm filesystem command-level timing over the same 9.3 MB bundle measured 20
ordinary `shamway inspect --json` invocations at 1.713 seconds and 20
`unityz info --json` invocations at 0.146 seconds. Five UnityPy-backed deep
inspections took 3.605 seconds; five sets of `unityz info --objects`, `stats`,
and `hierarchy` took 0.169 seconds. These figures include process startup and
describe this artifact on this host, not a universal speed claim.

The baseline before any migration was `make check test`: 860 Python tests
passed, five opt-in tests skipped, and all five editor scripts compiled against
Unity 2022.3.62f2. The independent `unityz` suite passed 400 tests.

## Finding

### What unityz is

`unityz` is a Zig library and CLI for Unity containers and serialized asset
files. Its relevant format surface is broader than the pipeline's present
reader surface:

- UnityFS, UnityWeb, UnityRaw, WebFile, SerializedFile formats 2 through 22,
  `.resources` and `.resS` sidecars;
- uncompressed, LZ4, LZMA, and LZHAM bundle blocks;
- type-tree-driven object JSON, byte-exact object and container rewrite,
  atomic field/sidecar editing, hashing, structural and decoded diffs;
- PNG/TGA/BMP/raw texture and sprite extraction across raw, BC, ETC, ASTC,
  PVRTC, ATC, EAC, and Crunch formats;
- OBJ and glTF/GLB mesh extraction, including skinned meshes and named rigs;
- FSB5 PCM/ADPCM decoding and Vorbis-to-Ogg reconstruction without FFmpeg;
- shader-program decoding and skinning analysis, scene hierarchy, materials,
  animation, animator, particle, mixer, font, video, terrain, script, and
  AssetBundle-container summaries;
- Mono assembly metadata and injected script type trees without a CLR.

It is primarily a reader, extractor, verifier, differ, and in-place editor.
Its writer preserves and modifies object tables and type trees it received;
that is different from this pipeline's job of constructing a new object table
from authored PNG/WAV/glTF/VFX inputs.

### Repository-wide decision matrix

| Pipeline surface | Current mechanism | unityz coverage | Decision |
|---|---|---|---|
| `shamway inspect` revision and class-142 gate | local `unityfs.py` parser | full after unityz PR 121: embedded revision and class IDs are in `info --json` | migrate, then remove the duplicate parser and its pure-Python LZ4 path |
| `shamway inspect --deep` object census | UnityPy environment, object tree and PPtrs | full from `info --objects`, `stats`, `show` on class 142, and `hierarchy --json` | migrate; retain the existing `DeepReport` public shape |
| Synthesized writer type-tree lookup | UnityPy TPK database selected by Unity version and class ID | not full | keep until the creation gaps below land in unityz |
| `anim.py` and `particles.py` type-tree defaults | UnityPy TPK nodes | not full; same missing built-in tree source | keep with the writer, not as a separate exception |
| Writer read-back tests | UnityPy `load` / `read_typetree` | full through `show`, `info`, `hierarchy`, `shader`, and `verify` | migrate; unityz then becomes the independent reader of Python-authored bytes |
| Shader-object and compiled-blob tests | UnityPy object views and LZ4 helper | full through `show` / `shader`; decoded record tables are native | migrate the object assertions; keep direct byte-level tests where they test the Python assembler itself |
| `generate audio from-bank` | python-fsb5 | full through `unityz fsb` | migrate the user-facing decoder |
| FSB5 writer catalogue gate | python-fsb5 CRC lookup and reconstructed setup header | partial: unityz owns the same catalogue and can decode a completed bank, but has no non-writing JSON validation/query command | keep for now; add the missing unityz contract before removing `fsb5` |
| FSB5 writer independent tests | python-fsb5 rebuilds PCM/Ogg | full extraction, but replacing the only independent reader would reduce implementation independence | add unityz coverage, but do not delete the independent decoder solely for deduplication |
| BC1/BC3 independent decode tests | `texture2ddecoder` | unityz decodes these formats | retain `texture2ddecoder`: it intentionally checks the Python encoder with unrelated code |
| Authored glTF/OBJ/STL/PLY ingestion and geometry gates | trimesh plus Khronos validator | not covered: unityz extracts Unity `Mesh` objects; it is not an authored interchange-file validator | retain trimesh and the Khronos validator |
| glTF scene/skin import | pipeline `gltf_scene.py` | not covered in this direction | retain; unityz exports Unity meshes to glTF, which is the inverse operation |
| BC1/BC3 encoding | pipeline NumPy compressor | decode only | retain the encoder and its independent checks |
| HLSL/DXBC/SPIR-V/SMOL-V authoring | vkd3d, glslang, zmol-v and `shader_blob.py` | shader blob decode and analysis only | retain compilers and assembler; migrate read-back inspection |
| Fresh SerializedFile and UnityFS creation | `bundle_writer.py` | not covered from an empty input | retain until unityz exposes creation, not only rebuild |
| Engine method decompilation | ILSpy / monodis | not covered: `unityz managed` reads serialized field layouts, not method bodies | retain the decompilers for engine-behaviour provenance |
| Historical research facts | named UnityPy measurements | unityz could repeat many, but did not produce the recorded evidence | preserve attribution; remeasure only when a current conclusion depends on it |

### UnityPy replacement verdict

UnityPy cannot yet be removed completely. The reader and diagnostic usage is
replaceable now, and the test read-back usage is replaceable in logical
slices. The synthesized writer still needs two creation-side contracts unityz
does not currently provide:

1. A bundled, release-indexed source of built-in engine class type trees, or
   an equivalent offline command that returns the exact tree for a Unity
   revision and class ID. `unityz --trees` consumes externally generated
   AssetRipper/managed trees, but does not ship or select a versioned built-in
   database the way UnityPy's TPK does.
2. An API or CLI operation that creates a SerializedFile/object table and a
   UnityFS bundle from new objects. `unityz edit` and its writers rebuild an
   existing file; they do not create the first type, object, path ID, or
   container mapping from empty input.

The first gap also owns the default-value helpers in `anim.py` and
`particles.py`: those functions walk the selected class tree to produce the
correct version-specific empty shape. Treating them as unrelated Python
helpers would hide the actual dependency.

### Other open unityz contracts

The FSB5 migration needs a read-only, machine-readable validation mode. The
existing `unityz fsb` proves more than python-fsb5 for supported codecs, but it
writes decoded media and a sidecar. A writer gate needs to submit a bank and
receive sample mode, rate, channel count, sample count, Vorbis setup CRC
resolution, and success/failure without creating output files.

`unityz` has no published release artifacts as of 2026-09-04 (`gh release
list --repo hordeforge/unityz` returned no releases). Until releases exist,
the reproducible installation route is a checksum-verified source archive at
a pinned commit, built with the already-required Zig 0.16 toolchain. The
pipeline must not depend on the sibling checkout path.

The command-level benchmark above is enough to motivate migration, but not to
set a performance budget. A durable budget needs representative small,
large, LZ4, LZMA, and sidecar-backed game artifacts, plus peak-memory
measurement. This remains not checked because only the tracked self-test
bundle was benchmarked.

## Where it landed

The immediate slices are:

1. publish the embedded SerializedFile metadata in unityz (`info --json`);
2. install and probe a pinned unityz command without a sibling checkout;
3. replace `unityfs.py` and UnityPy-backed deep inspection;
4. replace UnityPy test readers by domain (`bundle_writer`, prefabs/entities,
   animation, shaders);
5. replace the user-facing FSB decoder after adding a read-only JSON bank
   contract;
6. design and implement the two creation-side contracts before removing the
   final UnityPy dependency.

Each behavior slice updates its owning command documentation and tests in the
same commit. Unknown performance limits stay on this page until the broader
artifact matrix is measured.
