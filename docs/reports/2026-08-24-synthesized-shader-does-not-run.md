# Report — a synthesized prop places in 7DTD and renders nothing

## TL;DR

- **SOLVED.** A synthesized prop now draws. `verify-bundle --draw` reports
  `VERIFY-DRAWN: shamwayselftestprop covered=38.8% zoomed-out=2.4%`, with
  `_MainTex` bound and the control cube healthy in the same frame.
- **Root cause: one string.** Every field of a pass's render state is a
  `SerializedShaderFloatValue`, which carries a constant in `val` **or** the
  name of a material property in `name`. Unity writes the sentinel
  `<noninit>` when there is no property. This writer wrote `""`.
  The empty string is **not** that sentinel - it is a property whose name is
  empty. The runtime looks it up, finds nothing, and takes **0**.
- **Which made `colMask` 0**: the pass wrote no colour channels at all. The
  geometry rasterized and nothing reached the framebuffer.
- **Why every symptom looked healthy**: the shader loaded, `Shader.isSupported`
  was `True`, `Material.SetPass(0)` returned `True`, and Unity never fell back,
  because nothing about the shader had *failed*. It was told to write no
  colour.
- **Two earlier bugs, also real, also fixed** (they are what made the shader
  *load*; they were never going to make it draw): the GLCore code record was
  eight bytes short of the format, and the fragment half used
  `layout(location = ...)` under `#version 150` without
  `#extension GL_ARB_explicit_attrib_location`.
- **Still owed**: a human look. The prop draws; nobody has yet seen whether it
  looks *right*. And **d3d11 is still unmeasured** - everything here is
  OpenGLCore, and d3d11 is what the game runs through Proton.

## How it was found

By mutating a stock shader **that draws in this writer's own bundle**
(`Game/EntityTintMaskSSS`) toward this writer's shader one block at a time, and
measuring the frame each step - the technique the earlier sections argued for,
finally applied with a baseline known to render:

| Mutation of the stock shader | Draws? |
|---|---|
| reduced to a single pass | **yes**, 38.8% |
| ... plus **this writer's whole `m_State`** | **no**, 0.0% |
| ... `m_State` but keeping stock's `rtBlend0` alone | **yes**, 38.8% |
| ... `m_State` but keeping stock's `gpuProgramID` / `culling` / `m_Tags` / `zTest` | no |

`rtBlend0` alone brought it back. Inside `rtBlend0`, **every `val` already
matched stock** - `srcBlend` 1, `destBlend` 0, `colMask` 15. The only
difference in the entire block was `name`: `""` against `"<noninit>"`.

```text
field         ours                      stock
colMask       {'val': 15.0, 'name': ''} {'val': 15.0, 'name': '<noninit>'}
```

`NO_PROPERTY` now names that sentinel in `bundle_writer.py`, and
`RenderStateSentinelTests` fails if any render-state value ever carries an
empty name again.

## The road there (kept: the eliminations still hold)


Mutating a *stock* shader object toward this one, one field at a time, keeping
the record indices consistent — the shape the previous entry in this report
argued for, after the blob/parsed-form swap turned out to be invalid.

| Mutation of the stock object | Result |
|---|---|
| its records re-tiled by this writer's `assemble_blob` + `compress_lz4` | `isSupported=True` — the blob assembler is clean |
| all 19 parameter records replaced with this writer's `ParameterBlob.to_bytes()` | `isSupported=True` — the parameter blob is clean |
| the 8 GLCore **code** records replaced with this writer's | **`isSupported=False`** — the fault is in the code record |

That last row is what narrowed it to `source_blob()`. Decoding all twelve stock
type-6 records then showed a trailing region this writer never wrote, and
running the GLSL through `glslangValidator` — a compiler that reports errors,
unlike the runtime — showed the missing extension.

**One probe here was confounded and is recorded as such**: substituting this
writer's GLSL into a stock record's framing also fails, but that pair is
inconsistent by construction — the stock parameter blob beside it names stock's
uniforms, not ours. It isolates nothing, and no conclusion was drawn from it.
The GLSL fix rests on `glslangValidator` alone, which needs no Unity at all.

## Eliminated after the record fix, so these negatives count

Every row below was measured against the **fixed** writer, with the control
cube reading a healthy `38.8% / 2.4%` in the same frame and the GLSL verified
to compile before the run. None of them changed `0.0%`.

