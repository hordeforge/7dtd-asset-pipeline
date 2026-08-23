# Art direction for 7DTD mod assets

How to make a 2D asset that looks like it belongs in 7 Days to Die, and how to
write the prompt that gets it. This page is the style contract; the mechanics
of building and validating are in [agent-workflows.md](agent-workflows.md) and
[game-integration.md](game-integration.md).

Everything here applies to a coding agent and a human equally. An agent
generating art without it produces the same failure every time: technically
clean, tonally wrong, and obviously not part of the game.

## Quick start

Generate a source at high resolution against a flat key colour, cut it out,
reduce it to the atlas cell, and check it:

```bash
shamway generate cutout key assets-src/icons/thing-src.png \
    UIAtlases/ItemIconAtlas/myModThing.png --size 160 --pad 0.9 --trim
shamway check-icons
```

Or render the item's own prefab, when the icon should *be* the item:

```bash
shamway render-icon myModThing
```

Then look at it at 160 px, in the game, in a backpack next to vanilla items.
Everything below is detail.

## The house style

7DTD's own item art is a specific, consistent treatment, and matching it is
most of what makes a mod asset look native rather than bolted on. Read the
game's own icons before authoring — see "Study the game's own art" below — but
the treatment reduces to five rules.

**Readability first.** One decisive silhouette, one clear focal point, and
restrained detail that still reads at inventory scale or at normal in-world
distance. An icon is looked at for a fraction of a second in a grid of other
icons. If a player has to study it, it has failed regardless of how good the
full-resolution render is.

**Functional construction.** Every visible component should support what the
object does in game. A device with one obvious power input reads as a thing you
wire; the same device covered in unexplained pipes, ornamental greebles,
duplicated warning markings and a large carrying yoke reads as a household
thermos. That specific mistake — a carry handle turning ordnance into a flask —
cost the source project a full regeneration, because a handle is a strong
silhouette cue and it says "kitchenware".

**Cohesive survival-game look.** Hand-painted, worn industrial materials;
slightly simplified forms; oxidised olive, charcoal, dirty steel, muted hazard
yellow, sparing faded red. The result must not look like a glossy product
render, a photoreal military catalogue photograph, or generic high-detail
generative hard-surface art. "Deliberately authored" is the target, and it is
worth saying so in the prompt in exactly those words.

**Composition discipline.** No cinematic background, lens effects, dramatic
smoke, gratuitous cables, cropped components, tiny unreadable labels, UI
frames, watermarks, or invented branding. A high-angle three-quarter view is
the default because that is what the game uses, but use it because it serves
the asset, not reflexively.

**Iteration discipline.** Generate narrow, role-specific candidates. Inspect
them *at their intended scale*, not at full resolution. Keep only the selected
source after review and delete the rest, so the next person cannot mistake a
rejected concept for the shipped one.

### Reading a family of items

When a mod ships several related items, the family *is* the message, and it is
a design decision that has to be made deliberately:

- Variants of one thing — sizes, tiers, yields — should be the same object at
  different scales and paints, so a player reads "same weapon, more power".
- A different *kind* of thing must be a different shape entirely, so it can
  never be mistaken for the family it sits beside.
- Every variant owes its **own** assets: its icon, its held mesh, and its
  placed model. A tier that inherits another tier's art is a bug, not a
  shortcut — a player who cannot tell a small charge from a large one at a
  glance will eventually use the wrong one.

That last rule has a trap behind it in XML, not in art: `ItemClassesFromXml`
and `BlocksFromXml` copy every parent property an `Extends` `param1` list does
not name, so *not restating* `Meshfile`, `Model`, `CustomIcon` or `TintColor`
does not stop them being inherited. See
[game-integration.md](game-integration.md).

## Study the game's own art first

The installed game is read-only evidence, and its icon atlas is the reference
that settles arguments about treatment. Its item icons are **160 × 160** cells
in `Data/Addressables/Standalone/automatic_assets_generic/itemicons.bundle`
(measured on V 3.1.0 b14).

Inspect a few icons close to your subject — a thrown explosive for a thrown
explosive, an electrical device for an electrical device — and note the
treatment they share: isolated, high-angle, tightly framed props; weathered
material-specific rendering; high readability at cell size; practical detail
only where it communicates function.

Two rules about doing this:

- **Never copy vanilla image data into a mod repository.** Extract to a
  temporary directory, look, and delete. The reference establishes treatment,
  not pixels.
- **Never write to the game install.** It is evidence.

`shamway inspect --deep` reads a bundle's objects when UnityPy is
installed; for extracting the images themselves, UnityPy is the scriptable
option and AssetStudio or UABE are the interactive ones. Pin whichever you use
— all three track Unity's serialization format and break across versions.

## Writing the prompt

A prompt that produces a usable asset has six parts and a long negative list.
The negative list is not padding: generative models default to cinematic
product renders, and every clause below exists because its absence produced a
reject.

