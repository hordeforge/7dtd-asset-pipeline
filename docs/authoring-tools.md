# Open-source authoring and inspection tools

Only Python and Unity are pipeline requirements. The tools below are optional
and selected for reproducible, scriptable workflows that humans and coding
agents can both drive. Pin versions in each mod when output stability matters.

Install them with `scripts/install-tools.sh --with-authoring`.
[scripts/generators/](../scripts/generators/) already ships working generators
built on this stack — audio (standard library only), icons (Pillow), texture
maps (Pillow + NumPy), and meshes (Blender) — and the scaffolded Unity project
ships `GeneratedAsset.cs` for prefabs and materials. Start from those.

## Geometry

### Blender — recommended general 3D authoring tool

Blender can create, UV, rig, bake, render, and export meshes. Its `--background
--python script.py -- ...` workflow makes it the strongest general option for
agent-authored geometry and deterministic batch conversion. Keep a `.blend`
or a generator script as source, apply transforms deliberately, and export a
Unity-supported interchange format.

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

Python's standard `wave` module plus seeded NumPy is also effective for wholly
procedural tones and effects. Always listen to the result; deterministic does
not mean good.

## Unity and bundle diagnostics

### This pipeline's inspector

`7dtd-assets inspect` is the required zero-dependency preflight. It owns the
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
| item icon | Pillow/ImageMagick | size, alpha, downscaled montage | client atlas lookup + human readability |
| particle card | Pillow/NumPy/Blender | alpha-edge montage | particle material state + live VFX |
| sound | FFmpeg or NumPy/wave | codec/rate/peak report | sound group lookup + listening at range |