| Tried | Why it was a candidate |
|---|---|
| `$Globals` of individual uniform members instead of the d3d11 cbuffers | stock GLCore uses that shape |
| one shared source record, both stages at the same index | stock's shape, `stageCounts=1` |
| a vertex stage reading **no** inputs and no uniforms | would prove or kill the transform hypothesis |
| a fragment writing **constant opaque red** | would prove or kill alpha-zero from an unbound sampler |
| **GLCore-only** shader, the d3d11 platform dropped entirely | would catch cross-platform blob-index confusion |
| `m_ShaderRequirements` `0` → `1` | ours was `0`; no stock shader sampled has `0` (min seen: `1`) |
| a real keyword vocabulary plus `m_SerializedKeywordStateMask` | the recurring error names keyword state, and ours declared none |
| `m_NameIndices` populated | ours was `[]`, stock's is `[('$Globals', 1), ('_Cutoff', 2), ('_MainTex', 0)]` |

`Incompatible keyword states` still appears in **every** run, including with a
full keyword vocabulary and a consistent state mask. It is not a description of
the cause; treat it as noise until something else explains it.

### What matches stock exactly

Checked field by field rather than assumed, against
`Legacy Shaders/Transparent/Cutout/VertexLit` read out of the installed game:

- **every scalar on the pass** — `m_ProgramMask` 6, `m_Type` 0, `m_UseName`,
  `m_Name`, `m_TextureName`, both instancing flags, and the subshader's
  `m_LOD` 100;
- **`m_CommonParameters`** — empty in ours *and* in all eight stock shaders
  sampled, so its emptiness is correct, not a gap;
- **the tier slot** — stock puts its player sub-programs in `tier[3]`, as this
  writer does.

### The sub-program indexing is correct, and here is the artifact that says so

Worth recording because it looked like the most likely fault and is not. In
stock's `tier[3]`, the d3d11 entries come first and the GLCore entries follow,
and **`sp[0]` (`type=15`, d3d11) and `sp[6]` (`type=6`, GLCore) both carry
`m_BlobIndex: 6`**:

```text
sp[0] blob=  6 type=15 kwIdx=[]
sp[6] blob=  6 type= 6 kwIdx=[]
```

So `m_BlobIndex` is an index **into that platform's own blob**, and two
platforms sharing an index is normal. This writer sharing index 2 across d3d11
and GLCore is right, and the GLCore-only build confirmed it from the other
direction.

`m_SerializedKeywordStateMask` was decoded from the same artifact: it lists the
**keyword indices that participate in variant selection**, and a sub-program's
`m_KeywordIndices` names the subset it is compiled for, with `[]` being the
base variant.

## CORRECTION — the section below is wrong, and here is the measurement that breaks it

**Retracted on 2026-08-24, the same day it was published in #66 and #67.** The
claim was that a `Shader` loaded from a bundle this writer produces never
renders whatever its content. It is false.

The claim rested on one transplant: stock
`Legacy Shaders/Transparent/Cutout/VertexLit`, written into this writer's
bundle, loading correctly and drawing nothing. What that transplant never
checked is whether **that particular shader** draws on a bare cube at all. It is
an alpha-tested cutout shader with its own `_Cutoff` and property
expectations, and this writer's material does not carry them - so its zero has
an explanation that has nothing to do with serialization.

Redone with a shader **measured rendering in this same harness** -
`Game/EntityTintMaskSSS`, the shader behind `Azalea_TintSSS`, which covered
43.2% of the frame when loaded from the game's own bundle - transplanted into
this writer's bundle instead:

```text
VERIFY-SHADER: 'Shamway/Unlit' isSupported=True passes=4 renderQueue=2450 properties=17 device=OpenGLCore
VERIFY-DRAWN-MATERIAL: built-in cube wearing 'shamwaySelfTestProp_mat' covered=38.8%
VERIFY-DRAWNOW:        direct SetPass+DrawMeshNow covered=25.0%
VERIFY-DRAWN-CONTROL:  built-in cube covered=38.8% zoomed-out=2.4%
```

**It draws.** Four passes, render queue 2450, seventeen properties - the real
transplanted shader, not a substituted error shader, which reports
`isSupported=False` and was seen doing exactly that earlier today.

That `38.8%` matches the control is expected here rather than suspicious: it is
the same cube at the same zoom, so any opaque shader covers the same fraction.
The independent number is `DRAWNOW`'s 25.0%, which no error shader produced in
any run.

