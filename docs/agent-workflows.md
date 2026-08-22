# Agent-friendly asset workflows

Asset generation is safest when the editable source, transformation, checks,
and acceptance evidence are explicit. An agent should be able to regenerate a
derivative without guessing which GUI state produced it.

## Repository pattern

```text
assets-src/
├── README.md                 # art direction, licenses, provenance, commands
├── models/
│   ├── generator.py          # or .blend/.scad source
│   └── exported/example.glb
├── textures/
│   ├── material.ptex         # or seeded Python generator
│   └── generated/*.png
├── icons/
│   ├── source/*.png
│   └── make-icons.py
└── audio/
    ├── source/*.wav
    └── make-audio.sh

tools/7dtd-assets/UnityProject/Assets/ModAssets/Bundle/
└── selected Unity inputs + every .meta file
```

Keep source-generation work outside the Unity bundle membership directory.
Copy only selected outputs into the Unity project. This prevents concepts,
turntables, masks, and unused alternatives from shipping accidentally.

## Reproducible generator contract

Every generator should:

- accept explicit input/output paths;
- use a recorded random seed;
- declare tool/library versions;
- fail on missing inputs instead of creating placeholders;
- avoid timestamps and absolute paths in output where possible;
- write to a temporary file and replace only on success;
- print dimensions, format, channels, and hashes;
- support a check/dry-run mode when practical;
- never edit the installed game.

For AI-generated source art, record the tool/model, prompt, references,
selection/edit decisions, and license/usage basis. The prompt is provenance,
not acceptance evidence.

## Mesh lane

1. Define axes, real-world dimensions, pivot, collider, LOD, and attachment
   requirements before generation.
2. Generate with Blender Python, OpenSCAD, or a checked-in script.
3. Validate topology/extents and interchange format.
4. Render a deterministic turntable/contact sheet.
5. Import into Unity; commit its `.meta` and importer settings.
6. Create the exact game-facing prefab and name.
7. Build/probe/validate, then test held/placed/dropped states in game.

## Texture/material lane

1. State channel semantics and color-space intent per file.
2. Generate maps with Material Maker or seeded code.
3. Check sizes, alpha, numeric ranges, tiling seams, and packed-channel means.
4. Configure Unity imports before assigning materials.
5. Enable shader keywords and complete blend/depth/render state in code.
6. Inspect generated `.mat` YAML.
7. Test under multiple in-game light levels and distances.

## Icon lane

1. Keep a high-resolution source and transparent background.
2. Derive the exact deployed size with ImageMagick/Pillow.
3. Create a contact sheet at native and 2x/4x zoom.
4. Place the PNG in `UIAtlases/ItemIconAtlas/`, not the bundle.
5. Test atlas lookup by stem and inspect in inventory/perk/recipe contexts.

## Audio lane

1. Keep lossless source and a transformation script.
2. Report duration, channels, sample rate, peak, and loudness.
3. Import the clip and, when range matters, a deliberate AudioSource prefab.
4. Configure `sounds.xml` near/distant behavior and voice limits.
5. Validate load, then listen near, across fade, at maximum range, and under
   simultaneous events.

## VFX lane

1. Define presentation-only scope, duration, maximum live particles, LODs,
   distance culling, concurrency policy, and fallback.
2. Generate cards/meshes and complete transparent material state.
3. Put hard caps in the prefab, not only in runtime selection code.
4. Verify all particle curves/modules in the Unity log and live client.
5. Test repeated effects for frame time, allocations, orphans, obstruction,
   flicker, and accessibility.

## Evidence packet

For a release candidate preserve:

- source commit;
- tool/editor/game versions;
- bundle and manifest SHA-256;
- `7dtd-assets inspect --json` output;
- `7dtd-assets validate` output;
- client/server logs for the exact run;
- screenshots/turntables/listening notes;
- negative-control result where graceful fallback matters.