```text
Create exactly one <subject>, <what it is for in one clause>.
Subject:      <the shapes, materials and components, in order of importance>
Style:        deliberately authored, slightly hand-painted survival-game prop;
              worn industrial materials; simplified forms
Composition:  high-angle three-quarter view, single centred object, generous
              padding, fully contained
Palette:      <three to five named colours, e.g. oxidised olive, charcoal,
              dirty steel, muted hazard yellow, one faded red accent>
Readability:  must read clearly at 160 x 160 pixels
Background:   exactly flat #ff00ff
Constraints:  no text, numerals, logos, watermark, UI frame, border, scenery,
              background gradient, ground plane, horizon, shadow, reflection,
              lens flare, cinematic treatment, glossy product-render finish,
              loose wires, carry handle or yoke, extra objects
```

Notes that matter more than they look:

- **"exactly one"** and **"fully contained"** stop the model composing a scene
  or cropping the subject at the frame edge.
- **Name the failure you expect.** If the last candidate grew a carry handle,
  the next prompt says "no carry handle, arch, bail handle, or strap". Generic
  negatives do not remove a specific recurring artefact.
- **Ask for the key colour explicitly and flatly** — "exactly flat `#ff00ff`",
  not "transparent background". Models produce a checkerboard pattern or a
  soft vignette when asked for transparency, and neither can be keyed out.
- **Edit rather than regenerate** when one element is wrong and the rest is
  right. An edit prompt names what to remove, what to put in its place, and
  everything to preserve — including the key colour, or the edit will silently
  change it.

### Choosing the key colour

| Key | Use when |
|---|---|
| `#ff00ff` magenta | the default: olive, steel, charcoal, earth, yellow subjects |
| `#00ff00` green | the subject contains magenta, pink, or hot red |
| `#000000` black | **only** for a grayscale opacity mask (see particle cards) |

The key must be a colour the subject cannot contain, because the cutout works
by colour distance. A magenta key behind a magenta warning light removes the
light.

### Worked example: an item icon

> Create exactly one compact, ground-placeable field control box that reads
> immediately as a rugged wired electrical trigger, clearly separate from any
> payload: a squat charcoal-painted welded-steel enclosure on four short
> rubberised feet. Its angled front has exactly three large controls — a
> guarded muted-red arming toggle, a chunky dial with unmarked ticks, and a
> two-position rotary selector. Put two empty recessed cable terminals on one
> side. Use scratched powder coat, oxidised steel, dirty rubber, and one small
> faded electrical-hazard triangle, against an exactly flat `#ff00ff` key. No
> radiation symbol, labels, numbers, screen, keypad, antenna, loose wires,
> suitcase shape, UI, scenery, or frame.

What makes it work: the role is stated first, the control count is exact
("exactly three"), the materials are named, and the negative list names the
specific wrong answers this subject attracts (a screen, a keypad, a briefcase).

### Worked example: a tileable material albedo

An albedo source is not a picture of an object. Say so, or the model renders
the object.

> Create one square, flat, tileable PBR albedo reference texture for battered
> olive-drab painted steel. Include restrained irregular chipping that exposes
> dark oxidised steel, faint rubbed grime, sparse tan dust, and one small
> weathered hazard-warning decal fragment. It must stay readable on a
> compact ground-placed prop at normal game distance. Perfectly flat
> orthographic 2D material sheet; no object silhouette, floor, horizon, baked
> directional lighting, text, numerals, logos, UI, watermark, shadows,
> highlights, reflections, perspective, or rendered object.

Derive the normal and packed mask from that albedo rather than generating them
— derived maps stay in register with the albedo for free, and a hand-authored
normal has to be redrawn every time the albedo changes:

```bash
shamway generate texture-maps assets-src/textures/paint.png \
    --out-dir tools/shamway/UnityProject/Assets/ModAssets/Bundle/Textures \
    --stem myModPaint --metallic 0.58 --smoothness 0.16
```

### Worked example: a particle card

Flash, fire, and ring cards are generated against a flat key like any other
image. Smoke is the exception: generate it as a **grayscale mask on pure
black**, because a chroma key cannot survive soft smoke edges.

> Create exactly one isolated, irregular, broad smoke-puff cluster suitable as
> a camera-facing particle card. Use a deliberately chunky, slightly
> hand-painted survival-game texture: dense soft centre, varied rounded puffs,
> naturally broken lower edge, a few sparse wisps. This is an opacity mask, not
> a scene. Use a perfectly flat pure-black `#000000` background; the cluster
> ranges from soft mid-grey to white, and black is reserved for empty
> background. No colour, landscape, sky, ground plane, fire, embers, debris,
> text, UI, watermark, shadow, reflection, frame, gradient, or cinematic
> rendering.

Then convert brightness to alpha and make the colour white, so the particle
system's own colour-over-lifetime tints it:

```bash
shamway generate cutout luma assets-src/vfx/smoke-mask.png \
    assets-src/vfx/smoke-card.png --black-point 15
```

