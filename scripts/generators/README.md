# Asset generators

The generators moved into the installed package. They are no longer scripts you
copy or path into — a mod calls them through the one command it already has:

```bash
shamway generate --list
shamway generate sound --help
shamway generate sound blast assets-src/audio/blast.wav --seed 7
```

Their source is [`src/sevendtd_asset_pipeline/generators/`](../../src/sevendtd_asset_pipeline/generators/).

That move is the point: this repository owns the generalized tooling and a mod
owns its content, so a mod must never contain a relative path into a checkout
of this repository. The full ownership split is in
[docs/mod-repo-layout.md](../../docs/mod-repo-layout.md).

| Generator | Lane | Needs |
|---|---|---|
| `sound` | **create** clips: designed voices, plus the `sounds.xml` entry | stdlib only |
| `audio` | **measure and convert** clips: report, downmix, resample, normalize | stdlib only |
| `cutout` | cut a generated image out of its flat key background, or a grayscale mask into a particle card | Pillow |
| `icon` | derive an atlas cell from an already-transparent source | Pillow |
| `texture-maps` | derive normal + mask maps from an albedo | Pillow, NumPy |
| `mesh` | authored mesh to GLB | Blender on `PATH` |
| `mesh-icon` | photograph a mesh file into an atlas cell, headless | Blender on `PATH` |
| `particle-card` | a soft streak or haze card for a particle material | Pillow, NumPy |

Every one of them writes a file the editorless bundle writer can read, so a
generated asset reaches a `.unity3d` with no editor between them.

Install the optional tools with `scripts/install-tools.sh --with-authoring`;
ask what works right now with `shamway capabilities --json`. Each generator
fails with an actionable message when its dependency is absent, and `--help`
works either way.

## The contract every generator follows

Follow it in a mod's own generators too — that is what these are a reference
for:

- explicit input and output paths, no implicit locations;
- a recorded seed wherever randomness is involved, so a rebuild is
  byte-reproducible and a diff means someone changed the design;
- write to a temporary file and replace the destination only on success, so a
  failed run never leaves a half-written asset in the bundle-membership folder;
- print the numbers a review needs — dimensions, format, channels, duration,
  peak, means — so a change is reviewable without opening an editor;
- fail on missing inputs instead of creating placeholders;
- never edit the installed game.

## Gate what you generated

Each lane has an offline check that needs no Unity, no network, and no game:

- `shamway check-sound assets-src/audio/blast.wav` — format, level, DC offset
- `shamway check-icons` — cells + every CustomIcon key
- `shamway check-mesh  assets-src/meshes/thing.glb` — extents, glTF conformance

```bash
shamway check-sound assets-src/audio/blast.wav
shamway check-icons
shamway check-mesh  assets-src/meshes/thing.glb
```

## Two mesh lanes

Both are first-class; pick by what the shape needs.

| Lane | Use it for | Cost | Result in the bundle |
|---|---|---|---|
| **Authored** — `shamway generate mesh`, Blender, OpenSCAD | organic, rigged, sculpted, or anything primitives cannot express; and everything, on the default editorless path | Blender on the host | a class-43 `Mesh`, and — from `assets-src/bundle/` — the prefab, material and shader around it |
| **Procedural** — `GeneratedAsset.Primitive(...)` in the Unity project | hard-surface props that are boxes, cylinders, and spheres | a Unity editor: this is the one lane that needs `bundle_source = "unity"` | no `Mesh` object; the prefab references Unity's built-in primitives |

A procedural prop's first draft is always a handful of bare shapes that read
as nothing; the one that shipped went to about forty primitives, and the
lessons — hoops on drums, caps on pipes, wraps as straight runs never thin
discs, one asymmetric detail, decals on a textured quad, colours re-tuned for
linear space — are in `shamway docs art-direction` under "Props from
primitives". Its flat-coloured parts get surface from a tileable detail
normal (`shamway generate texture-maps detail`) applied with
`GeneratedAsset.Tile`, so primitives need not mean plastic.

Validate an authored mesh before importing it:

- `shamway check-mesh out.glb` — extents, watertightness, glTF conformance
- `shamway check-mesh out.glb --strict` — also fail on glTF warnings

```bash
shamway check-mesh out.glb
shamway check-mesh out.glb --strict
```

That catches the expensive mistakes early — most often a mesh authored in
centimetres, which arrives a hundred times too large and reads as a scale bug
in game rather than an export bug.

`watertight: False` is reported but never fails the check: glTF export splits
vertices at UV and normal seams, so a correctly exported cylinder is routinely
not watertight. It matters when the mesh is meant to be a collider, and is
noise otherwise.

Blender is Z-up and glTF is Y-up, so a mesh authored at `--size W D H` arrives
with its height on Y. The generator puts the pivot at the base, so exported
bounds start at Y = 0 and a placed block rests on the ground.

## Unity side — only for a mod that opted into an editor

Generating a prefab or material from code is the Unity half of the same idea,
and it applies to `bundle_source = "unity"` alone. On the default path the
writer assembles the prefab, material and shader itself from the mesh file, and
none of the helpers below exist or are needed — nor do their traps, since that
material has one texture property and no keywords.

A mod with a Unity project gets `GeneratedAsset.cs`, whose helpers encode the
traps a batch script hits and the inspector hides:

- `StandardMaterial(...)` enables `_NORMALMAP` and `_METALLICGLOSSMAP`, without
  which an assigned map is never sampled;
- `TransparentMaterial(...)` and `ParticleMaterial(...)` set blend factors,
  `_ZWrite`, keywords, and the render queue, not just `_Mode`, so a particle
  card is not opaque;
- `ImportNormalMap(...)`, `ImportLinearMap(...)`, and `ImportColorMap(...)` set
  the import type, which is the other way a material map fails silently;
- `SavePrefab(...)` renames the root to the file stem, because 7DTD compares
  the loaded object's name and a mismatch yields a silent fallback mesh;
- `RequireBundleStem(...)` rejects a stem too generic to stay unique;
- `Primitive(...)`, `Root(...)`, `RootCollider(...)`, `ScaleChildren(...)`, and
  `MeasureBounds(...)` compose the procedural mesh lane: real-world metres, an
  identity root the engine's own corrections do not compound with, one root
  collider instead of one per visual part, and measurable bounds in the log;
- `ZeroCurve()` and `BudgetParticles(...)` keep a particle system's curve modes
  consistent and its cost inside the prefab;
- `ImportAudioClip(...)` and `AudioSourcePrefab(...)` are the audio half.

`IconRenderer.cs` ships beside it for the other icon lane, driven by
`shamway render-icon`, and `ShamwayPreBuild.cs` is the seam a mod's own
generators hook into so `shamway build` runs them before collecting the bundle.

Both halves end at the same place: `shamway build`, then a fresh client.
