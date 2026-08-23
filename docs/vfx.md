# Visual effects

Particle effects are the asset class where "it built and it loaded" is furthest
from "it works". A VFX prefab can pass every gate in this pipeline and still
render as flat orange polygons, or flood the client log with thousands of error
lines a second, or drop a player's frame rate whenever two of them overlap.
Each of those has happened; each has a specific, cheap preventative below.

## Quick start

```bash
7dtd-assets generate cutout luma assets-src/vfx/smoke-mask.png \
    assets-src/vfx/smoke-card.png --black-point 15
# import the card, build the prefab with GeneratedAsset.ParticleMaterial(...)
7dtd-assets build
7dtd-assets inspect --deep Resources/mymod.unity3d    # did the systems survive?
```

Everything below is detail.

## Scope: presentation only

Decide this before authoring anything, and write it down. A visual effect is a
*presentation of* something that already happened; it must never decide damage,
radius, timing, collision, spawn behaviour, or any multiplayer state. Two
consequences follow:

- The effect runs **client-side**. A server that never renders it must reach
  the same gameplay result.
- If the prefab fails to load, the mod logs one error and continues. Vanilla
  presentation stays in place underneath, so a missing effect costs polish, not
  playability. Test that fallback deliberately, by making the bundle
  unavailable — it is the one path nobody exercises by accident.

## The engine module trap, again

`ParticleSystem` and `ParticleSystemRenderer` are stripped from a bundle when
`com.unity.modules.particlesystem` is absent from the Unity project's
`Packages/manifest.json`. The editor still creates them at author time — the
stripping only happens on serialization — so nothing fails until a player loads
an empty prefab.

The pipeline rejects such a build on the disabled-module log gate, and the
scaffolded project declares the module. What the class-142 gate **cannot** tell
you is whether a specific component survived, which is what
`inspect --deep` is for:

```bash
7dtd-assets inspect --deep Resources/mymod.unity3d
#   myModBlastVfx (GameObject) [7 objects: ParticleSystem=6, ParticleSystemRenderer=6, Transform=7]
```

Six systems in the prefab and six in the bundle is the proof. Zero, with a
green build, is the exact signature of a stripped module.

## The two silent material failures

**A particle card renders opaque unless the material is fully set up.** Setting
`_Mode` is not enough and this is the most expensive material trap in the
pipeline: `_Mode` is read by the shader's *inspector GUI*, which is what
normally applies the blend factors, depth write, keywords, and render queue —
and no GUI runs in a batch build. The material stays in `Particles/Standard
Unlit`'s default **opaque** state, and the effect renders as enormous flat
polygons with hard black edges that ignore their own alpha. Every offline check
passes.

The mode numbers are a second trap on top of the first: that shader enumerates
`Opaque, Cutout, Fade, Transparent, Additive, Subtractive, Modulate`, so a
plausible-looking `additive ? 2 : 0` asks for *Fade* and *Opaque*.

Use `GeneratedAsset.ParticleMaterial(path, tint, card, additive)`, which mirrors
Unity's own `StandardParticleShaderGUI.SetupMaterialWithBlendMode`. Then verify
by reading the built `.mat` rather than by trusting the assignment:

```bash
grep -nE "_Mode:|_SrcBlend:|_DstBlend:|_ZWrite:|m_CustomRenderQueue" \
  tools/7dtd-assets/UnityProject/Assets/ModAssets/Bundle/**/*.mat
```

Additive is `_SrcBlend: 5` (SrcAlpha) with `_DstBlend: 1` (One); fade is `5`
with `10` (OneMinusSrcAlpha). Both want `_ZWrite: 0`, `m_CustomRenderQueue:
3000`, and `_ALPHABLEND_ON` in `m_ValidKeywords`.

**A curve-mode mismatch logs on every update.** `velocityOverLifetime` requires
all three axes to share one `MinMaxCurve` mode. Assigning a plain float to `x`
and `z` while `y` is a curve makes Unity log `Particle Velocity curves must all
be in the same mode` on *every frame the system updates* — thousands of lines a
second in the client, and nothing at all offline. Express a stationary axis as
`GeneratedAsset.ZeroCurve()`, never as `0f`.

The general form of both, worth stating once: **setting a shader property is
not the same as putting the material into the state that property names.**
Assume any script-authored material is wrong until its keywords, blend state,
and render queue have been read back out of the `.mat`.

