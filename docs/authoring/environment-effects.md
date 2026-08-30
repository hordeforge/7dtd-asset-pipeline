# Environment effects

Rain, fog, cloud cover, and the colour of the daylight — the asset class that
is **not an asset**. A zone that is supposed to feel poisoned does not become
poisoned by adding particles to it: the sky stays clear, the sun stays bright,
and the effect reads as floating specks over ordinary weather. 7 Days to Die
already owns weather, fog, and light, and an environment effect is a mod
driving those controls. The bundle only supplies character on top.

## Quick start

- drive the engine's weather and sky controls from a replicated value
- add the particle layer last, as character, never as the effect itself

```bash
shamway generate particle-card haze assets-src/vfx/zoneHaze.png --size 512
shamway generate particle-card streak assets-src/vfx/zoneRain.png
shamway build
```

Everything below is detail.

**What needs an editor here, and what does not.** The engine controls below are
C# in the mod's own DLL and need nothing from a bundle, so the effect itself
works on `bundle_source = "none"` and on the default synthesized path alike.
The cards above are textures, which the editorless writer packs. The particle
system that carries them is a `.vfx` declaration on
`bundle_source = "synthesized"` — see [vfx.md](vfx.md). Lit Particles/Standard
Unlit keywords and modules that schema does not encode still want an editor.
Weather itself never does.

## A particle prefab is not weather

This is the mistake worth naming first, because it is the one that gets built.
A viewer-attached particle system is cheap, visible in the editor, and passes
every gate in this pipeline — so it feels finished. In a live client it is a
handful of sprites drifting through unchanged sunny weather. The player reads
it as a glitch, not as an environment.

The order that works is the opposite of the order that is easy:

1. Drive the engine's weather, fog, and light with the value the effect
   presents. This alone, with no bundle at all, already looks like weather.
2. Only then add particles for what the stock weather cannot express — acid
   green rain, ash, spores, an aerosol tint.

An environment effect therefore works on a mod that declares
`bundle_source = "none"`. Losing the bundle costs the character layer, not the
effect.

## The controls the engine already has

Measured with `ilspycmd` against the installed `Assembly-CSharp.dll` for
**V 3.1.0 (b14)** — the display form the engine itself prints;
`SerializableString` gives the same build unambiguously as `V.3.10.14`. See
[research/research-provenance.md](../research/research-provenance.md), which
owns the symbol list.

| Control | What it does |
|---|---|
| `WeatherManager.forceClouds` | overrides cloud cover, `0`–`1`; **`-1` means "not forced"** |
| `WeatherManager.forceRain` | overrides precipitation, `0`–`1`; `-1` means "not forced" |
| `WeatherManager.Instance.GetCurrentCloudThicknessPercent()` | the current cover already on the `0`–`1` scale — use this, not `GetCloudThickness()` |
| `WeatherManager.Instance.GetCurrentRainfallPercent()` | the current precipitation, `0`–`1`, despite the name |
| `WeatherManager.Instance.CloudsFrameUpdateNow()` | applies a cloud change now instead of at the next natural update |
| `SkyManager.SetFogDebug(density, start, end)` | the fog volume the effect actually lives in |
| `SkyManager.SetFogDebugColor(color)` | fog tint — the cheapest "this air is wrong" signal there is |
| `SkyManager.GetFogDensity()` | the current density |
| `SkyManager.SetWeatherLightScale(scale)` | daylight reduction, `1` being untouched |
| `SkyManager.fogDebugDensity` / `fogDebugStart` / `fogDebugEnd` / `fogDebugColor` | what was set before you arrived; capture these to restore |

**The two getters are on different scales despite their names.**
`GetCloudThickness()` returns a percentage, `0`–`100`, while `forceClouds`
takes `0`–`1`; `GetCurrentRainfallPercent()` is already `0`–`1` and needs no
conversion. The engine ships the conversion as
`GetCurrentCloudThicknessPercent()`, so reach for that rather than
hand-rolling `* 0.01f` and eventually forgetting it somewhere.

`WeatherManager.ParticlesFrameUpdate` applies the stock storm light scale at
its end, which is why a light reduction belongs in a **postfix** on it: a value
written anywhere else is overwritten on the next frame that has weather in it.

## Save, clamp, restore

These are global statics on the client, not per-effect state. Four rules, each
with a visible failure when it is skipped:

- **The saved values are sentinels, not weather.** `forceClouds` and
  `forceRain` are **`-1f`** when nothing is forcing them, and every reader
  gates on `>= 0f`; `SkyManager.fogDebugDensity` is `-1f`, and
  `fogDebugColor` is ignored unless its alpha is above zero. Restoring means
  writing those sentinels back. A helper that "resets to zero" instead pins
  the sky permanently clear and permanently dry, and **nothing logs** — this
  is the easiest way to get an environment effect wrong.
- **Capture once, on entry.** Read every value the effect will write before
  writing any of them, behind a flag that makes it happen exactly once. Do not
  re-read the baseline each frame: `GetCurrentCloudThicknessPercent()` and
  `GetCurrentRainfallPercent()` return *your own override* while you are
  forcing, so a per-frame re-capture ratchets the effect to full within a few
  frames and never comes back down.
