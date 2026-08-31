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
| `creatures/` | editable entity sources: the `--atlas` UV manifest + role map behind each generated creature (provenance, **not** bundle content) |
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
| `shamwaySelfTestCreature` | `shamway generate entity bundle/shamwaySelfTestCreature.glb --rig quadruped --atlas creatures/shamwaySelfTestCreature.atlas.json` | the quadruped rig, default parts, fully deterministic (no seed); `--atlas` gives each part its own UV cell so a hide can paint the feet apart from the body | `bundle/shamwaySelfTestCreature.glb` | yes — look signed off 2026-08-30 |
| `shamwaySelfTestCreature_albedo` | `shamway generate hide bundle/shamwaySelfTestCreature_albedo.png --atlas creatures/shamwaySelfTestCreature.atlas.json --seed 7 --base 118,96,66 --fur 150,124,86 --paw 22,16,12 --limb 74,58,40 --outline 12,10,8 --size 256` | a role-aware atlased hide, dark warm palette: paws near-black, limbs a deep shade, body brown, gutters outlined — so the feet/legs read against the body and the terrain (the earlier pale cream coat washed out under daytime and read as one blob) | `bundle/shamwaySelfTestCreature_albedo.png` | yes — judged with the creature |
| `shamwaySelfTestBird` | `shamway generate creature bundle/shamwaySelfTestBird.glb --rig bird --atlas creatures/shamwaySelfTestBird.atlas.json --hide bundle/shamwaySelfTestBird_albedo.png --coat slate --seed 7 --size 256` | bird rig, Z-keel torso, neck that meets the head, legs that meet the feet, Idle1 (bob+flap+head+in-place walk+tail sway) + Walk on perched legs (wings are not walk legs), slate role-aware hide | `bundle/shamwaySelfTestBird.glb` + `_albedo.png` + `.anim.json` | look run 2026-08-31 (`pass=1`); frame filed, not a human sign-off |
| `shamwaySelfTestArachnid` | `shamway generate creature bundle/shamwaySelfTestArachnid.glb --rig arachnid --atlas creatures/shamwaySelfTestArachnid.atlas.json --hide bundle/shamwaySelfTestArachnid_albedo.png --coat charcoal --seed 7 --size 256` | arachnid rig, flat abdomen, legs splayed outboard, eight-leg tetrapod Walk, peach hide (tarsi painted as paws) | `bundle/shamwaySelfTestArachnid.glb` + `_albedo.png` + `.anim.json` | look run 2026-08-31 (`pass=1`); frame filed, not a human sign-off |
| `shamwaySelfTestDino` | `shamway generate creature bundle/shamwaySelfTestDino.glb --rig dinosaur --atlas creatures/shamwaySelfTestDino.atlas.json --hide bundle/shamwaySelfTestDino_albedo.png --coat olive --seed 7 --size 256` | dinosaur rig, overlapping horizontal theropod, biped Walk on Thighs, olive hide | `bundle/shamwaySelfTestDino.glb` + `_albedo.png` + `.anim.json` | look run 2026-08-31 (`pass=1`); clay six-view has the side/back the live rotation frame missed; frame filed, not a human sign-off |
| `shamwaySelfTestCrocodile` | `shamway generate creature bundle/shamwaySelfTestCrocodile.glb --rig crocodile --atlas creatures/shamwaySelfTestCrocodile.atlas.json --hide bundle/shamwaySelfTestCrocodile_albedo.png --coat rust --seed 7 --size 256` | crocodile rig, overlapping long low hull, four-leg sprawl Walk, rust hide | `bundle/shamwaySelfTestCrocodile.glb` + `_albedo.png` + `.anim.json` | look run 2026-08-31 (`pass=1`); frame filed, not a human sign-off |
| `shamwaySelfTestHumanoid` | `shamway generate bind body.obj --extra head.obj --extra hands.obj --extra feet.obj --rig humanoid --head-lift --neck --height 1.75 --stretch-x 1.12 --anim bundle/shamwaySelfTestHumanoid.glb` then `shamway generate hide … --base 198,142,108 --fur 220,168,132 --limb 170,118,88 --paw 96,62,48 --outline 56,36,28 --seed 11 --size 256` | split-OBJ bind with `--head-lift --neck`, Idle1 A-pose (Z drop) + Y arm swing + thigh/shin walk, peach hide; feet still deferred | `bundle/shamwaySelfTestHumanoid.glb` + `_albedo.png` + `.anim.json` | not signed off; feet deferred |
| _example_ | `icons/nuke-v4.png` | image generation, prompt below; cut out with `shamway generate cutout key --size 160` | `UIAtlases/ItemIconAtlas/myModNuke.png` | not yet |
| `flashCard.png` | `shamway generate particle-card haze --size 256 --seed 3 --lobes 7` | procedural haze, white RGB, shape in alpha | `assets-src/bundle/flashCard.png` | not yet |
| `smokeCard.png` | `shamway generate particle-card haze --size 256 --seed 11 --lobes 9 --softness 7` | procedural haze, white RGB, shape in alpha | `assets-src/bundle/smokeCard.png` | not yet |
| `sparkCard.png` | `shamway generate particle-card streak --size 64 --width 0.12 --length 0.88` | procedural streak, white RGB, shape in alpha | `assets-src/bundle/sparkCard.png` | not yet |

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
- `shamway generate bind` — skin an authored mesh onto a shipped rig

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
