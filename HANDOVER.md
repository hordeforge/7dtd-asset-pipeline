# Handover — synthesized shader across graphics APIs

Written 2026-08-25. Read this before touching the Vulkan lane.

## Status, honestly

| Platform | State | Evidence |
|---|---|---|
| OpenGL Core | **works** | human-verified in a live client, orientation card correct |
| Direct3D 11 | **works** | human-verified in a live client, texture correct |
| Direct3D 12 | **works** | machine-captured frame at 2560×1920, card correct |
| Vulkan | **NOT confirmed** | see below — do not claim it renders |

**Vulkan has never been confirmed rendering.** Every Vulkan attempt this
session either drew the magenta error shader or was inconclusive. The most
recent change (bind-channels tail with SPIR-V-location targets) is verified
**offline only** — unit tests pass and the record now matches stock's byte
shape — but **no live client has shown the prop drawn on Vulkan**. One run with
that change hung the client mid-draw before capturing; a later run was still in
flight when the session ended (`/tmp/vkfinal.log`, and the shot, if any, at the
client's `playtest-shots/look_shamwaySelfTestProp.png`). Treat Vulkan as open.

Also unresolved on the *working* platforms: a **translucency** the user saw and
pixel-measurement confirmed (card dark region rendered ~(70,74,80) vs source
albedo (28,32,38)). Our blend state is `One`/`Zero`, `colMask 15`, so it should
be opaque. Not explained. Not the gamma trap (colour space is correct).

## Uncommitted work in this worktree (`/tmp/7dtd-launchfix`)

Branch `fix/vulkan-bind-channels` has staged, **un-committed** changes:

- `src/sevendtd_asset_pipeline/shader_blob.py` — the Vulkan lane: a `VGlobals`
  vertex HLSL, one shared parameter + one shared code record, and the
  `ParserBindChannels` tail with SPIR-V-location targets `(0,0),(4,1)`.
- `tests/test_shader_writer.py` — tests for the above (green:
  `env -u SEVEN_DAYS_TO_DIE_DIR make check test` → 512 pass).
- `docs/research/research-provenance.md` — the retraction (below) and findings.

**Do not commit the `examples/SelfTestMod/tools/.../obj/` files** that also show
as modified — those are C# build artifacts, not source. Stage only the three
paths above:

```bash
cd /tmp/7dtd-launchfix
git add src/sevendtd_asset_pipeline/shader_blob.py tests/test_shader_writer.py docs/
git commit    # message draft below
```

Before committing, re-sync packaged docs or the docs test fails:

```bash
cd /tmp/7dtd-launchfix/docs && find . -name '*.md' -exec cp {} ../src/sevendtd_asset_pipeline/docs/{} \;
```

Commit message: describe it as **"emit the Vulkan bind-channels tail (offline
only; not confirmed rendering)"** — NOT as a fix. It removes the last known
structural difference from stock, but the render is unproven.

## What is proven about Vulkan (all measured, keep)

1. **The container shape** matches stock: platform 18, program type 25, one
   type-25 code record carrying both SMOL-V modules, `stageCounts` 1, the
   six-word size table whose invariants hold, `VGlobals`/`PGlobals` per-stage
   parameter buffers, descriptor sets (constant buffers in set 1).
2. **Section order**: A = fragment, B = vertex, read from `OpEntryPoint`.
3. **The 32-byte hash is NOT validated.** Corrupting every byte of it in an
   otherwise-untouched *stock* blob still renders. This overturns three earlier
   provenance sections and PRs #95/#96 that concluded the hash mattered — a
   negative-observation trap. The retraction is written into
   `research-provenance.md`.
4. **The real acceptance blocker was the missing bind-channels tail**, found by
   byte-diffing our record against a stock one with the same modules: identical
   but for the (harmless) hash, and stock was 32 bytes longer — that block.
   Adding it changed the live behaviour from clean-magenta to hung-mid-draw,
   which means the record is now *accepted* and the program *executed*. That is
   the only in-client evidence the tail helped; it is not evidence it draws.

## The next step for Vulkan

Confirm or fix the **bind-channel target values**. Ours are the SPIR-V input
locations `(Position→0, TexCoord0→1)`, derived from our glslang vertex module's
`OpDecorate ... Location`. Stock `VertexLit` used `(0,13)(1,14)(4,15)` — larger
targets whose meaning was not decoded. If our locations are wrong the vertex
shader reads the wrong stream and the client hangs (as observed once).

Run it — one command, unattended, no manual placement:

```bash
cd /tmp/7dtd-launchfix/examples/SelfTestMod
export ZMOLV_LIBRARY=/tmp/zmol-v/zig-out/lib/libzmolv.so \
       SEVEN_DAYS_TO_DIE_DIR="/home/yannick/Games/Steam/steamapps/common/7 Days To Die" \
       SEVEN_DAYS_TO_DIE_SERVER_DIR=/home/yannick/steam-server-build GFX_API=vulkan
shamway build
bash ../../scripts/playtest-acceptance.sh --mod-root .
```

Then read the frame (in-game, 2560×1920) at
`…/7DaysToDie/playtest-shots/look_shamwaySelfTestProp.png`. Magenta = still
wrong; the textured card = Vulkan finally works. **Only a look at that frame
confirms it** — the suite passing does not, and neither do the offline tests.

If it hangs again, the targets are the suspect: decode them from stock by
correlating each pair's target against that module's SPIR-V
`OpDecorate <id> Location`, or try a small set by hand.

## Related repos touched this session (all merged, all pushed)

- `ywy50/zmol-v` — SMOL-V codec in Zig + the Unity Vulkan container knowledge.
  Latest commit records the bind-channels tail and the hash-is-not-validated
  finding. `libzmolv.so` built at `/tmp/zmol-v/zig-out/lib/`.
- `hordeforge/7dtd-playtest#48` — in-game `CaptureFrame` (staged cases
  photograph their own framebuffer, supersized). This is why capture is
  unattended now.
- `hordeforge/7dtd-fastconnect#19` — `GFX_API` selects the graphics API
  (was hardcoded `-force-d3d11`).

## Tools left in `/tmp` (rebuild from aras-p/smol-v + rurban/smhasher if gone)

`spooky_seeded`, `spooky_sweep`, `spooky_magic`, `spooky_chain`, `smolv_decode`,
`spooky_oracle`. Fixtures: `/tmp/stockA.smolv`, `/tmp/stockB.smolv`, decoded
`.spv`. Stock hash halves (for reference only — the field is unvalidated):
`c9dae3ee4501d8bee8b28c965c85e3f9` / `c6db081ec58e178a3377170abf47ac70`.

## Rules that bit this session

- **Work in a git worktree** for hordeforge repos — they are shared between
  sessions. A pushed branch lost its commit when another session reset the
  shared checkout; recovered via `git cat-file` + `git cherry-pick`.
- **A staged case passing is not a look.** Every acceptance case passes on a
  magenta prop. The frame is the evidence.
- **Take the frame in-game, never a desktop grab** — a desktop capture
  photographed another session's client repeatedly.
