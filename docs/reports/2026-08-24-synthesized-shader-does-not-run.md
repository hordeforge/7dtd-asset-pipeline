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
2. **The GLSL is not the fault — bisected.** A stock shader's GLCore source
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
3. Re-check whether the bind-channel block, recorded as the fix for this exact
   `Failed to load GpuProgram` message, ever helped. It was validated against a
   headless `isSupported`, which cannot fail, so its evidence is as weak as the
   claim it supported.
4. Only then the d3d11 path, which needs a Windows or Proton-hosted editor to
   measure offline at all — or the live client, which is now a slow loop rather
   than the only one.

```bash
xvfb-run -a shamway verify-bundle --draw
```

That is a seconds-long loop and it fails today. Until it passes, no synthesized
prop draws in 7DTD, and `bundle_source = "unity"` remains the answer for
anything a player has to see.
