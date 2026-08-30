# Editable asset sources for ShamwaySelfTest

Nothing in this directory ships. It holds the sources, generators, and
provenance behind the assets that do: the deployable artifacts are the bundle
at `Resources/shamwayselftest.unity3d`, the PNGs under `UIAtlases/`, and nothing else.

Keep it this way round on purpose. Concepts, rejected alternatives, masks,
turntables and full-resolution sources live here; only a *selected* output
reaches `assets-src/bundle/`, so an unfinished asset cannot ship merely by sitting
in the wrong folder.

## Layout

| Directory | What belongs in it |
|---|---|
| `bundle/` | **bundle content** — every file here becomes an asset named by its stem; copy only selected outputs in |
| `icons/` | atlas icons: generated or drawn sources, and the cut-out RGBA derivative |
| `textures/` | albedo, normal, and packed mask sources for materials |
| `meshes/` | Blender/OpenSCAD scripts and their exported .glb |
| `audio/` | sound generators and their .wav output |
| `vfx/` | particle card sources and opacity masks |

## Every asset owes a provenance row

Add one row per asset to the table below when you add the asset. An entry that
cannot be regenerated from what is written here is not finished.

| Asset | Source | How it was made | Deployed as | Reviewed |
|---|---|---|---|---|
| `shamwaySelfTestProp` | `shamway generate mesh` (see the prop's own history) | a full 1 × 1 × 1 m block, Y-up, UV0 | `bundle/shamwaySelfTestProp.glb` | yes — the playtest asserts it by value |
| `shamwaySelfTestCreature` | `shamway generate entity bundle/shamwaySelfTestCreature.glb --rig quadruped` | the quadruped rig, default parts, fully deterministic (no seed) | `bundle/shamwaySelfTestCreature.glb` | not yet — the `--look` run is the owed picture |
| `shamwaySelfTestCreature_albedo` | PIL, one deterministic script (256×256: moss green, dorsal stripes, pale snout patch, eye marker) | re-run the recorded script byte-for-byte | `bundle/shamwaySelfTestCreature_albedo.png` | not yet — judged with the creature |
| _example_ | `icons/nuke-v4.png` | image generation, prompt below; cut out with `shamway generate cutout key --size 160` | `UIAtlases/ItemIconAtlas/myModNuke.png` | not yet |

For generated art, record the model or tool, the **exact prompt**, the
references used, which candidate was selected and why, and the licence basis.
A prompt is provenance, not acceptance evidence — it says where the pixels came
from, never that they are good. `shamway prompt KIND --subject "..."` renders
the house pattern to start from; record what you actually sent, not the
template, because the subject and the negatives are what you changed.

For generated audio, meshes, and textures, the generator script *is* the
provenance: record the command and its `--seed`. Re-running it must reproduce
the file byte-for-byte, so a diff means someone changed the design.

## The commands

Nothing here is a copy of the pipeline. Author with its generators and read its
rules through the command itself — there is no checkout of it to point at:

- `shamway generate --list` — the generators, and what each needs
- `shamway prompt --list` — the house-style image prompts, rendered ready to use
- `shamway docs art-direction` — the style contract and prompt patterns
- `shamway docs audio` — the sound lane
- `shamway docs mod-repo-layout` — what belongs here vs in the pipeline

```bash
shamway generate --list
shamway prompt --list
shamway docs art-direction
shamway docs audio
shamway docs mod-repo-layout
```

```bash
shamway generate sound blast audio/thing.wav --seed 7     --promote bundle/myModThing.wav
shamway generate cutout key icons/src.png ../UIAtlases/ItemIconAtlas/thing.png     --size 160 --pad 0.9 --trim
shamway generate texture-maps textures/paint.png --out-dir textures/derived --stem myModPaint     --also bundle
shamway generate mesh meshes/thing.glb --shape box --size 1 0.6 0.8
```

Promote from the generator (`--promote`, `--also`), never by copying by hand:
the bundle copy is then the recorded design by construction.

Then gate each lane, build, and validate — from the mod root:

- `shamway capabilities --json` — what is installed, and what it unlocks
- `shamway check-icons` — every atlas PNG and CustomIcon key
- `shamway generate mesh-icon` — photograph a mesh file into an icon, no editor

```bash
shamway capabilities --json
shamway check-mesh assets-src/meshes/thing.glb
shamway check-sound assets-src/audio/thing.wav
shamway check-icons
shamway build && shamway validate
```

Then a fresh client, and a human look or listen. Offline gates are necessary,
never sufficient:

```bash
shamway client deploy .
shamway client launch --mod-name ShamwaySelfTest --run-seconds 120 --mute
```

A listening run is never `--mute`. Record in the provenance row which of the
two a person did.