- **Clamp against that baseline, do not replace it.** Take
  `Mathf.Max(baseline, yourValue)` for cover, rain, and fog density, and
  `Mathf.Min` for the light scale. Assigning directly *erases a stronger
  vanilla storm* — the effect makes a thunderstorm sunnier, which is the exact
  opposite of what it is for. The honest limit, which follows from the rule
  above: this protects the storm that existed **at entry**, not one that rises
  while the player is inside. There is no way to read the unforced value while
  forcing it.
- **Two restore paths, and neither one covers the other.** Put the values back
  when the effect ends — that is the walking-out-of-the-zone case, and the
  engine will never do it for you. Also reset on a world change: the engine's
  own `WeatherManager.Cleanup()` clears the force fields and
  `SkyManager.Cleanup()`/`Reset()` clear the fog debug state and put
  `weatherLightScale` back to `1f`, but only at teardown. A reset driven from
  the player tick is the mirror image: it cannot run while no world is loaded,
  so it lands on the first tick of the *next* world. Keep both.

## Where it attaches

Client only. `EntityPlayerLocal.OnUpdateLive` is the local player's own
per-tick update, so a postfix on it exists only where there is a local player —
a dedicated server never constructs one. The light postfix is client-only for a
second, independent reason: `ParticlesFrameUpdate` is an instance method taking
an `EntityPlayerLocal`, called with the primary player, so it cannot fire on a
dedicated server even without a guard. Guard on
`GameManager.IsDedicatedServer` anyway, and wrap the tick body so a
presentation fault cannot take the player's update loop with it: report the
failure once, then stay quiet.

**Apply the environment before instantiating the prefab.** This ordering is
what makes the no-bundle path degrade instead of vanishing: the weather, fog,
and light are already set when the prefab load is attempted, and a failed load
only logs and returns. A helper written the other way round — instantiate,
bail on failure — silently gives a mod with `bundle_source = "none"` nothing
at all, which is the same symptom as a broken effect.

**The effect is a readout, never an input.** The server owns the zone, the
damage, and the spawns; the client is presenting a value that has already been
replicated to it. Nothing in the game may read the effect back. A weather
override that another system consults is a gameplay mechanic that lives in the
presentation layer, where the first client without a bundle breaks it.

**The particle layer follows the viewer; it is not the zone.** The client is
usually not told the boundary at all. Density does the talking: drive
`emission.rateOverTimeMultiplier` from the same replicated value, with a
visibility floor and hysteresis so walking the rim shows a gradient rather than
a strobe. [vfx.md](vfx.md) owns that pattern and the budget for an effect
measured in hours rather than seconds.

## The cards

Two shapes cover almost every weather layer, and neither is worth a generated
image — an image model asked for "a soft grey blob" returns a planet:

```bash
shamway generate particle-card haze assets-src/vfx/zoneHaze.png --size 512
shamway generate particle-card streak assets-src/vfx/zoneRain.png
```

`haze` is a broad, low aerosol puff; `streak` is one falling drop, flake, or
cinder. Both come out white with the shape in the alpha channel, so the
**material** carries the colour: one streak card serves acid rain, ash, and
snow.

For a card with real drawn structure, prompt for one — `shamway prompt
opacity-mask` — and bring it in with the mode that matches what the model
actually returned:

```bash
shamway generate cutout alpha assets-src/vfx/haze-src.png assets-src/vfx/zoneHaze.png --size 512 --pad 1.0
shamway generate cutout luma assets-src/vfx/haze-mask.png assets-src/vfx/zoneHaze.png --black-point 15
```

**A generated "opacity mask" often arrives with alpha already baked in, and
that alpha is not its own brightness.** The source this rule came from peaks at
alpha 251 where its brightness peaks at 135. Run `cutout luma` on such a file
and it recomputes alpha from brightness, capping the card near half opacity —
a visibly fainter particle, with nothing in the pipeline to flag it. `cutout
alpha` keeps the source's alpha and only whitens the RGB; use `luma` for a true
grey-on-black mask with no alpha at all.

You do not have to guess which one you have: `cutout alpha` refuses a source
with no alpha channel and names `luma` in the error, and it prints the coverage
it kept, so a card that came out at 53% opaque is visible in the output rather
than in the game a week later.

Give the haze and the rain **separate materials and separate cards**. Reusing a
detonation's tall, opaque smoke card for a persistent low haze is a specific
failure the source project shipped and then had to correct: the character of a
card built for one dramatic event is wrong for air that hangs around for two
in-game days.

The prefab's stem is referenced only by your C#, never by XML, so declare it in
`code_references` in `.shamway.toml` or the reference gate cannot see it.

## Acceptance

Every offline gate here is worth exactly what it is worth elsewhere: a bundle
that loads proves the card and the prefab exist. **The environment part cannot
be proven offline at all** — it is engine state on a running client, and the
only evidence is a look.

Look at all five, because each one has caught a different bug:

- **In the effect, by day.** Is the sky actually changed, or is it particles?
- **By night.** A light reduction that reads as atmosphere at noon reads as a
  broken flashlight at midnight.
- **Indoors.** Fog density that is right outside can make an interior a wall.
- **At the rim.** A gradient, not a strobe, and not a visible fence.
- **After it ends, and after leaving the world.** The weather the player had
  before must be back. This is the check nobody remembers to do, and the
  failure it catches is the one players report.

File the frame with what it was checked against, so the sign-off is citable:

```bash
shamway client capture zone-haze-day --observable "cloud cover and green fog rise with intensity; stock weather restored on exit"
```