### Eliminated against the corrected baseline

With the container cleared, everything below was measured on **this writer's own
shader**, each with the control cube healthy in the same frame and the GLSL
verified to compile first. None moved it off `0.0%`.

| Tried | Why it was a candidate |
|---|---|
| `m_PreloadTable` populated, every container entry spanning it | ours was empty; the game's has 5144 entries with per-asset slices |
| `m_ShaderIsBaked` `False` → `True` | ours is `False`, every stock shader sampled is `True` |
| `m_State.m_Name` `"Shamway/Unlit"` → `"FORWARD"` | **this is how `LightMode` is carried** - stock's pass tags are empty and its state name is `FORWARD` / `ShadowCaster`, while ours held the shader's own name |
| **empty parameter blobs** for both GLCore stages | removes every uniform, texture and cbuffer binding from the question |
| a **trivial parameter-free program** - `gl_VertexID` triangle, constant opaque fragment - on top of those empty blobs | this program cannot produce zero pixels if it executes |

That last row is the important one. A shader with **no parameters, no uniforms,
no texture, no vertex inputs**, whose fragment writes opaque red
unconditionally, still draws nothing - in a bundle that renders a stock shader
in the same slot, through the same material, in the same frame.

So the fault is not in any binding, any parameter, any pass-state field or any
GLSL this writer emits. It is in the **structure** of the `Shader` object
itself, and it is something none of the field comparisons in this report has
caught - because the parsed form matches stock field for field.

### The differences that remain, against a shader known to render

Compared against `Game/EntityTintMaskSSS`, which renders from this writer's own
bundle:

| Field | ours | stock |
|---|---|---|
| `m_FallbackName` | *(empty)* | `Diffuse` |
| `m_Dependencies` (shader level) | `0` | `2` |
| `m_KeywordNames` / `m_KeywordFlags` | `0` | `27` |
| `m_ShaderIsBaked` | `False` | `True` (**tested, not the cause**) |
| subshader `m_Tags` | `RenderType=Opaque` | `QUEUE=AlphaTest+0`, `RenderType=Transparent` |
| subshader `m_LOD` | `100` | `0` |
| passes | `1` | `4` |
| platforms | `2` | `3` |

`m_FallbackName` was then **tested too**: setting it to `Diffuse` changed
nothing, and the run still reports `passes=1`. That number is itself a finding -
**Unity did not fall back**, so it does not consider this shader failed. It
believes the shader is fine, selects its single pass, and draws nothing.

The shader-level `m_Dependencies` is the only field in that table still
untested.

### What this actually establishes

| | draws? |
|---|---|
| our bundle + our material + **stock** shader (`EntityTintMaskSSS`) | **yes**, 38.8% |
| our bundle + our material + **our** shader | no, 0.0% |
| our material + a built-in shader (`Unlit/Color`) | yes, 38.8% |

So the **container is cleared**: this writer's UnityFS bundle, its
SerializedFile, its class-142 wiring and its `Shader` serialization all carry a
stock shader that then renders. The fault is back where the earlier sections put
it - in **the `Shader` object this writer constructs**, that is, in its content.

Two supporting facts, both measured while chasing the wrong conclusion, and
both still true and still useful:

- the embedded **class-48 type tree is identical** to the game bundle's, node
  for node, 2324 nodes each;
- a transplanted stock shader serializes to **byte-identical** object data -
  the only difference is the name string that was deliberately renamed
  (`0x0d` "Shamway/…" against `0x2b` "Legacy S…"), which accounts for the whole
  28-byte length delta.

Those two are why the container was suspected, and they are exactly why it can
now be cleared rather than merely doubted.

### One real deviation found on the way, measured, and *not* the cause

This writer wrote an **empty `m_PreloadTable`**, with every container entry at
`preloadIndex=0, preloadSize=0`. The game's bundle has 5144 preload entries, and
its material declares `preloadIndex=2865 preloadSize=7`. `m_PreloadTable` is
what the runtime loads *alongside* an asset, so an empty one looked like a
precise explanation for a shader that resolves by `PPtr` and never gets its
sub-programs.

**It was implemented and measured: still `0.0%`.** The change was reverted
rather than kept for looking right, and the deviation is recorded here so the
next session neither re-discovers it as a lead nor assumes it is harmless in the
live client, which has not been tested.

### The mistake, named

