# Open-source authoring and inspection tools

Python is the only pipeline requirement; Unity is optional and, for a bundle
of textures, clips, text files and meshes, not involved at all. The tools below
are optional
and selected for reproducible, scriptable workflows that humans and coding
agents can both drive. Pin versions in each mod when output stability matters.

Install them with `scripts/install-tools.sh --with-authoring`. That takes each
tool from the distribution when it packages one, and falls back to the official
checksum-verified build for Blender and the Khronos glTF validator, which
several distributions omit or ship well behind upstream. Ask what is usable
right now with `shamway capabilities --json`.
`shamway generate` already ships working generators
built on this stack — sound synthesis and audio conversion (standard library
only), background cutout and icons (Pillow), texture maps (Pillow + NumPy), and
meshes (Blender) — and the scaffolded Unity project ships `GeneratedAsset.cs`
for prefabs, materials, imports, particles, and audio, plus `IconRenderer.cs`
for rendering a prefab into an atlas icon. Start from those.

## Geometry

### Blender — recommended general 3D authoring tool

Blender can create, UV, rig, bake, render, and export meshes. Its `--background
--python script.py -- ...` workflow makes it the strongest general option for
agent-authored geometry and deterministic batch conversion. Keep a `.blend`
or a generator script as source, apply transforms deliberately, and export a
Unity-supported interchange format.

`scripts/install-tools.sh --with-authoring` installs it, and
`shamway generate mesh` is a
working `--background --python` template to extend. Validate what it exports
with `shamway check-mesh` before importing.

- Official scripting guide: <https://docs.blender.org/api/main/info_quickstart.html>
- Background/module automation: <https://docs.blender.org/api/main/info_advanced_blender_as_bpy.html>

### OpenSCAD — recommended parametric hard-surface option

OpenSCAD is useful for crates, housings, brackets, tools, and other shapes
that are naturally described as constructive geometry. Its CLI exports meshes
and accepts `-D` parameters, which makes variant generation reviewable in a
small text diff.

Its STL output is a bundle input directly — OpenSCAD to `.unity3d` involves no
editor and no conversion step:

```bash
openscad -o assets-src/bundle/myModCrate.stl -D 'width=0.8' crate.scad
shamway check-mesh assets-src/bundle/myModCrate.stl
shamway build
```

STL carries no UVs, so the mesh reaches the bundle with positions and normals
only. Export from Blender or a glTF-emitting script when the geometry needs a
texture.

- Official command-line manual:
  <https://files.openscad.org/documentation/manual/Using_OpenSCAD_in_a_command_line_environment.html>

### trimesh — Python mesh generation, checks, and the editorless mesh lane

`trimesh` is useful for procedural primitives, conversions, extents,
watertightness checks, normals, and scripted export.

It is also the reader behind the **editorless mesh lane**: `shamway pack` and
`bundle_source = "synthesized"` turn any file trimesh reads — `.glb`, `.gltf`,
`.obj`, `.stl`, `.ply` — into a Unity `Mesh` inside the bundle, with no editor
anywhere. That makes every generator on this page a bundle input rather than a
Unity-import input:

```bash
shamway check-mesh assets-src/bundle/myModThing.glb
shamway pack assets-src/bundle build/mymod.unity3d --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
```

