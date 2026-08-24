# Art direction for 7DTD mod assets

How to make a 2D asset that looks like it belongs in 7 Days to Die, and how to
write the prompt that gets it. This page is the style contract; the mechanics
of building and validating are in [agent-workflows.md](agent-workflows.md) and
[game-integration.md](../game-integration.md).

Everything here applies to a coding agent and a human equally. An agent
generating art without it produces the same failure every time: technically
clean, tonally wrong, and obviously not part of the game.

## Quick start

Get the prompt for the asset you are making. It arrives with the key colour,
the negative list, and the commands that consume the model's output:

```bash
shamway prompt item-icon --subject "a squat charcoal welded-steel control box" \
    --stem myModThing
```

Then generate a source at high resolution against the flat key colour it names,
cut it out, reduce it to the atlas cell, and check it:

```bash
shamway generate cutout key assets-src/icons/thing-src.png \
    UIAtlases/ItemIconAtlas/myModThing.png --size 160 --pad 0.9 --trim
shamway check-icons
```

Or photograph the item itself, when the icon should *be* the item. With a
Unity editor, that is the bundle prefab, materials and all:

```bash
shamway render-icon myModThing
```

With no editor, it is the mesh file, rendered by headless Blender:

```bash
shamway generate mesh-icon assets-src/bundle/myModThing.glb \
    UIAtlases/ItemIconAtlas/myModThing.png
```

The two frame the object identically — same yaw, pitch and padding — but the
Blender one is a **clay render**: an interchange file carries no Unity
material, so it reports silhouette, proportion and framing, not the in-game
look. Treat it as the base coat that the rules below are applied to, and as
the honest answer for a mod on the synthesized path, which has no prefab to
photograph.

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
- A smaller tier's icon can be a **derivative of the same source**, drawn
  smaller and greyer so it reads as the same object with less in it:
  `shamway generate icon src.png UIAtlases/ItemIconAtlas/myModSmall.png
  --fill 0.7 --saturation 0.45` is the proven pairing. Record the numbers
  with the source. It is a third lane beside generating and rendering, not a
  substitute for a different *kind* of thing owning different art.
- When generating a sibling, pass the **approved family icons as image
  references** to the model alongside the prompt. It is the cheapest way to
  keep treatment, angle and palette consistent across a family.

That last rule has a trap behind it in XML, not in art: `ItemClassesFromXml`
and `BlocksFromXml` copy every parent property an `Extends` `param1` list does
not name, so *not restating* `Meshfile`, `Model`, `CustomIcon` or `TintColor`
does not stop them being inherited. See
[game-integration.md](../game-integration.md).

## Study the game's own art first

The installed game is read-only evidence, and its icon atlas is the reference
that settles arguments about treatment. Its item icons are **160 × 160** cells
in `Data/Addressables/Standalone/automatic_assets_generic/itemicons.bundle`
(measured on V 3.1.0 b14).

Inside that bundle the cells are grouped into named `icons_mip0_N` textures
(the 160 px figure is the `mip0` measurement); that is the name to look for
when extracting with UnityPy. For *held* scale, the calibration reference is
`Data/Addressables/Standalone/automatic_assets_other/items.bundle`: vanilla's
`GrenadePrefab` and `timedChargePrefab` are identity-transform prefabs whose
mesh children sit at the origin, so "as big as a grenade" is a number you can
read rather than guess.

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

## Producing the source image

This repository ships no image-generation model, and does not pick one for
you; it ships the *contract* the image must meet, and the tools that turn a
candidate into a deployable asset. The source project made every 2D asset
with the image-generation workflow built into the coding agent it was driven
by (its "stylized-concept" use case), and that is the expected path for an
agent: generate with whatever image model the agent session has, using the
prompt pattern below, with the approved family icons passed as image
references when a sibling is being made. A person does the same in any
hosted image model's UI, or locally with Stable Diffusion / ComfyUI / FLUX,
or in Material Maker for tileable PBR sources, or by drawing.

Whatever produces the pixels, the request is the same:

- one subject, at **1024 px or larger**, as PNG — never an upscaled or
  JPEG-compressed candidate, because the cutout works on edge pixels;
- against the **flat key colour** named in the prompt, never "transparent";
- narrow, role-specific candidates (three to five), reviewed at 160 px, one
  selected, the rest deleted;
- the model or tool, the exact prompt, the references, and the selection
  reason recorded in `assets-src/README.md` — the prompt is provenance, not
  acceptance evidence.

Then the pipeline takes over: `shamway generate cutout key` for the cutout,
`--size 160 --pad 0.9 --trim` for the cell, `shamway check-icons` for the
gate, and a look in the inventory for the verdict.

