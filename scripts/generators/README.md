# Asset generators

Reproducible, parameterized generators for the authoring lanes in
[../../docs/agent-workflows.md](../../docs/agent-workflows.md). They exist so a
mod's first asset is a checked-in command with recorded numbers rather than
unrecorded GUI state, and so an agent has a working template to extend.

They are **starting points, not a modelling suite.** Copy one into your mod's
`assets-src/` and edit it there; this repository does not own your art.

| Script | Lane | Needs |
|---|---|---|
| `make-audio.py` | report, convert, and synthesize mono 16-bit WAV | stdlib only |
| `make-icon.py` | derive an atlas icon from a source image | Pillow |
| `make-texture-maps.py` | derive normal + mask maps from an albedo | Pillow, NumPy |
| `make-mesh.py` | authored mesh to GLB | Blender on `PATH` |

Install the optional tools with `scripts/install-tools.sh --with-authoring`.
Each script fails with an actionable message when its dependency is absent.

## The contract every generator follows

- explicit input and output paths, no implicit locations;
- a recorded seed wherever randomness is involved, so a rebuild is
  byte-reproducible and a diff means someone changed the design;
- write to a temporary file and replace the destination only on success, so a
  failed run never leaves a half-written asset in the Unity project;
- print the numbers a review needs — dimensions, format, channels, duration,
  peak, means — so a change is reviewable without opening an editor;
- fail on missing inputs instead of creating placeholders;
- never edit the installed game.

Follow it in your own generators too.

## Examples

```bash
# Audio: synthesize, convert, and report
./make-audio.py tone /tmp/hum.wav --seconds 2 --hz 90 --noise 0.3 --seed 7
./make-audio.py convert source.wav Bundle/Audio/myModHum.wav --rate 44100 --peak 0.89
./make-audio.py report Bundle/Audio/myModHum.wav

# Icon: 7DTD atlas cell plus a legibility contact sheet
./make-icon.py art/thing.png UIAtlases/ItemIconAtlas/myModThing.png \
    --size 160 --contact-sheet /tmp/thing-sheet.png

# Textures: maps that stay in register with their albedo
./make-texture-maps.py art/paint.png \
    --out-dir tools/7dtd-assets/UnityProject/Assets/ModAssets/Bundle/Textures \
    --stem myModPaint --metallic 0.58 --smoothness 0.16

# Mesh: a parameterized primitive at real-world metres
./make-mesh.py /tmp/crate.glb --shape box --size 1.0 0.6 0.8 --name myModCrate
```

## Two mesh lanes

Both are first-class; pick by what the shape needs.

| Lane | Use it for | Cost | Result in the bundle |
|---|---|---|---|
| **Authored** — `make-mesh.py`, Blender, OpenSCAD | organic, rigged, sculpted, or anything primitives cannot express | Blender on the host | a real class-43 `Mesh` object |
| **Procedural** — `GeneratedAsset.Primitive(...)` in the Unity project | hard-surface props that are boxes, cylinders, and spheres | nothing beyond Unity | no `Mesh` object; the prefab references Unity's built-in primitives |

Validate an authored mesh before importing it:

```bash
7dtd-assets check-mesh out.glb            # extents, watertightness, glTF conformance
7dtd-assets check-mesh out.glb --strict   # also fail on glTF warnings
```

That catches the expensive mistakes early — most often a mesh authored in
centimetres, which arrives a hundred times too large and reads as a scale bug
in game rather than an export bug.

## Unity side

Generating a prefab or material from code is the Unity half of the same idea.
The scaffolded project ships `GeneratedAsset.cs`, whose helpers encode the
traps a batch script hits and the inspector hides:

- `StandardMaterial(...)` enables `_NORMALMAP` and `_METALLICGLOSSMAP`, without
  which an assigned map is never sampled;
- `TransparentMaterial(...)` sets blend factors, `_ZWrite`, keywords, and the
  render queue, not just `_Mode`, so a particle card is not opaque;
- `SavePrefab(...)` renames the root to the file stem, because 7DTD compares
  the loaded object's name and a mismatch yields a silent fallback mesh;
- `RequireBundleStem(...)` rejects a stem too generic to stay unique;
- `Primitive(...)`, `Root(...)`, `RootCollider(...)`, `ScaleChildren(...)`, and
  `MeasureBounds(...)` compose the procedural mesh lane: real-world metres, an
  identity root the engine's own corrections do not compound with, one root
  collider instead of one per visual part, and measurable bounds in the log.

Both halves end at the same place: `7dtd-assets build`, then a fresh client.