## Budgets and distance LOD

An effect that looks right at 40 m and costs 400 particles is not finished. Put
a hard cap in the **prefab**, not only in the runtime code that chooses which
prefab to spawn — a distance LOD that picks the cheap tier is no protection if
the cheap tier was never cheap:

```csharp
GeneratedAsset.BudgetParticles(root, allowance);   // throws when over budget
```

A workable tier shape, from a large-explosion effect that shipped:

| Tier | Viewer distance | Live particle cap | What it keeps |
|---|---:|---:|---|
| High | ≤ 400 m | 384 | every stage, plus one short light pulse |
| Medium | ≤ 1,400 m | 160 | every stage, fewer particles |
| Low | ≤ 2,500 m | 48 | the silhouette only — no ground-level detail |
| None | beyond 2,500 m | 0 | vanilla presentation alone |

Two rules that come with it: ground-level stages (dust, a shock ring) are not
readable past roughly 1,400 m, so the silhouette tier should spend nothing on
them; and concurrent effects need a policy — one tier down per effect still
alive, never below the silhouette, and nothing at all past a small fixed count.
Prune destroyed instances before counting.

Log the chosen tier and the measured distance when the effect spawns. That one
line is the difference between "the LOD rule exists" and "the LOD rule ran".

## Staging a large effect

An effect that reads as a single event has stages with distinct
responsibilities and overlapping windows. The shape below is generic; the
timings are the part that must match the gameplay it presents.

| Stage | Responsibility |
|---|---|
| Flash | one brief additive flash, optionally a short point-light pulse; never a sustained full-screen effect |
| Fireball | expanding emissive core, broken into a restrained set of puffs rather than one opaque sphere |
| Ground wave | dust thrown outward across the terrain, decelerating — the only stage that travels horizontally |
| Column | the rising stem, born lit from the fireball beneath it |
| Cap | the head, emitted where the column arrives |
| Dissipation | drift, desaturate, and fade without a hard edge or a persistent wall |

**Derive the cap's start time; do not choose it.** If the column climbs at a
known speed to a known height, the cap begins when the first particles arrive.
A cap that starts earlier hangs above a gap, which is the single most common
reason a mushroom-shaped effect does not read as one.

**Match the effect's duration to the gameplay it presents.** An effect that
runs for a third of the event it describes reads as a bang followed later by
unrelated damage. This is a timing bug that looks like an art problem.

Material profiles, expressed as required behaviour rather than filenames:

| Profile | Required behaviour |
|---|---|
| Flash / fire | unlit additive, HDR colour, vertex-colour and age control, no depth write |
| Smoke / cap | unlit alpha blend, texture or flipbook input, age-driven alpha, slow noise motion, no shadows |
| Ring | unlit alpha or additive, radial falloff and expansion, no depth write, no terrain modification |

No particle should collide, cast or receive shadows, or generate mesh at
runtime. Avoid screen-space distortion, heavy post-processing, compute shaders,
and depth-dependent behaviour unless the pipeline has proven they work in the
shipped client.

## Custom shaders

Prove the effect with stock materials first, and reach for a custom shader only
when that proof demonstrably cannot produce the required result — then record
the specific defect that forced it. The source project's entire VFX and
world-material work needed no custom shader: everything the material profiles
ask for was expressible in stock `Standard` and `Particles/Standard Unlit`. Two
silent traps (keywords and import type), not a missing shader, accounted for
every failure that looked like one.

## Acceptance

Offline, before a client: `build` passes the module and class-142 gates,
`inspect --deep` shows the systems survived, and the `.mat` grep shows real
blend state.

In a client, and only there:

1. The effect spawns on the real event, and the log line naming the tier and
   distance appears.
2. The client log is **clean while it runs** — a curve-mode error only exists
   during playback.
3. It reads correctly from every viewpoint that matters: close, far, above.
4. Flash readability and accessibility: no persistent blindness, excessive
   bloom, or full-screen flicker.
5. Repeated effects hold frame time, do not grow managed allocations, and leave
   no orphans.
6. With the bundle deliberately unavailable, gameplay and vanilla presentation
   still complete.

The first human look at an effect routinely finds two defects that every
automated check passed over. Budget for it, and do it before any further
authoring — art reworked after a review is art authored twice.