## Writing the prompt

`shamway prompt` assembles the skeleton below for you, filled in for one of
five asset kinds:

```bash
shamway prompt --list
```

Read the rest of this section anyway. The command supplies everything that is
the same for every asset of a kind; what it cannot supply is the part that
decides whether the result is usable — the subject clause, and the specific
wrong answer this subject attracts:

```bash
shamway prompt item-icon --subject "..." --role "..." --avoid "carry handle"
```

A prompt that produces a usable asset has six parts and a long negative list.
The negative list is not padding: generative models default to cinematic
product renders, and every clause below exists because its absence produced a
reject.

```text
Asset type:   7 Days to Die <inventory icon | tileable albedo | particle card>
Create exactly one <subject>, <what it is for in one clause>.
Subject:      <the shapes, materials and components, in order of importance>
Style:        deliberately authored, slightly hand-painted survival-game prop;
              worn industrial materials; simplified forms
Composition:  high-angle three-quarter view, single centred object, generous
              padding, fully contained
Lighting:     dramatic neutral studio lighting; <one mood clause, e.g.
              dangerous industrial>
Palette:      <three to five named colours, e.g. oxidised olive, charcoal,
              dirty steel, muted hazard yellow, one faded red accent>
Readability:  must read clearly at 160 x 160 pixels
Background:   exactly flat #ff00ff
Constraints:  no text, numerals, logos, watermark, UI frame, border, scenery,
              background gradient, ground plane, horizon, shadow, reflection,
              lens flare, cinematic treatment, glossy product-render finish,
              loose wires, carry handle or yoke, extra objects
```

The asset-type line matters because a model asked for "an icon" and a model
asked for "a tileable albedo" must make opposite decisions about perspective;
the lighting line matters because without it the default is a cinematic
rim-lit render, which is the look the whole page is trying to avoid.

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

`shamway prompt` picks the default for the kind and refuses a wrong one: an
opacity mask is forced onto black, because brightness *is* its alpha channel,
and a tileable albedo gets no key line at all because it is never cut out.
Override with `--key green` when the subject contains magenta, pink, or hot
red.

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
    --out-dir assets-src/textures/derived --stem myModPaint \
    --metallic 0.58 --smoothness 0.16 \
    --also tools/shamway/UnityProject/Assets/ModAssets/Bundle/Textures
```

`--metallic` and `--smoothness` are the scalars the flat material shipped
with: the mask is *variation around them*, with its means pinned, so a signed
palette keeps its reflectance while the surface gains relief. `--also`
writes the byte-identical bundle copy from the same run.

### Material profiles for a prop

Most of a hard-surface prop has no albedo at all — it is flat-coloured
primitives — and "finished" needs a definition per surface family or the
result is smooth plastic under the game's lighting. Expressed as required
behaviour, not filenames:

| Profile | Typical parts | Required maps and behaviour |
|---|---|---|
| Painted steel | bodies, housings, drums | authored albedo, a normal **in register** with it, and the packed mask; wear must read where the albedo shows wear — a scratch that changes colour but not reflectance reads as a decal |
| Bare metal | fins, plates, terminals, lids | no albedo; flat colour plus a **tileable detail normal**, mildly anisotropic so it reads as machined stock rather than sand |
| Rubber / tape | feet, straps, binding tape | flat colour plus a coarser, isotropic detail normal; matte, and visibly not the same surface as the metal beside it |
| Emissive lamp | an armed indicator | smooth and map-free — a lens whose only job is to be unambiguously lit or unlit; `GeneratedAsset.EmissiveMaterial` |

The detail normals come from seeded noise, periodic by construction so a
cylinder's wrap-around UVs never show a seam:

```bash
shamway generate texture-maps detail --out-dir assets-src/textures/derived \
    --stem myModSteel --size 512 --seed 7 --anisotropy 2.6 --grit 0.35 --slope 0.28
shamway generate texture-maps detail --out-dir assets-src/textures/derived \
    --stem myModRubber --size 256 --seed 7 --exponent -1.5 --slope 0.42
