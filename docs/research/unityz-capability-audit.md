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

The replacement report was also compared directly after correcting the
generated entity component ownership found during the migration. UnityPy
1.25.3 and the unityz-backed candidate produced byte-identical public JSON for
the corrected self-test bundle: 604 objects, 50 container entries, 10 prefab
roots, and zero skipped children. Before that correction they disagreed on the
Arachnid hierarchy because UnityPy's old walker selected the last Transform
pointer on a malformed root; unityz exposed that the pointer belonged to the
child `figure` GameObject. That discrepancy became the writer fix rather than
being normalized away in the replacement reader.

Before replacing the hot revision gate, the same single-run timing was taken
against the installed game's preferred `Entities` bundle and its 621 MB
`trees` fallback. `Entities` is 1.6 KB: the Python CLI plus prefix reader took
0.101 seconds and `unityz info --json` took 0.002 seconds. On `trees`, the
prefix reader took 0.116 seconds while unityz's current whole-container read
took 1.365 seconds. The normal discovery path therefore improves, while the
large fallback is a measured 1.249-second regression. Peak memory remains not
checked because `/usr/bin/time` is absent on this host. The migration keeps
the one-reader architecture, but this fallback measurement belongs in the
optimization backlog rather than being hidden by the small-bundle benchmark.

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
| `shamway inspect` revision and class-142 gate | pinned `unityz info --json` behind `unityz.py` | full after unityz PR 121: embedded revision and class IDs are in `info --json` | migrated; the duplicate parser and its pure-Python LZ4 path are removed |
| `shamway inspect --deep` object census | unityz `info`, `stats`, `show`, `verify`, and `hierarchy` | full for embedded-tree bundles; stripped 2022.3.62f2 files decode with `--builtin` since unityz PR 156, other releases still refuse | migrated with the existing `DeepReport` shape; pass `--builtin` in the next re-pin and keep the refusal for unshipped releases |
| Synthesized writer type-tree lookup | UnityPy TPK database selected by Unity version and class ID | full for 2022.3.62f2 since unityz PR 156: `trees --builtin <release> --class <id>` returns the exact tree with sizes, versions and array flags | migrate to the export after the re-pin; keep UnityPy until then |
| `anim.py` and `particles.py` type-tree defaults | UnityPy TPK nodes | full for 2022.3.62f2 through the same export | migrate with the writer, not as a separate exception |
| Writer read-back tests | UnityPy `load` / `read_typetree` | full through `show`, `info`, `hierarchy`, `shader`, and `verify` | migrate; unityz then becomes the independent reader of Python-authored bytes |
| Shader-object and compiled-blob tests | UnityPy object views and LZ4 helper | full through `show` / `shader`; decoded record tables are native | migrate the object assertions; keep direct byte-level tests where they test the Python assembler itself |
| `generate audio from-bank` | pinned `unityz fsb` | full in 0.1.2: PCM/ADPCM WAV and Vorbis OGG extraction; incomplete decodes return non-zero | migrated; the generator delegates through the bounded unityz process adapter |
| FSB5 writer catalogue gate | python-fsb5 CRC lookup and reconstructed setup header | full read-only validation in `unityz fsb --json`, including `setupKnown`, `decodable`, and `valid` | retain python-fsb5 for now because it is also the writer's independent implementation; add unityz validation beside it in the writer-test slice |
| FSB5 writer independent tests | python-fsb5 rebuilds PCM/Ogg | full extraction, but replacing the only independent reader would reduce implementation independence | retain the independent decoder; unityz becomes an additional cross-repository check, not its replacement |
| BC1/BC3 independent decode tests | `texture2ddecoder` | unityz decodes these formats | retain `texture2ddecoder`: it intentionally checks the Python encoder with unrelated code |
| Authored glTF/OBJ/STL/PLY ingestion and geometry gates | trimesh plus Khronos validator | not covered: unityz extracts Unity `Mesh` objects; it is not an authored interchange-file validator | retain trimesh and the Khronos validator |
| glTF scene/skin import | pipeline `gltf_scene.py` | not covered in this direction | retain; unityz exports Unity meshes to glTF, which is the inverse operation |
| BC1/BC3 encoding | pipeline NumPy compressor | decode only | retain the encoder and its independent checks |
| HLSL/DXBC/SPIR-V/SMOL-V authoring | vkd3d, glslang, zmol-v and `shader_blob.py` | shader blob decode and analysis only | retain compilers and assembler; migrate read-back inspection |
| Fresh SerializedFile and UnityFS creation | `bundle_writer.py` | not covered from an empty input | retain until unityz exposes creation, not only rebuild |
| Engine method decompilation | ILSpy / monodis | not covered: `unityz managed` reads serialized field layouts, not method bodies | retain the decompilers for engine-behaviour provenance |
| Historical research facts | named UnityPy measurements | unityz could repeat many, but did not produce the recorded evidence | preserve attribution; remeasure only when a current conclusion depends on it |