Read [no-unity.md](../bundles/no-unity.md#the-mesh-lane-and-what-it-is-not)
before using it: the writer converts handedness for you, the file must be
Y-up, and a `Mesh` is not a prefab — 7DTD's `Meshfile` wants a `GameObject`,
which wants a material, which wants a shader an editor has to compile.

- Official export API: <https://trimesh.org/trimesh.exchange.export.html>

### gltfpack — mesh optimization before import

`gltfpack` (from meshoptimizer) quantizes positions, normals and UVs and
reorders indices for vertex-cache locality, shrinking a glTF by large factors
with a documented quality knob (`-cc`, `-vpq`, `-vtn`). Run it between export
and validation when bundle size matters; keep the unoptimized glTF as the
editable source.

- Official repository: <https://github.com/zeux/meshoptimizer>

### AssetRipper — full vanilla reference extraction

AssetRipper exports complete prefab hierarchies, materials, meshes and
textures from an installed game into readable project form — stronger than
object-list inspection when a mod needs to study how vanilla wires a material
or a particle graph. Read-only against the install, reference only: never
copy exported vanilla assets into a mod.

- Official repository: <https://github.com/AssetRipper/AssetRipper>

### Khronos glTF Validator — interchange gate

When Blender/OpenSCAD/scripts emit glTF or GLB, run the Khronos validator
before Unity import. Its CLI reports schema, buffer, accessor, transform,
image, and extension problems with a nonzero error exit.

- Official repository: <https://github.com/KhronosGroup/glTF-Validator>

## Textures, materials, and icons

### Material Maker — procedural PBR source

Material Maker is an MIT-licensed node-based procedural texture and model
painting tool. Recent releases provide command-line material export, making
`.ptex` graphs suitable provenance for generated albedo/normal/ORM inputs.
Verify DirectX/OpenGL normal orientation and Unity mask-channel packing during
export.

- Official repository: <https://github.com/RodZill4/material-maker>
- Official releases: <https://github.com/RodZill4/material-maker/releases>

### ImageMagick — vector and layered source art

**Wired**, for the formats Pillow cannot read. Drop a `.svg`, `.psd`, `.exr`,
`.webp` or `.avif` into `assets-src/bundle/` and the writer rasterizes it to a
PNG in a temporary file, then makes the `Texture2D` from that — the original is
never touched. Vector source art is the case that matters: an icon authored
once as SVG re-renders cleanly at any cell size instead of being resampled.

```bash
shamway pack assets-src/bundle build/mymod.unity3d --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
```

An SVG renders at its own pixel size × `density / 96` (SVG's user unit is
1/96 inch), so the 384 default is 4x. Transparency is preserved explicitly —
without `-background none` ImageMagick fills it white, which reaches the atlas
as an opaque card behind every icon, and that is a test.

Beyond the wired path, reach for `magick` in a mod's own scripts for crop/trim,
channel packing, montages, and quantitative comparison (`magick compare
-metric RMSE`). Prefer a new output path over `mogrify`, which overwrites
inputs.

- Official CLI guide: <https://imagemagick.org/command-line-processing/>
- Tool behavior: <https://imagemagick.org/command-line-tools/>

### Pillow and NumPy — asset generation as code

Pillow's `ImageDraw` can create icons, masks, decals, and sprite cards; NumPy
supports seeded noise, channel math, FFT texture synthesis, and deterministic
numeric generation. Use an explicit seed and write source plus deployable
derivative in a single script.

- Pillow documentation: <https://pillow.readthedocs.io/en/stable/>
- ImageDraw: <https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html>

### Block compression — built in for BC1/BC3, external for BC7

The editorless writer compresses textures itself, with no extra tool:
`compress_textures = true` in `.shamway.toml`, or
`shamway pack --compress-textures`, encodes BC1 (`DXT1`, 8x smaller) when the
image is fully opaque and BC3 (`DXT5`, 4x) when it is not. Off by default,
because it is lossy.

```bash
shamway pack assets-src/bundle build/mymod.unity3d --compress-textures --game-dir "$SEVEN_DAYS_TO_DIE_DIR"
```

Both sides must be a multiple of four; a block format cannot express anything
else, and the writer refuses rather than padding, since padding moves every
atlas cell built on the old size.

**BC7 is the one worth an external tool.** It has eight block modes and a
partition table, so a mediocre Python encoder would be worse than the good BC1
one already here. These are the current CLIs, none of them packaged by Arch,
Debian or Fedora — each means building from source, so reach for one when a
mod's texture budget actually demands it:

- [bc7enc_rdo](https://github.com/richgel999/bc7_enc_rdo) — BC1–7 with
  rate-distortion optimization, a further 10–50% off after LZ;
- [Compressonator](https://github.com/GPUOpen-Tools/compressonator) — GPUOpen,
  CLI and library, widest format coverage;
- [ISPCTextureCompressor](https://github.com/GameTechDev/ISPCTextureCompressor)
  — Intel's SIMD encoders, the quality/speed reference other tools embed;
- [ctt](https://github.com/cwfitzgerald/ctt) — one front end over bc7e, ISPC,
  AMD and astcenc, if you want to compare them.

Judge the result with a **composited** PSNR, never a raw one: a transparent
pixel's colour is renderer noise, and grading it makes a good encoder look
broken (`shamway docs improvements`, gap 4).

### python-fsb5 — FSB5 decoding, for reference and for proof

**Wired**, and for two jobs. The game stores every clip as an FSB5 bank inside
a `.resource` stream, so decoding one lets a sound designer hear exactly what
a vanilla clip contains at its true rate and channel count:

```bash
shamway generate audio from-bank vanilla.resource reference/
```

The second job is why it is a dependency rather than a suggestion. This
pipeline **hand-writes** those banks — `_fsb5_pcm16` packs the header bit by
bit — and a bank read back only by the code that wrote it has not been read
back at all. The suite decodes our own output with python-fsb5 and asserts the
PCM returns byte-identical, the same independent-reader rule the block
compressor follows with `texture2ddecoder`.

- Official repository: <https://github.com/HearthSim/python-fsb5>

## Audio

### FFmpeg — compressed source audio

**Wired**, for the containers the standard library cannot open. An `.ogg`,
`.mp3`, `.flac`, `.aiff`, `.m4a`, `.opus` or `.wma` in `assets-src/bundle/` is
decoded to 16-bit PCM in a temporary file and becomes an `AudioClip` from
there; the lossy original stays exactly as authored. A `.wav` skips FFmpeg
entirely, so the lane still works on a host without it.

Note the asymmetry: FFmpeg is used to get audio **in**, never to get it out.
The bundle always carries PCM, because `AudioClip` Vorbis encoding needs
FMOD's own seek tables ([improvements](../status/improvements.md) 4).

Beyond that, FFmpeg provides scriptable resampling, channel layout,
normalization, filtering, fades, mixing and convolution for a mod's own
scripts — though `shamway generate audio convert` already does resample,
downmix and normalize with no third-party package. Keep lossless editable
sources and make bundle-ready derivatives from a checked-in command or script.

- Official documentation: <https://ffmpeg.org/documentation.html>
- Audio filters: <https://ffmpeg.org/ffmpeg-filters.html#Audio-Filters>

Python's standard `wave` module is also effective for wholly procedural sound,
and needs no third-party package at all:
`shamway generate sound` builds
explosions, ticks, whooshes, hums, and cues from seeded noise and one-pole
filters, and prints the matching `sounds.xml` entry. Gate the result with
`shamway check-sound`, then always listen to it; deterministic does not
mean good.

## Visual evidence

### grim, maim, spectacle — the screenshot backends

A visual sign-off is the last step of acceptance and the only one with no
output of its own. `shamway client capture` uses whichever of `grim`,
`spectacle`, `gnome-screenshot`, `maim`, `scrot`, or ImageMagick's `import` can
serve the current session, and records the frame with the observable it was
checked against.

Which tool matters less than which *session*: an X11 grabber under Wayland
returns a black or garbage frame **and exits zero**, so the session type
selects the candidate rather than merely ordering it. `grim` is the Wayland
answer, `maim` the X11 one, and an X11 host that already ran `--with-authoring`
has `import` and needs neither.

- `grim`: <https://sr.ht/~emersion/grim/>
- `maim`: <https://github.com/naelstrof/maim>

```bash
shamway script install-tools --with-desktop-capture
shamway capabilities --json
```

## Engine facts

### ilspycmd and monodis — the named sources

Every 7DTD-specific rule in this repository cites a decompiled method, and a
new one must too (see [AGENTS.md](../../AGENTS.md)). `ilspycmd` (ILSpy's CLI, a
.NET global tool) is the primary: `ilspycmd -t ModManager
"$SEVEN_DAYS_TO_DIE_DIR/7DaysToDie_Data/Managed/Assembly-CSharp.dll"` prints
one type. Mono's `monodis` (and `ikdasm`) is the second opinion on a method
body; `strings` proves only that a name exists. `scripts/install-tools.sh
--with-research` installs all three, and `mcs` from the same Mono package is
what `scripts/compile-editor-scripts.sh` uses to compile the editor scripts
against a real editor's assemblies without starting it.

- ILSpy: <https://github.com/icsharpcode/ILSpy>
- The installed game's own `Data/Config/XML.txt` is the first source for
  what an XML property means.

## Unity and bundle diagnostics

### This pipeline's inspector

`shamway inspect` is the required zero-dependency preflight. It owns the
revision and class-142 gates used during staging.

### UnityPy

UnityPy is a Python parser/extractor useful for independent object-table,
container, Texture2D, Mesh, and typetree inspection. Pin its minor version
because its own documentation warns that minor releases may break APIs. Keep
it diagnostic; do not use it to generate the authoritative bundle.

- Official repository/documentation: <https://github.com/K0lb3/UnityPy>

### AssetsTools.NET

AssetsTools.NET is a .NET library for reading and modifying Unity assets and
bundles, with streaming LZ4 support and container traversal. It is valuable as
a second implementation when a subtle bundle claim needs independent
confirmation.

- Official repository: <https://github.com/nesrak1/AssetsTools.NET>
- Official wiki: <https://github.com/nesrak1/AssetsTools.NET/wiki>

### AssetStudio and UABE

Interactive Unity asset browsers, widely used in the 7DTD community for looking
at the game's own art — which is the reference for
[art direction](art-direction.md). Both track Unity's serialization format
closely, so pin a version that matches the game's Unity revision rather than
taking the newest. Read-only use against the installed game only: never write
to it, and never copy its assets into a mod.

### Unity Asset Bundle Browser

Unity's open-source browser can inspect and debug bundle contents in the
Editor. Unity labels it unsupported and recommends newer alternatives, so use
it as an interactive diagnostic rather than a build dependency.

- Official repository: <https://github.com/Unity-Technologies/AssetBundles-Browser>

### OCB7D2D UnityAssetExporter

OCB's MIT-licensed Unity package is specifically intended for 7DTD and
supports folder membership, LZ4/LZMA, platform variants, and shader stripping
controls. It is a useful community reference or GUI alternative. Exporter API
choice does not waive this pipeline's module-log, class-142, version, naming,
or live-client gates.

- Official repository: <https://github.com/OCB7D2D/UnityAssetExporter>

## What is actually wired, and what is not

A tool named on this page with nothing calling it reads like an unfinished
integration. This table says which is which, so nobody has to guess — and so
"integrate the OSS tools" has one place to check. Ask the live version with
`shamway capabilities --json`.

| Tool | State |
|---|---|
| **UnityPy** | **wired** — type trees for every class the editorless writer emits, `inspect --deep` |
| **trimesh** | **wired** — `check-mesh`, and reads glTF/OBJ/STL/PLY into a bundle `Mesh` |
| **Blender** | **wired** — `generate mesh` (GLB) and `generate mesh-icon` (headless Cycles render) |
| **Pillow** | **wired** — cutouts, atlas cells, contact sheets, the texture lane |
| **NumPy** | **wired** — `generate texture-maps`, and the BC1/BC3 block compressor |
| **Khronos glTF Validator** | **wired** — `check-mesh --strict`; degrades to a `skipped:` line when absent |
| **screenshot backends** | **wired** — `client capture` picks one per session type |
| **xvfb** | **wired** — `render-icon` on a headless host |
| **OpenSCAD** | **input only** — its STL drops straight into `assets-src/bundle/`; no command shells out to it |
| **ImageMagick** | **wired** — rasterizes `.svg`, `.psd`, `.exr`, `.webp`, `.avif` into the texture lane, which Pillow cannot |
| **FFmpeg** | **wired** — decodes `.ogg`, `.mp3`, `.flac`, `.aiff`, `.m4a`, `.opus`, `.wma` into the audio lane, which the stdlib cannot |
| **bc7enc / Compressonator / ISPC / ctt** | **not wired** — BC7 only; none is packaged on Arch, Debian or Fedora, so each means a source build. BC1/BC3 are built in |
| **gltfpack** | **not wired** — mesh quantization; useful when a mod's bundle is mesh-heavy, and nothing needs it before then |
| **Material Maker** | **not wired** — GUI-first; its CLI export is a mod-side authoring choice |
| **AssetRipper / AssetStudio / UABE** | **reference only, by design** — read the game to learn from it, never to copy out of it |
| **python-fsb5** | **wired** — `generate audio from-bank`, and the independent reader that grades the hand-written FSB5 banks |
| **vkd3d-compiler / glslang** | **not wired yet** — proven to emit the DXBC/SPIR-V a Unity shader carries; blocked on one undecoded descriptor ([improvements](../status/improvements.md) 4b) |

## Recommended agent-ready stack

| Asset | Generate/author | Pre-Unity check | Final gate |
|---|---|---|---|
| hard-surface mesh | OpenSCAD or Blender Python | `shamway check-mesh` (trimesh + glTF Validator) | `shamway build` straight from the exported file, or a Unity import; then in-game view |
| organic/rigged mesh | Blender | glTF Validator + render turntable | Unity import (rigging and animation are not in the editorless lane) + in-game view |
| PBR maps | Material Maker or seeded Python | channel/range checks + montage | `.mat` keywords/import + in-game light sweep |
| item icon | `shamway generate cutout`, `shamway render-icon` (editor) or `shamway generate mesh-icon` (Blender), Pillow/ImageMagick | `shamway check-icons` + downscaled montage | client atlas lookup + human readability |
| particle card | Pillow/NumPy/Blender | alpha-edge montage | particle material state + live VFX |
| sound | `shamway generate sound`, FFmpeg | `shamway check-sound` | sound group lookup + listening at range |
| detail normal | `shamway generate texture-maps detail` | tiling seam check on a cylinder | in-game light sweep on the flat-colour part |
| fresh client | `shamway client deploy` / `launch` | `shamway client log` | a person's look or listen, filed with `shamway client capture` |
