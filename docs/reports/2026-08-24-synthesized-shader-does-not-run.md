# Report — a synthesized prop places in 7DTD and renders nothing

## TL;DR

- **Observed:** a block whose `Model` is a synthesized prefab places in a live
  client, has collision, and draws nothing. No error, no magenta, no missing
  asset. Every offline gate passed and the in-client acceptance suite passed
  `5/5`.
- **Cause:** the synthesized shader does not compile on a real graphics device.
  `Shader.isSupported` is `False` and the runtime logs `Failed to load
  GpuProgram from binary shader data`.
- **Why nothing caught it:** `verify-bundle` runs the editor with
  `-nographics`. With no device there is nothing to compile a sub-program
  against, so `isSupported` returns `True` for a shader that does not run — and
  that value was recorded across five pages as evidence the shader worked.
- **Resolved by:** nothing yet. The false evidence is withdrawn and the
  measurement is fixed (`verify-bundle --draw`); the shader itself is still
  broken.
- **Still open:** the shader. See "What to measure next".

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

1. **Done, and it found something.** The GLCore record layout is decoded in
   [research-provenance.md](../research/research-provenance.md), "The GLCore
   sub-program record". `source_blob()` and `UNLIT_GLSL` both match stock in
   shape. What does not match is the **program type on the parameter records**:
   every parameter record in a stock GLCore blob is type `2`, and this writer
   emits types `3` and `1`, plus the same GLSL twice as two type-6 records.
   Decide that by decoding a stock type-2 record and comparing it against
   `ParameterBlob.to_bytes()` — it is either per-stage and legal, or it is the
   answer.
2. Re-check whether the bind-channel block, recorded as the fix for this exact
   `Failed to load GpuProgram` message, ever helped. It was validated against a
   headless `isSupported`, which cannot fail, so its evidence is as weak as the
   claim it supported.
3. Only then the d3d11 path, which needs a Windows or Proton-hosted editor to
   measure offline at all — or the live client, which is now a slow loop rather
   than the only one.

```bash
xvfb-run -a shamway verify-bundle --draw
```

That is a seconds-long loop and it fails today. Until it passes, no synthesized
prop draws in 7DTD, and `bundle_source = "unity"` remains the answer for
anything a player has to see.