### UnityPy replacement verdict

UnityPy remains required for the synthesized writer until the pipeline
migrates to the upstream contracts. The reader and diagnostic usage is
replaceable now, and the test read-back usage is replaceable in logical
slices. Of the two creation-side contracts, one has landed upstream and one is
still missing:

1. **Landed (unityz PR 156, 2026-09-05, not yet in the pinned release):** a
   bundled, release-indexed source of built-in engine class type trees.
   `src/builtin_trees.zig` embeds the AssetRipper TypeTreeDumps release dump
   packed by `scripts/structsdump-to-builtin.py` and serves the exact tree for
   an exact `(release, class id)`; `unityz trees --builtin <release>
   [--class <id>]` exports it in the `--trees` JSON shape with `m_ByteSize`,
   `m_Version`, `m_TypeFlags` and `m_Index`, and `--builtin` lets the reading
   commands decode a stripped file's built-in classes. Only 2022.3.62f2 ships;
   matching is exact, with no nearest-version selection, so a stripped file
   from any other release is still refused by `inspect --deep` until that
   release is packed upstream. Checked against the self-test bundle's
   embedded TPK trees: all 17 classes identical on type, name, level, meta
   flag, version and byte size; the only difference is the array flag on
   `TypelessData` nodes, which `bundle_writer.py` omits and the built-in tree
   carries. MonoBehaviour script trees remain a `--trees`/`managed` concern.
2. An API or CLI operation that creates a SerializedFile/object table and a
   UnityFS bundle from new objects. `unityz edit` and its writers rebuild an
   existing file; they do not create the first type, object, path ID, or
   container mapping from empty input.

The first item also owns the default-value helpers in `anim.py` and
`particles.py`: those functions walk the selected class tree to produce the
correct version-specific empty shape, and they move to the `trees --builtin`
export together with the writer. Treating them as unrelated Python helpers
would hide the actual dependency.

### FSB5 contract closure

Unityz PR 138 added the read-only, machine-readable validation mode the audit
found missing. `unityz fsb --json` submits no extraction target, decodes or
rebuilds every sample in memory, and reports mode, rate, channel count, sample
count, Vorbis setup CRC availability, per-sample decodability, and a top-level
validity verdict. It writes nothing and returns non-zero for malformed banks or
any sample it cannot reconstruct. The same change corrected ordinary `fsb`
extraction to return non-zero instead of printing a partial decode as success.

At the initial 2026-09-04 measurement, `gh release list --repo
hordeforge/unityz` returned no releases, so the first reproducible integration
built merged commit `b3fc09b38f7d0b1d3870981b50164740c5cbeeb7` from a
checksum-pinned source archive. Unityz subsequently published 0.1.3. The
current `scripts/install-unityz.sh` installs that checksum-verified release
binary on Linux x86_64 and macOS arm64, and builds pinned commit
`b7ee8db3da36166c45903eea6a2d215a3ff9ef8f` elsewhere or when
`UNITYZ_FROM_SOURCE=1`. Neither route reads a sibling checkout.

