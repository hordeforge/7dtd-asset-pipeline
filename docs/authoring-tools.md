# Open-source authoring and inspection tools

Only Python and Unity are pipeline requirements. The tools below are optional
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

- Official command-line manual:
  <https://files.openscad.org/documentation/manual/Using_OpenSCAD_in_a_command_line_environment.html>

### trimesh — Python mesh generation and checks

`trimesh` is useful for procedural primitives, conversions, extents,
watertightness checks, normals, and scripted export. It is an optional Python
dependency for asset-generation scripts, not for the bundle pipeline itself.

- Official export API: <https://trimesh.org/trimesh.exchange.export.html>

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

### ImageMagick — deterministic raster transforms

Use `magick` for crop/trim, resize, alpha/key processing, channel packing,
format conversion, montages, and quantitative comparisons. Prefer a new output
path over `mogrify`, which overwrites inputs. Record the complete command in
source documentation or a script.

- Official CLI guide: <https://imagemagick.org/command-line-processing/>
- Tool behavior: <https://imagemagick.org/command-line-tools/>

### Pillow and NumPy — asset generation as code

Pillow's `ImageDraw` can create icons, masks, decals, and sprite cards; NumPy
supports seeded noise, channel math, FFT texture synthesis, and deterministic
numeric generation. Use an explicit seed and write source plus deployable
derivative in a single script.

- Pillow documentation: <https://pillow.readthedocs.io/en/stable/>
- ImageDraw: <https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html>

## Audio

### FFmpeg

FFmpeg provides scriptable resampling, channel layout, normalization,
filtering, fades, mixing, convolution, and format conversion. Keep lossless
editable sources and make bundle-ready derivatives from a checked-in command
or script.

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
new one must too (see [AGENTS.md](../AGENTS.md)). `ilspycmd` (ILSpy's CLI, a
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

## Recommended agent-ready stack

| Asset | Generate/author | Pre-Unity check | Final gate |
|---|---|---|---|
| hard-surface mesh | OpenSCAD or Blender Python | trimesh + glTF Validator | Unity import + bundle + in-game view |
| organic/rigged mesh | Blender | glTF Validator + render turntable | bundle + animation/in-game view |
| PBR maps | Material Maker or seeded Python | channel/range checks + montage | `.mat` keywords/import + in-game light sweep |
| item icon | `shamway generate cutout`, `shamway render-icon`, Pillow/ImageMagick | `shamway check-icons` + downscaled montage | client atlas lookup + human readability |
| particle card | Pillow/NumPy/Blender | alpha-edge montage | particle material state + live VFX |
| sound | `shamway generate sound`, FFmpeg | `shamway check-sound` | sound group lookup + listening at range |
| detail normal | `shamway generate texture-maps detail` | tiling seam check on a cylinder | in-game light sweep on the flat-colour part |
| fresh client | `shamway client deploy` / `launch` | `shamway client log` | a person's look or listen, filed with `shamway client capture` |