This is the same failure this repository's `AGENTS.md` warns about, committed by
the session that had just quoted it: a **negative observation over-generalized**.
"This one stock shader did not draw" became "no shader this writer serializes
can draw", and it was written into a report and two merged pull requests
before the obvious control - use a shader already known to draw - had been run.

The cost was two pull requests of wrong framing. The fix is the same as it was
for the shader claim in August: a negative result names the *specific* route
measured, and a transplant is only evidence if the transplanted thing is known
to work at the destination's baseline.

## Superseded: the fault is the Shader object this writer serializes

This supersedes the sections below it. They are kept because their eliminations
still hold, but the target has moved off the shader *source* entirely.

Four measurements, each with its own control in the same frame:

```text
VERIFY-DRAWN-BUILTIN-MAT: built-in cube wearing a fresh Unlit/Texture material covered=38.8%
VERIFY-DRAWN-SWAPPED:     the bundle's material wearing Unlit/Color covered=38.8%
VERIFY-DRAWN-MATERIAL:    built-in cube wearing 'shamwaySelfTestProp_mat' covered=0.0%
VERIFY-DRAWN-CONTROL:     built-in cube covered=38.8% zoomed-out=2.4%
```

- `BUILTIN-MAT` **validates the probe**: a material Unity built itself, on the
  same cube, through the same path, reads 38.8%. So a zero from this path is a
  real zero. It was added *before* any conclusion was drawn from one.
- `SWAPPED` **clears the `Material`**: the bundle's own material, with
  `Unlit/Color` assigned onto it, draws. Its properties, its texture binding and
  its render queue are all fine.

Then the two that settle it.

**A stock shader, serialized by this writer, does not draw.** `Legacy
Shaders/Transparent/Cutout/VertexLit` was taken whole out of the installed game
and written into this writer's bundle in place of ours:

```text
VERIFY-SHADER: 'Shamway/Unlit' isSupported=True passes=3 renderQueue=2450 properties=6 device=OpenGLCore
VERIFY-DRAWN-MATERIAL: built-in cube wearing 'shamwaySelfTestProp_mat' covered=0.0%
```

Three passes, render queue 2450, six properties - unmistakably the stock
shader, loading correctly, drawing nothing.

**A shader loaded from the game's own bundle does draw.** The control that
proves the harness is not the problem. `Data/Bundles/Standalone` is a
*directory*, which is why an earlier attempt was refused by
`bundle.is_file()`; the bundle is the 650 MB file
`Standalone/Entities/trees`, read straight out of the install:

```text
VERIFY-DRAWN-MATERIAL: built-in cube wearing 'Azalea_TintSSS' covered=43.2%
VERIFY-DRAWNOW:        direct SetPass+DrawMeshNow covered=14.0%
VERIFY-DRAWN:          azalea.spm covered=14.7% zoomed-out=0.3%
VERIFY-DRAWN-CONTROL:  built-in cube covered=57.1% zoomed-out=3.6%
```

A bundle-loaded shader renders - on the cube, through the renderer, and through
a hand-issued `SetPass` + `DrawMeshNow` - and that bundle's prefab draws its own
geometry, with coverage falling as the camera pulls back the way a real object's
does.

Putting the two together:

> Bundle-loaded shaders render. This writer's `Shader` object does not, and
> neither does a **stock** shader's content once this writer has serialized it.
> The fault is in the serialization of the `Shader` object - not in the GLSL,
> not in the `Material`, not in the mesh, and not in the harness.

The two bugs fixed earlier today were real, and are what made the shader
**load**. They were never going to make it **draw**: the same failure survives
content this writer did not author.

### Caveats, stated rather than omitted

- Not every material in the game bundle draws: the first sampled, `Billboard`,
  read `0.0%`. Billboard shaders need per-instance setup a bare cube does not
  give them, so that zero is expected and is evidence of nothing.
- Still OpenGLCore only. **d3d11 remains unmeasured**, and it is what the game
  actually runs.
- The `Shader` object's *parsed form* matches stock field for field (see below),
  so whatever is wrong is not a field this report has compared.

### A probe rule this cost

`verify-bundle` writes its log to a fixed path, so a **failed run leaves the
previous run's log in place** and every grep against it still succeeds. Numbers
were read off exactly such a stale log once during this work and had to be
discarded. Check the log's timestamp or the command's exit status before reading
it, and prefer a control in the *same* frame over a comparison across runs.

