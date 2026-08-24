# Agent-friendly asset workflows

Asset generation is safest when the editable source, transformation, checks,
and acceptance evidence are explicit. An agent should be able to regenerate a
derivative without guessing which GUI state produced it.

## Repository pattern

`shamway init` creates this, with a README that says what a provenance row
must carry:

```text
assets-src/
├── README.md                 # art direction, licenses, provenance, commands
├── icons/                    # generated or drawn sources, and cut-out RGBA
├── textures/                 # albedo, normal, packed mask sources
├── meshes/                   # Blender/OpenSCAD scripts and exported .glb
├── audio/                    # sound generators and their .wav
└── vfx/                      # particle card sources and opacity masks

tools/shamway/UnityProject/Assets/ModAssets/Bundle/
└── selected Unity inputs + every .meta file
```

Keep source-generation work outside the Unity bundle membership directory.
Copy only selected outputs into the Unity project. This prevents concepts,
turntables, masks, and unused alternatives from shipping accidentally.

The style contract for anything generated is [art-direction.md](art-direction.md);
the sound lane is [audio.md](audio.md); effects are [vfx.md](vfx.md).

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
- write the editable source **and** the byte-identical bundle copy in one
  run (`--promote` / `--also`), so the shipped file is the recorded design by
  construction;
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

1. State channel semantics and color-space intent per file, and the
   material profile per surface family — painted, bare metal, rubber,
   emissive — from [art-direction.md](art-direction.md).
2. Generate maps with `shamway generate texture-maps` (from an albedo, or
   `detail` for a tileable normal from seeded noise), Material Maker, or
   seeded code. Detail normals are periodic by construction; anisotropic for
   machined metal, isotropic and coarser for rubber.
3. Check sizes, alpha, numeric ranges, tiling seams, and packed-channel means
   (the mask must average back to the scalars it replaces).
4. Configure Unity imports before assigning materials.
5. Enable shader keywords and complete blend/depth/render state in code.
6. Inspect generated `.mat` YAML.
7. Test under multiple in-game light levels and distances.

## Icon lane

Two lanes, both first-class: generated or drawn art when the icon should show
something the mesh does not, and a render of the prefab when the icon should
*be* the item. See [art-direction.md](art-direction.md) for the choice, the
prompt pattern, and the key-colour convention.

1. Keep a high-resolution source; generate against a flat key colour rather
   than asking for transparency.
2. Cut the background out with partial alpha and de-spill
   (`shamway generate cutout key`), or photograph the item itself — the bundle
   prefab with `shamway render-icon` where an editor exists, the mesh file with
   `shamway generate mesh-icon` where one does not.
3. Derive the exact deployed cell — 160 x 160 for `ItemIconAtlas`.
4. Create a contact sheet at native and 2x/4x zoom, and check it on a light
   *and* a dark background.
5. Place the PNG in `UIAtlases/ItemIconAtlas/`, not the bundle.
6. Run `shamway check-icons`: cell shape, alpha, and every `CustomIcon` key.
7. Test atlas lookup by stem and inspect in inventory/perk/recipe contexts.

## Audio lane

Full lane, with the engine facts that decide audibility: [audio.md](audio.md).

1. Synthesize with `shamway generate sound` (a designed voice and a recorded seed) or
   keep a lossless source and a transformation script.
2. Gate it with `shamway check-sound`: mono, rate, level, clipping, DC
   offset, edge silence.
3. Import the clip and, when range matters, a deliberate AudioSource prefab —
   `GeneratedAsset.AudioSourcePrefab(...)`.
4. Configure `sounds.xml` near/distant behavior and voice limits;
   `shamway generate sound sounds-xml` prints the entry.
5. Validate load, then listen near, across fade, at maximum range, and under
   simultaneous events.

## VFX lane

Full lane, with budgets, tiers, and the two silent material failures:
[vfx.md](vfx.md).

1. Define presentation-only scope, duration, maximum live particles, LODs,
   distance culling, concurrency policy, and fallback.
2. Generate cards/meshes and complete transparent material state.
3. Put hard caps in the prefab, not only in runtime selection code.
4. Verify all particle curves/modules in the Unity log and live client.
5. Test repeated effects for frame time, allocations, orphans, obstruction,
   flicker, and accessibility.

## Keep an asset inventory

One table, in the mod's own docs, with a row per gameplay object rather than
per file. It is the only artifact that answers "what is left" without reading
the whole repository:

| Gameplay object | Assets it owes | Current state | Reviewed by a human? |
|---|---|---|---|
| `myModWorkbench` | placed model, icon | bundle prefab + 160 px atlas cell | no — placement and bounds unchecked |

Three rules keep it honest:

- **A new gameplay object is a new row**, added when it is added to `Config/`.
- **Say what is a stand-in.** Reusing a vanilla asset is a legitimate
  prototype decision; an inventory that does not distinguish a stand-in from
  finished art will eventually ship one as the other.
- **"Reviewed" means a person looked or listened.** A green offline run is not
  a review, and writing it in that column is how a mod ends up believing its
  art was checked.
- **Three states, not two.** Stand-in, accepted, and *mod-owned but failed
  review* — the third is the one that gets lost, because the asset exists.
- **Re-verify the table against `Config/` and the installed game**, not
  against prose, whenever either changes. The source project's table was
  stale on two rows (a wrong scale, an un-overridden prefab) until it was.
- **Keep an owed-sounds list beside it** — events still silent — because an
  unauthored sound produces no error ([audio.md](audio.md)).

## Evidence packet

For a release candidate preserve:

- source commit;
- tool/editor/game versions;
- bundle and manifest SHA-256;
- `shamway inspect --json` output;
- `shamway validate`, `check-icons`, and `check-sound` output;
- client/server logs for the exact run — **copied out**, because the client
  rewrites `output_log_client__*.txt` on every launch, so a path into the
  live log directory is not evidence;
- the `shamway client log --json` classification for the run;
- screenshots/turntables/listening notes, each capture named for the
  observable it records (`held-mesh-scale`, `placed-bounds`,
  `detonation-audio-near`) with the stated expectation beside it, so a later
  reader knows what a picture was meant to prove. `shamway client capture
  LABEL --observable "..."` writes exactly that pairing into
  `.local/acceptance/manifest.json`, with the frame's own hash, and leaves the
  verdict field empty for the person who looked;
- the audio state of the run (muted or listening);
- negative-control result where graceful fallback matters.