```

Apply them with `GeneratedAsset.Tile(material, u, v)` at a repeat chosen from
the part's real size. Masks are capped at 512 px and normals at 1024 px on
import for a reason: mask channels are blurred fields, so extra resolution
stores noise, and two 1024 px paint normals took the source bundle from 1.6
MB to 5.2 MB.

The human sign-off for this pass: fine relief and uneven gloss on paint;
seams and scuffs where the albedo shows them; bare steel brushed, not
mirrored; rubber matte; and nothing anywhere that looks like wet plastic.

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

The flash and the ring are keyed like any other image. Their negative lists
name the failures those subjects attract, which is the whole technique:

> Create exactly one isolated, compact near-spherical white-hot flash/fireball
> sprite for an additive particle material. The centre is nearly white with a
> pale yellow rim and a restrained orange edge; use chunky, camera-facing,
> slightly hand-painted game-particle forms. Use a perfectly flat solid
> `#ff00ff` chroma-key background, with no ground plane, gradients, shadow,
> reflection, lens flare, smoke column, dust ring, terrain, debris, UI, text,
> logo, watermark, or cinematic background.

> Create exactly one isolated, top-down circular shock-ring sprite: a broken,
> thin, expanding ring of pale yellow-white heat and dusty orange at the
> outer edge, with an empty centre. It must read as a restrained
> ground-hugging effect rather than a portal, magic spell, sci-fi HUD, or
> target marker. Use a perfectly flat solid `#ff00ff` chroma-key background,
> with no ground plane, gradients, shadow, reflection, fireball, smoke
> column, terrain, debris, UI, text, logo, watermark, or cinematic background.

Then convert brightness to alpha and make the colour white, so the particle
system's own colour-over-lifetime tints it:

```bash
shamway generate cutout luma assets-src/vfx/smoke-mask.png \
    assets-src/vfx/smoke-card.png --black-point 15
```

The black point is what removes a generator's faint background haze without
hardening the puff edges. A card that keeps that haze shows up in game as a
grey rectangle around every particle.

**Look at whether the file already has an alpha channel first.** Image models
often return one, and that alpha is usually *not* the picture's brightness — a
measured source peaked at alpha 251 where its luma peaked at 135. Running
`luma` on such a file recomputes alpha from brightness and caps the card near
half opacity, which nothing downstream flags. Keep the alpha instead:

```bash
shamway generate cutout alpha assets-src/vfx/haze-src.png \
    assets-src/vfx/haze-card.png --size 512 --pad 1.0
```

`cutout alpha` refuses a source with no alpha channel and names `luma` in the
error, so this is a question you can answer by running it rather than by
inspecting the file. For cards that are pure falloff — rain, ash, a broad haze
puff — skip the model entirely and draw them:
[environment-effects.md](environment-effects.md) owns that lane and
`shamway generate particle-card` draws both shapes.

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
50` are **percentages** of the RGB distance range, so they hold whatever key
colour was used. (A mod-local script that records `12 / 220` is on a 0–255
scale; the two are not interchangeable.) Widen the gap for a soft-edged
subject, narrow it for a hard-edged one, and record whichever you used.

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

- `shamway render-icon myModThing` — UIAtlases/ItemIconAtlas/myModThing.png

```bash
shamway render-icon myModThing
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

## Props from primitives

The procedural mesh lane (`GeneratedAsset.Primitive`) produces a reviewable
diff of numbers, and its first output is always eleven bare shapes that read
as nothing. The rebuild that made one read as an improvised device went to
about forty primitives, and every lesson generalises:

- **Rolled hoops and a chime at each end** are most of what makes a cylinder
  read as a *drum* at icon scale.
- **Cap every pipe.** An open-ended pipe is a tube, not a charge.
- **Offset repeated parts so a gap, not a part, faces the front** — the
  first build put a pipe squarely in front of the placard.
- **Parts must extend past the body's silhouette**, or they vanish at 160 px
  behind whatever wraps the body.
- **Model a wrap as straight runs, never as a thin wide cylinder.** A
  thin cylinder is a solid disc; two of them turned the whole item into a
  stack of black plates. This was the single biggest fix.
- **Break rotational symmetry once** — a taped-on box, a stub antenna, a
  wire run. It is the part that says somebody built this.
- **Symbols and decals go on a textured quad**, not on geometry. A trefoil as
  three rotated cubes reads as three smudges; the real symbol needs curved
  blades (ISO proportions: a central disc of radius R, three 60° blades from
  1.5R to 5R, on a worn border), and a 256 px card on one quad costs far less
  than curved geometry. Draw it at 4× with Pillow and LANCZOS-downsample.
- **Re-tune colour for linear space.** Tape at 0.2 albedo was mid-grey
  plastic strapping on screen; 0.07 reads as tape. A dark, highly metallic
  colour has almost no diffuse response left and renders brown — lower the
  metallic before brightening the colour.
- **Do not hand-draw the icon of a modelled item.** The source project's one
  Pillow-drawn icon sat next to photoreal renders, matched neither them nor
  its own mesh, and was replaced by `render-icon`.

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