### Still untested

- the GLSL **preamble**: stock carries `HLSLCC_ENABLE_UNIFORM_BUFFERS`,
  `UNITY_LOCATION`/`UNITY_BINDING` and a `GL_ARB_shader_bit_encoding` guard that
  this writer's source does not;
- `m_EditorDataHash`, empty here and populated in stock - probably editor-only,
  but that is a guess and is written down as one;
- **d3d11**, which nothing in this report has measured.

## The program loads, and is never executed

The sharpest statement this investigation has reached, from one asymmetry:

| The GLSL this writer emits | Coverage |
|---|---|
| **deliberately broken** (a syntax error injected into the vertex half) | **38.8%** — Unity substitutes its magenta error shader, which draws |
| **valid** (compiles under `glslangValidator`) | **0.0%** |

A shader that fails to compile draws. The one that compiles does not. So the
draw path, the camera, the mesh and the material are all working, and the
fallback proves it in the same frame — what does nothing is *our program*,
after it loads successfully.

That is not a fallback and not a rasterization failure downstream. Unity
reports `isSupported=True` and `SetPass(0)=True`, and then the program runs as
a no-op.

The strongest form of the test: a vertex stage that reads **no** inputs and no
uniforms, emitting a large triangle from `gl_VertexID`, with a fragment stage
writing **constant opaque red**. Both halves verified to compile before the
run. It cannot produce zero pixels if it executes at all:

```text
VERIFY-DRAWNOW: direct SetPass+DrawMeshNow covered=0.0%
VERIFY-DRAWN-MATERIAL: built-in cube wearing 'shamwaySelfTestProp_mat' covered=0.0%
VERIFY-DRAWN-CONTROL: built-in cube covered=38.8% zoomed-out=2.4%
```

Two hypotheses die here. It is **not** the vertex transform or uniform binding
(the program reads neither), and it is **not** an alpha-zero write from an
unbound sampler (the fragment writes alpha 1 unconditionally, and `Coverage`
counts `alpha > 8`).

### A check that would have cost one command

`glslangValidator` compiles the GLSL halves offline, with no editor and no
device, and names the line and the reason. The runtime names neither. It is now
a registered capability and a test — `GLSLCompilesTests` — that fails with the
original bug's own message when the extension line is removed:

```text
ERROR: 0:14: 'location' : not supported for this version or the enabled extensions
```

### Two false positives, and what caused both

Both were "it draws now!" results that were nothing of the kind, and both came
from the same mistake: splitting `shader_blob.py` on `#ifdef VERTEX` /
`#ifdef FRAGMENT` to patch a half, when **the file's own docstrings contain
those strings**. The split landed in prose, the patch went into the wrong
`void main`, and the resulting shader was broken — so Unity drew the error
shader at exactly the control's 38.8%, which reads like success.

The tell was available and initially missed: 38.8% is *identical* to the
control cube's number, because it **is** the control cube, wearing magenta. A
real result would not match the control to the decimal.

What fixed the method, and is now the rule for this lane: **patch the
`UNLIT_GLSL` literal by index, and validate both halves with
`glslangValidator` before every editor run.** A run whose shader was not
verified to compile proves nothing in either direction.

## After the record fix: the program loads and does not rasterize

Two probes were added to `BundleVerifier.cs` to split the remaining fault, both
reported every `--draw` run:

- **`VERIFY-DRAWN-MATERIAL`** puts the bundle's own material on the *built-in
  cube*. A built-in mesh that vanishes under this material accuses the
  material; one that draws accuses the mesh.
- **`VERIFY-DRAWNOW`** sets the pass by hand and calls `Graphics.DrawMeshNow`,
  bypassing culling, sorting and `LightMode` pass selection entirely.

What they say:

```text
VERIFY-PASS: passCount=1 SetPass(0)=True lightMode='<none>' renderType='Opaque'
VERIFY-DRAWNOW: direct SetPass+DrawMeshNow covered=0.0%
VERIFY-DRAWN-MATERIAL: built-in cube wearing 'shamwaySelfTestProp_mat' covered=0.0%
VERIFY-DRAWN-CONTROL: built-in cube covered=38.8% zoomed-out=2.4%
```

The built-in cube draws at 38.8% with its own material and **0.0% wearing
ours**, and a hand-issued draw of that same built-in mesh is also 0.0%. So:

- the **mesh is not the fault** — a built-in cube fails under this material;
- the **renderer is not the fault** — bypassing it changes nothing;
- **culling, sorting and pass selection are not the fault** — `DrawMeshNow`
  skips all three;
- the pass is **usable**: `SetPass(0)` returns `True`.

The narrowed statement is therefore: **the GPU program loads, the pass sets up,
and the program rasterizes no fragments.** That is a much smaller target than
"the prop is invisible", and it is where the next session should start.

`Material.GetTag("LightMode")` reading `<none>` is **not** evidence of anything:
`GetTag` reads *subshader* tags and `LightMode` is a *pass* tag, so it reads
`<none>` for stock shaders too. It is printed for context, not as a finding.

### Every pre-fix negative result is void

This matters more than any single entry below. Until the record tail was fixed,
**every** GLCore record this writer produced was eight bytes short, so every
experiment run against it failed for that reason whatever else it changed. The
eliminations recorded in the numbered list — the `$Globals` shape, the shared
source record, the keyword plumbing, the pass `m_State.m_Name` — were all
measured in that state and none of them are evidence.

Two have been **re-run** against the fixed writer, with the control cube healthy
in the same frame, and both are still negative:

| Re-tested after the fix | Result |
|---|---|
| `$Globals` of individual uniform members for GLCore instead of the d3d11 cbuffers | still `0.0%` |
| one shared source record, both stages at the same index (stock's shape) | still `0.0%` |

Two further single-variable tests, also against the fixed writer:

| Tried | Result |
|---|---|
| a vertex shader ignoring **every** uniform, writing clip space directly | still `0.0%` — so it is not the transform, the matrices, or uniform binding |
| removing the leading blank line before `#ifdef VERTEX`, so the source starts exactly as stock's does | still `0.0%`; reverted rather than kept, being neutral |

The remaining structural differences from stock, none yet tested against the
fixed writer, are in the source preamble: stock GLCore carries
`HLSLCC_ENABLE_UNIFORM_BUFFERS`, `UNITY_LOCATION`/`UNITY_BINDING` and a
`GL_ARB_shader_bit_encoding` guard that this writer's GLSL does not.

## Evidence

Same bundle, same editor (2022.3.62f2), one difference:

```text
VERIFY-SHADER: 'Shamway/Unlit' isSupported=True  passes=1 ... device=Null
VERIFY-SHADER: 'Shamway/Unlit' isSupported=False passes=3 ... device=OpenGLCore
Failed to load GpuProgram from binary shader data in 'Shamway/Unlit'.
VERIFY-MATERIAL: 'shamwaySelfTestProp_mat' shader='Shamway/Unlit'
                 shaderSupported=False _MainTex=<unbound>
```

In the live client, before this was understood, the same bundle reported every
member loading through the game's own `DataLoader`:

```text
shamwaySelfTestProp: children=0 renderers=1
shamwaySelfTestProp_mesh: vertices=24 submeshes=1 bounds=(0.30, 0.50, 0.20)
shamwaySelfTestProp_mat: shader=Shamway/Unlit
shamwaySelfTestProp_albedo: 256x256 RGBA32
SUMMARY pass=5 fail=0 skip=0 total=5
```

Both are true at once. The engine reads the whole object graph and then cannot
run the shader, and **a load is not a draw** — which is the distinction this
repository writes about and had not yet built a check for.

## What was ruled out

Each of these was measured, not assumed:

- **the container, and the game's own resolution of it.** 7DTD resolved the
  prefab, mesh, material and texture by stem through `DataLoader.LoadAsset<T>`,
  so the class-142 `m_Container` table, the stem lookup and the cross-object
  `PPtr` chain are all correct.
- **the prefab's structure.** `m_Layer = 0`, `m_IsActive = True`, the
  `MeshRenderer` `m_Enabled = True` with one material — read back out of the
  shipped bytes.
- **the mesh.** Authored bounds come back from the runtime, and the UV channel
  is present since the generator fix.
- **the block XML.** An earlier invented `Class="Decoration"` aborted
  `blocks.xml` entirely and cascaded into unrelated NREs; that is fixed and
  gated, and this run logs zero XML errors.
- **`platform.cfg`.** Reads `platform=Steam`, correct for a Steam launch.
- **the harness mods.** `7dtd-playtest` and `7dtd-fastconnect` load without
  arming; fastconnect reported the downstream NRE rather than causing it.

## What was wrongly concluded on the way, and how it was caught

An offline draw probe was added, and reported 100% frame coverage at every
zoom — read as proof that the vertex shader ignored the camera transform, on
the strength of which two constant-buffer edits were made to `shader_blob.py`.

Then a control was added: a built-in Unity cube rendered through the same
camera. It reported **100% too**. The probe was measuring itself — under
`-nographics` `Camera.Render()` draws nothing and the readback is
uninitialised. The shader edits were reverted; nothing about the constant
buffers is established either way.

The probe now renders that control every run and refuses to report a number
when it misbehaves. That refusal is what surfaced the `-nographics` problem
instead of producing a second confident wrong answer.

## What to measure next

The failing sub-program under `xvfb` is **OpenGLCore**, because that is what a
Linux editor creates. The game runs **d3d11** through Proton, so the two are
different code paths and a fix for one is not evidence for the other. Both are
written by `shader_blob.py`.

1. **Done.** The GLCore record layout is decoded in
   [research-provenance.md](../research/research-provenance.md), "The GLCore
   sub-program record". `source_blob()` and `UNLIT_GLSL` both match stock in
   shape, and an apparent mismatch in parameter-record "types" turned out to be
   a misread field: word1 is a **buffer count** on a parameter record, not a
   program type. That lead is withdrawn there.

   What the decode did surface: a stock GLCore sub-program describes **one
   `$Globals` buffer of individual uniform members**, matching GLSL that
   declares plain `uniform vec4 hlslcc_...`. This writer emits the d3d11 shape
   unchanged — `UnityPerDraw` and `UnityPerFrame` as constant buffers — beside
   GLSL that declares plain uniforms. The two disagree about how the uniforms
   are bound.

   **Tested, and it is not the cause.** Giving the GLCore platform a parameter
   blob describing a single `$Globals` of individual uniform members — the
   stock shape — changed nothing: `isSupported=False` and `Failed to load
   GpuProgram from binary shader data` as before, with the control cube reading
   a healthy `38.8% / 2.4%` in the same frame, so the negative is trustworthy.
   The change was reverted rather than kept on the grounds of being
   "more correct": it is unverified either way, and the one hard thing in this
   writer is the last place to carry an unverified edit.
2. **Superseded — this entry's headline was wrong.** It read "the GLSL is not
   the fault", and `UNLIT_GLSL` did in fact carry a compile error (the missing
   `GL_ARB_explicit_attrib_location` in the fragment half). The *observation*
   below stands: stock GLSL inside this container failed too. The inference
   from it did not, because the record-framing bug — eight missing trailing
   bytes — broke **every** record whatever source it carried, so substituting a
   known-good source could not have passed and its failure said nothing about
   the source. Left in place because the reasoning error is the point:
   a substitution that cannot pass is not a bisect.

   **The original entry, as written:** A stock shader's GLCore source
   (`Nature/SpeedTree Billboard`, 8251 chars) was substituted into this
   writer's container and rebuilt. The runtime answered exactly as before:

   ```text
   Failed to load GpuProgram from binary shader data in 'Shamway/Unlit'.
   VERIFY-SHADER: 'Shamway/Unlit' isSupported=False ... device=OpenGLCore
   VERIFY-DRAWN-CONTROL: built-in cube covered=38.8% zoomed-out=2.4%
   ```

   Known-good source in this container still fails, so the missing
   `HLSLCC_ENABLE_UNIFORM_BUFFERS` preamble and `UNITY_LOCATION`/`UNITY_BINDING`
   macros are not it, and neither is anything else about `UNLIT_GLSL`. This is
   the same bisect shape that cracked the d3d11 blob: stock contents inside a
   synthesized container isolate the container.

   What is left is the **wiring around the source**: the record indices a
   `PlatformBlob` publishes (`vertex_blob_index`, `vertex_parameter_index` and
   their fragment counterparts), `stageCounts`, the pass's `m_ProgramMask` and
   `m_State`, and whether GLCore wants one shared record rather than the two
   identical type-6 records this writer emits.

   Note that `passes` is not a clue: it reads 1 headless and 3 with a device
   because an unsupported shader reports the substituted error shader's passes.