Version 0.1.2 is the explicit downstream contract. It includes the nested
metadata added in unityz PR 121, the version signal from PR 123, the corrected
`show` failure status from PR 137, and the FSB5 JSON/status contract from PR
138. Both the shell installer's `--check` and the Python capability probe reject
an older binary as present but unusable instead of discovering a missing
contract half-way through an operation.

The original pinned source archive was installed through the downstream script
into an empty prefix and reported `unityz 0.1.2`. The pipeline-authored PCM16
FSB5 fixture then decoded through `generate audio from-bank` to
`audio_sample.wav` plus `bank.json` with exit 0. Truncating its sample payload
returned exit 1 and one physical `ERROR:` line; it was not accepted as a
partial extraction. After rebasing onto the release-installer change, that
installer fetched and checksum-verified the Linux x86_64 0.1.3 binary into an
empty prefix; the same valid fixture exited 0 and the payload-cut fixture
exited 1 through that exact binary. After the generator, installer, capability,
tests, and documentation moved together, `make check test` passed 852 tests
with three opt-in skips and compiled all five editor scripts against Unity
2022.3.62f2.

The same pin includes unityz PR 135's subtree-local `skipped_children`
contract. Deep inspection uses that field to mark only the affected prefab
entry partial when a hierarchy child cannot be decoded; the top-level count
alone cannot identify which bundle entry lost evidence.

The pinned commit also includes unityz PR 134: `hierarchy --json` emits a
stable `{node, hierarchy, skipped_children}` object for every SerializedFile,
keeps arrays valid when an unreadable child is omitted, and returns non-zero
for malformed input or an invalid option. That contract is required by the
next deep-inspection slice; without the count, migrating from UnityPy would
silently discard the existing partial-result signal.

The first reader integration then found that `unityz info` printed a rejection
for an unrecognized file but exited zero. Unityz PR 126 made single inputs and
directory batches return non-zero when any member cannot be read; the pinned
commit includes that fix, so the pipeline can trust exit status before parsing
stdout.

The command-level benchmark now covers a small shipped bundle and one large
LZ4 shipped bundle as well as the synthesized self-test. It is still not a
durable performance budget: LZMA and sidecar-backed game artifacts and peak
memory remain not checked. A unityz metadata-only streaming path would remove
the measured large-fallback regression without restoring a second parser.

## Where it landed

The migration slices are:

1. **done:** publish the embedded SerializedFile metadata in unityz
   (`info --json`, unityz PR 121);
2. **done:** version that contract and install/probe a pinned unityz command
   without a sibling checkout (unityz PR 123 and the installer slice);
3. **done:** replace the local `unityfs.py` parser with the bounded `unityz`
   process/JSON adapter; generated acceptance and truncated-rejection fixtures
   now exercise the external parser, whose own fuzz suite owns hostile format
   inputs;
4. **done for embedded-tree bundles:** replace UnityPy-backed deep inspection
   while retaining its public report; unityz PR 135 adds subtree-local omission
   counts so only the affected prefab is partial. The typeless-file limit is
   the built-in-tree gap above, not hidden as a complete replacement;
5. **in progress:** replace UnityPy test readers by domain. The
   `bundle_writer`, prefab/hierarchy, skinned-mesh, particle, and generated
   entity round trips now use the pinned unityz `extract --json` manifest,
   object trees, and path IDs. Animation clips, curves, components, and figure
   hierarchy now use the same contract; shaders remain the final test-reader
   slice;
6. **done:** replace the user-facing FSB decoder after adding the read-only JSON
   bank contract in unityz PR 138;
7. design and implement the two creation-side contracts before removing the
   final UnityPy dependency: the built-in type-tree source landed upstream in
   unityz PR 156 and awaits the re-pin plus the writer/default/deep-inspect
   migration here; from-empty SerializedFile and UnityFS creation is still
   open.

Each behavior slice updates its owning command documentation and tests in the
same commit. Unknown performance limits stay on this page until the broader
artifact matrix is measured.