The black point is what removes a generator's faint background haze without
hardening the puff edges. A card that keeps that haze shows up in game as a
grey rectangle around every particle.

## Cutting the background out

A hard threshold produces a coloured fringe on every soft edge, and a fringe is
precisely what makes an icon look pasted on. `shamway generate cutout key` keeps partial
alpha through the transition band and pulls the residual key tint out of it:

```bash
shamway generate cutout key assets-src/icons/thing-src.png \
    assets-src/icons/thing.png
```

Keep both files. The keyed original is the record of what was generated; the
RGBA result is the working source. Neither is deployable — the deployable file
is the atlas derivative below.

Defaults worth knowing: `--transparent-threshold 12` and `--opaque-threshold
50` are percentages of the RGB distance range, so they hold whatever key colour
was used. Widen the gap for a soft-edged subject, narrow it for a hard-edged
one, and record whichever you used.

## Making the deployable atlas cell

Atlas icons are **not** bundle assets. They are PNGs under
`UIAtlases/<AtlasName>/`, packed at runtime, keyed by filename stem —
`ItemIconAtlas` is the one the game already registers. The cell is 160 × 160.

```bash
shamway generate cutout key assets-src/icons/thing.png \
    UIAtlases/ItemIconAtlas/myModThing.png --size 160 --pad 0.9 --trim
```

`--trim` crops to the subject before scaling, so the item fills the cell rather
than floating in whatever margin the generator left; `--pad 0.9` then puts a
deliberate margin back. `shamway generate icon` does the same job from an
already-transparent source and can emit a legibility contact sheet.

Then reconcile every icon against every `CustomIcon` key in the mod's XML:

```bash
shamway check-icons
```

That catches the atlas failures that are silent in game: a cell that is not
square or not the right size, a PNG with no alpha, an empty render, and a
`CustomIcon` whose case does not match its filename. A key this mod does not
provide is *reported, not failed* — referencing a vanilla key is normal.

## The two ways an icon gets made

Both are first-class. Pick by what the icon should show.

| Lane | Use it when | Why |
|---|---|---|
| **Generated or drawn art** | the icon should show something the mesh does not: a weathered studio render, an object the primitive geometry cannot express | no mesh has to exist first, and the art can be better than the model |
| **Rendered from the prefab** — `shamway render-icon` | the icon should *be* the item | it cannot drift: regenerating the mesh regenerates the icon |

The second lane exists because of a specific failure worth remembering: an item
whose icon was a flat drawing of a green pipe bomb while its actual mesh was a
drum-and-charges assembly. Both were "finished", and they disagreed. A rendered
icon makes that impossible.

```bash
shamway render-icon myModThing                     # UIAtlases/ItemIconAtlas/myModThing.png
shamway render-icon myModThing --yaw 150 --pitch 20 --padding 1.1
```

Two things about it, both of which cost a render to learn:

- **It needs a graphics device.** Run under `xvfb-run -a` on a headless host.
  The pipeline never passes `-nographics` here, because with that flag Unity
  runs the script happily, draws nothing, and writes a uniform transparent
  square that looks like a framing bug.
- **The yaw default is past 180° on purpose.** The camera looks along its own
  forward vector, so a yaw near zero photographs the *back* of an item whose
  front detail faces +Z.

The renderer lights the subject with three directional lights and a bright
trilight ambient, because item materials are usually dark — steel, tape, rubber
— and lit like a scene at dusk they render as a silhouette. Exposure is a real
decision: halve those values and dark materials crush to black, double them and
the same materials wash out to pale grey. The project renders in **linear
space**, so a 0.2 albedo is already mid-grey on screen before any light touches
it. Colour values that look right as numbers are routinely wrong on screen.

## Review at the size it ships

The single most common review mistake is judging a 1254 px source. Judge the
160 px derivative, and judge it where it appears:

1. **At native scale**, next to the vanilla icons it will sit beside. A contact
   sheet at 1×, 2× and 4× makes the difference between "detailed" and "noisy"
   obvious.
2. **On a light and a dark background.** An alpha fringe is invisible against
   one of them.
3. **In the actual client** — in the backpack, in the toolbelt, in the recipe
   and perk windows. `check-icons` proves the file is a valid cell; it cannot
   prove the art reads.

A missing icon does not draw a blank: the atlas returns whatever else answers
to that key, which is why an icon bug can look like a deliberate choice. Only
a look in the inventory closes it.

## What is deliberately not here

- **Custom shaders.** Prove the effect with stock materials first. The source
  project's entire VFX and world-material work — per-texel metallic,
  smoothness, occlusion, surface relief, additive and alpha-blended particles —
  needed no custom shader, only the correct keywords and import types.
- **LOD groups on unreviewed geometry.** Anything a review may reshape is
  wasted LOD work. Derived material maps are the exception: they are keyed to
  the albedo's UV space, so a shape change does not invalidate them.
- **Art quality guarantees.** This pipeline validates format, resolution,
  addressability, and state. Whether the asset is good is a human judgement,
  every time.