3. **The real error is `Incompatible keyword states`, and it comes first.**
   The one-line `Failed to load GpuProgram` is not the whole message. The
   editor log carries a second error immediately before it, which the earlier
   greps had filtered out with the stack traces:

   ```text
   329: Incompatible keyword states
   337: Failed to load GpuProgram from binary shader data in 'Shamway/Unlit'.
   ```

   Four things are eliminated around it, each measured with the control cube
   reading a healthy `38.8% / 2.4%` in the same frame:

   | Tried | Result |
   |---|---|
   | stock GLCore GLSL inside this container | fails identically — the source is not it |
   | one shared source record, both stages pointing at it (stock's shape, `stageCounts=1`) instead of two identical records | no change |
   | a `$Globals` parameter blob of individual uniforms instead of the d3d11 cbuffers | no change |
   | a bundle containing **only** the `Shader` — no material, no prefab | both errors still appear, so the material is not involved |
   | a non-empty keyword space (`m_KeywordNames=["DIRECTIONAL"]`, one flag) | no change |

   The last one was worth trying because every stock shader carries 25–38
   keyword names and this writer carries **none**:

   ```text
   stock Nature/SpeedTree Billboard  keywordNames=26 keywordFlags=26 subshaders=2
   stock Standard                    keywordNames=37 keywordFlags=37 subshaders=2
   ours  Shamway/Unlit               keywordNames=0  keywordFlags=0  subshaders=1
   ```

   **Tested, and keywords are not the cause either.** All three surfaces were
   made to agree at once — the code record declaring `1 × "DIRECTIONAL"` the
   way stock's does, every sub-program's `m_KeywordIndices` pointing at it, and
   the Shader's `m_KeywordNames`/`m_KeywordFlags` naming it. Unchanged:
   `Incompatible keyword states`, `Failed to load GpuProgram`,
   `isSupported=False`.

   **So the error message is misleading, and that is worth knowing.**
   `Incompatible keyword states` appears with an empty keyword table, with a
   one-keyword table, and with fully consistent plumbing. It is far more likely
   a downstream symptom of the sub-program failing to load than a description
   of the cause. Anyone reading it fresh will spend a session on keywords; this
   entry exists so they do not.

4. **A positive control exists, and it clears the container.** A *stock*
   `Shader` object — `Legacy Shaders/Transparent/Cutout/VertexLit`, taken whole
   out of the game and written by **this writer**, through
   `bundle_writer.build_bundle`, into a bundle whose only object it is —
   loads on a real device:

   ```text
   VERIFY-SHADER: 'Legacy Shaders/Transparent/Cutout/VertexLit'
                  isSupported=True passes=3 renderQueue=2450 device=OpenGLCore
   ```

   No `Incompatible keyword states`, no `Failed to load GpuProgram`. So the
   UnityFS container, the SerializedFile, the type-tree serialization of class
   48 and the class-142 wiring are **all fine**. The fault is entirely in the
   *content* `bundle_writer.shader()` and `shader_blob.py` produce.

   This is the first known-good end this investigation has had. Everything
   before it was a negative against an unknown.

5. **Two more eliminations**, both single-variable against the known-bad:

   | Tried | Result |
   |---|---|
   | the four undecoded header words in the code record — checked across **334** stock GLCore records, all zero, same as this writer | not it |
   | the pass's `m_State.m_Name`, which stock sets to `FORWARD` and this writer sets to the *shader* name | no change |

   The pass name is worth fixing anyway on the grounds of being wrong, but it
   is not the cause.

6. **What is left**: the remaining difference between a stock `Shader` object
   and this one, bisected *from the working end*. Note that swapping the blob
   fields and the parsed form between stock and ours is **not** a valid
   experiment — a sub-program's `m_BlobIndex` addresses records inside its own
   blob, so the two halves are coupled and each arm fails for wiring reasons
   whatever else is true. It was tried, both arms failed, and both results are
   worthless. The valid shape is to start from the stock object and mutate it
   toward this one a field at a time, keeping the indices consistent at every
   step.

7. Re-check whether the bind-channel block, recorded as the fix for this exact
   `Failed to load GpuProgram` message, ever helped. It was validated against a
   headless `isSupported`, which cannot fail, so its evidence is as weak as the
   claim it supported.
8. Only then the d3d11 path, which needs a Windows or Proton-hosted editor to
   measure offline at all — or the live client, which is now a slow loop rather
   than the only one.

```bash
xvfb-run -a shamway verify-bundle --draw
```

That is a seconds-long loop and it fails today. Until it passes, no synthesized
prop draws in 7DTD, and `bundle_source = "unity"` remains the answer for
anything a player has to see.
