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

assets-src/bundle/
└── selected outputs only — every file here becomes a bundle asset
```

`assets-src/bundle/` is the membership folder by default; a mod that opted into
an editor uses `tools/shamway/UnityProject/Assets/ModAssets/Bundle/` instead,
and commits every `.meta` file with its asset.

Either way, keep source-generation work **outside** the membership directory
and copy only selected outputs in. This prevents concepts, turntables, masks,
and unused alternatives from shipping accidentally.

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
2. Generate with Blender Python, OpenSCAD, `shamway generate mesh`, or a
   checked-in script.
3. Validate topology/extents and interchange format (`shamway check-mesh`).
4. Render a deterministic turntable/contact sheet.
5. Copy the chosen file into `assets-src/bundle/` under the stem the XML will
   ask for. `shamway build` turns it into the prefab the game resolves, plus
   its mesh, material and shader; a texture named `<stem>_albedo` beside it is
   bound to that material.
6. Build/probe/validate, then test held/placed/dropped states in game.

With `bundle_source = "unity"`, steps 5 and 6 are different: import into the
Unity project, commit its `.meta` and importer settings, create the exact
game-facing prefab and name, then build. Take that route when the prop needs
lit or normal-mapped shading, SDCS extras, or Mecanim animation — none of
which the writer's unlit mesh pass covers. Named glTF children, glTF skins,
`.vfx` ParticleSystems, and legacy animation clips
(`anim.py`, see `docs authoring entities`) are synthesized without an editor.
`shamway generate creature` is the one-shot on-ramp for a reusable entity
from a shipped rig (atlas + idle/head/walk + hide); `--scale` and `--coat`
morph size and palette without editing the mesh.

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
4. Drop the albedo into `assets-src/bundle/` as `<mesh stem>_albedo.png` and
   it is bound for you. Steps 5 to 7 are the Unity lane, and are what the
   extra maps are *for* — the editorless material has one texture property and
   no keywords, so a normal or packed mask has nowhere to go on that path.
5. Configure Unity imports before assigning materials.
6. Enable shader keywords and complete blend/depth/render state in code.
7. Inspect generated `.mat` YAML.
8. Test under multiple in-game light levels and distances.

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
4. Create a contact sheet at native and 2x/4x zoom, on a light *and* a dark
   background: `shamway generate icon … --contact-sheet sheet.png` writes both
   rows. Two grounds because the two ways an icon fails are opposite, and each
   is invisible on the other — a dark-edged subject vanishes into an inventory
   slot, and a cutout that kept a white halo only shows it against light.
5. Place the PNG in `UIAtlases/ItemIconAtlas/`, not the bundle.
6. Run `shamway check-icons`: cell shape, alpha, and every `CustomIcon` key.
7. Test atlas lookup by stem and inspect in inventory/perk/recipe contexts.

## Audio lane

Full lane, with the engine facts that decide audibility: [audio.md](audio.md).

1. Synthesize with `shamway generate sound` (a designed voice and a recorded seed) or
   keep a lossless source and a transformation script.
2. Gate it with `shamway check-sound`: mono, rate, level, clipping, DC
   offset, edge silence.
3. Copy the `.wav` into `assets-src/bundle/`, where it becomes an `AudioClip`
   with no editor. When range matters, a deliberate AudioSource prefab decides
   audibility, and that is a Unity-lane asset —
   `GeneratedAsset.AudioSourcePrefab(...)` — so a long-range sound is one of
   the reasons a mod opts into an editor.
4. Configure `sounds.xml` near/distant behavior and voice limits;
   `shamway generate sound sounds-xml` prints the entry.
5. Validate load, then listen near, across fade, at maximum range, and under
   simultaneous events.

## VFX lane

Full lane, with budgets, tiers, and the two silent material failures:
[vfx.md](vfx.md).

1. Define presentation-only scope, duration, maximum live particles, LODs,
   distance culling, concurrency policy, and fallback.
2. Generate cards with `shamway generate particle-card` (haze, streak) or
   `shamway generate cutout`, and complete transparent material state.
   `blend` is `additive` or `alpha` on the `.vfx` material; do not reuse
   opaque `Shamway/Unlit`.
3. Put hard caps in the prefab, not only in runtime selection code.
4. Put the systems in a `.vfx` declaration next to the card PNGs and
   `shamway build`. One file is one prefab / one `*_look` suite. Offset
   `shape.position` when layers must be judged apart. `inspect --deep`
   must show ParticleSystem counts. Modules the schema does not encode
   still want an editor.
5. Test repeated effects for frame time, allocations, orphans, obstruction,
   flicker, and accessibility. Visual sign-off is
   `playtest-synthesized.sh --look` or
   `playtest-acceptance.sh --suite <mod>_<stem>_look`, never mixed with
   `*_block_*`.

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
