# Generated-creature reference renders

Ground-truth, isolation renders of the four generated creature rigs, for
**comparing against in-game `--look` frames**. They are the shape the creature
should have in a live frame, so a frame that shows only terrain (or the player /
the spawn-area car) can be judged against what actually should be there.

> These are **clay geometry references**, not the in-game look. The creature's
> albedo is a separate PNG bound by the writer's `_albedo` convention (`*.glb`
> carries geometry + skin only), so this render is a flat dark-clay silhouette.
> It answers *does the in-game frame contain this body shape?*, not *does the
> colour read right?*.

## The clay sheets

| Stem | Rig | Source | Rendered |
|---|---|---|---|
| `shamwaySelfTestCreature` | quadruped | `assets-src/bundle/shamwaySelfTestCreature.glb` | `shamwaySelfTestCreature_reference.png` |
| `shamwaySelfTestBird` | bird | `assets-src/bundle/shamwaySelfTestBird.glb` | `shamwaySelfTestBird_reference.png` |
| `shamwaySelfTestArachnid` | arachnid | `assets-src/bundle/shamwaySelfTestArachnid.glb` | `shamwaySelfTestArachnid_reference.png` |
| `shamwaySelfTestDino` | dinosaur | `assets-src/bundle/shamwaySelfTestDino.glb` | `shamwaySelfTestDino_reference.png` |
| `shamwaySelfTestCrocodile` | crocodile | `assets-src/bundle/shamwaySelfTestCrocodile.glb` | `shamwaySelfTestCrocodile_reference.png` |
| `shamwaySelfTestHumanoid` | humanoid | `assets-src/bundle/shamwaySelfTestHumanoid.glb` | `shamwaySelfTestHumanoid_reference.png` |

Each `_reference.png` is a 2×3 contact sheet of six views: front, 3/4, side,
back, back-3/4, other-side. The camera is orthographic, framed from the model's
union bounds with a margin (no angle can clip), on a light background so the
dark silhouette reads.

## Regenerate

Requires Blender (headless):

```bash
blender -b -P reference/creatures/render_creatures.py -- \
  assets-src/bundle/shamwaySelfTestCreature.glb reference/creatures shamwaySelfTestCreature 640
```

`render_creatures.py` imports the `.glb`, computes the world bounds, applies a
uniform dark-clay material, sets a light studio (key + fill) and the **Standard**
view transform (Blender's default AgX washes the greys out), then renders the six
views and montages the contact sheet. Change the last argument to change the
render size.

## Why they exist

The entity lane's `--look shamwaySelfTestCreature` run (a `CaseDef.WalkEntity`)
captures a clip, but the generated creature does **not** rasterize in the live
Proton/d3d11 client (it does draw in the editor's `verify-bundle --draw`). The
`frame-div` probe in `hordeforge/7dtd-playtest` (`CaseDef.WalkEntity`'s assert)
confirms the mesh is grounded, full-size, enabled and active, yet the 48 captured
frames show only terrain, the player and a spawn-area car — never the creature.
These references are what should be there. To compare, regenerate and re-run
`shamway script playtest-synthesized.sh --look shamwaySelfTestCreature`, then
place the captured frames next to these sheets.

See `docs/authoring/entities.md` and the "CORRECTION" section in
`docs/research/research-provenance.md` for the diagnosis and the open
d3d11-isolation test.
