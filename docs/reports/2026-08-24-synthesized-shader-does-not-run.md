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
