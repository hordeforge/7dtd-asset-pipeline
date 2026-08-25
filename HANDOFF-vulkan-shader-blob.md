# Handoff: finish the uncommitted Vulkan change in `/tmp/7dtd-launchfix`

The task I was about to run, with everything needed to do it by hand.

## Quick start

Inspect the change, test it, commit it on a branch, open the PR:

```bash
cd /tmp/7dtd-launchfix
git diff src/sevendtd_asset_pipeline/shader_blob.py
env -u SEVEN_DAYS_TO_DIE_DIR make check test
git checkout -b feat/vulkan-stock-shaped-records
git add src/sevendtd_asset_pipeline/shader_blob.py
git commit
git push -u origin feat/vulkan-stock-shaped-records
gh pr create --fill
```

Everything below is the context and the reasoning for each step.

## What the situation is

`/tmp/7dtd-launchfix` is a **worktree** of `hordeforge/7dtd-asset-pipeline`
(branch `work`, currently on `origin/main` = `854aae4`). One file is modified
and uncommitted:

```text
M src/sevendtd_asset_pipeline/shader_blob.py
```

That diff is the last block of Vulkan work from the 2026-08-24/25 session. It
was never committed because the session moved on to transplant experiments and
then stopped. If it is discarded, the next session re-derives it from the docs;
if it is committed, the code matches what the merged documentation already
describes.

## What the diff contains (expected)

Three Vulkan-only additions, none of which touch the d3d11 or GLCore lanes:

- `UNLIT_VERTEX_HLSL_VULKAN` — a vertex shader whose constants live in **one**
  `VGlobals` cbuffer, because Unity's Vulkan parameter records name per-stage
  `VGlobals`/`PGlobals` buffers, not the d3d11 `UnityPerDraw`/`UnityPerFrame`.
  Nothing in a stock Vulkan blob uses the d3d11 names.
- `VULKAN_VERTEX_GLOBALS` / `VULKAN_VERTEX_CBUFFER` — the declared layout for
  that buffer (`unity_ObjectToWorld` at 0, `unity_MatrixVP` at 64).
- The Vulkan platform assembling **one shared parameter record and one shared
  code record**, with both stages' indices pointing at record 0 and record 1 —
  the exact shape a stock Vulkan blob has (`stageCounts` = 1, one type-25 code
  record carrying both SMOL-V modules).

## Why commit it even though Vulkan still doesn't render

The change did **not** fix the magenta. The blocker is elsewhere (below). But:

- it makes our Vulkan blob **byte-shape-identical to stock's** — same record
  count, same sharing, same buffer naming convention;
- the merged docs (#89, #92, #95, #96 in `docs/research/research-provenance.md`
  and `docs/status/improvements.md`) describe this state; main's code currently
  does not match its own documentation;
- it is scoped: during the session I verified the built bundle still emits
  `d3d11 → UnityPerDraw`, `glcore → UnityPerDraw/UnityPerFrame`,
  `vulkan → VGlobals`. d3d11 and d3d12 rendering were confirmed working *after*
  this change existed.

## Step 1 — inspect the diff

```bash
cd /tmp/7dtd-launchfix
git diff src/sevendtd_asset_pipeline/shader_blob.py
```

What to check: every hunk should be inside the Vulkan block of
`unlit_textured()` or a new top-level `VULKAN_*` / `UNLIT_VERTEX_HLSL_VULKAN`
definition. **If any hunk changes the d3d11 or GLCore assembly** (the
`d3d11_raw` / `gl_raw` lists, `UNITY_PER_DRAW`, `UNITY_PER_FRAME`), stop and
revert instead — that would be an experiment leftover, not the intended change:

```bash
git checkout -- src/sevendtd_asset_pipeline/shader_blob.py
```

## Step 2 — run the suite

`SEVEN_DAYS_TO_DIE_DIR` leaking into the test environment changes several
doctor/preflight tests' answers, so unset it for the run:

```bash
cd /tmp/7dtd-launchfix
env -u SEVEN_DAYS_TO_DIE_DIR make check test
```

Expected: `OK` with ~512 tests. If `test_packaged_pages_are_the_repo_pages`
fails, the packaged docs drifted; re-sync and re-run:

```bash
cd /tmp/7dtd-launchfix/docs
find . -name "*.md" -exec cp {} ../src/sevendtd_asset_pipeline/docs/{} \;
```

## Step 3 — confirm all three platforms still emit

The Vulkan platform only appears when the SMOL-V encoder is loadable. The
built library from this session is at `/tmp/zmol-v/zig-out/lib/libzmolv.so`
(source: `github.com/ywy50/zmol-v`; rebuild with `zig build` in a clone if the
`/tmp` copy is gone):

```bash
cd /tmp/7dtd-launchfix
ZMOLV_LIBRARY=/tmp/zmol-v/zig-out/lib/libzmolv.so .venv/bin/python -c "import sys; sys.path.insert(0,'src'); import sevendtd_asset_pipeline.shader_blob as sb; print([p.platform for p in sb.unlit_textured().platforms])"
```

Expected: `[4, 15, 18]`. Without `ZMOLV_LIBRARY`: `[4, 15]` — that fallback is
deliberate (a host without the codec builds what it always did).

## Step 4 — commit, push, PR

Branch in the worktree (never switch branches in
`~/code/hordeforge/7dtd-asset-pipeline` — it is shared between sessions):

```bash
cd /tmp/7dtd-launchfix
git checkout -b feat/vulkan-stock-shaped-records
git add src/sevendtd_asset_pipeline/shader_blob.py
git push -u origin feat/vulkan-stock-shaped-records
```

Suggested commit message (no trailers, per repo rules):

```text
Shape the Vulkan blob the way stock shapes it

One shared parameter record and one shared code record, both stages pointing
at them, and the vertex constants in a single VGlobals buffer - the layout
every stock Vulkan blob has. Decoded from Legacy Shaders/Transparent/Cutout/
VertexLit: a Vulkan parameter record declares VGlobals<hash>/PGlobals<hash>
per stage, nothing in it uses the d3d11 buffer names, and stageCounts is 1.

This is not the fix for the magenta prop; the blocker is the validated 32-byte
hash (research-provenance.md, "The Vulkan hash IS validated"). It is committed
because it removes every other difference from stock, matches what the merged
documentation describes, and is scoped so the d3d11 and GLCore lanes are
byte-identical to before - both were re-verified rendering after this change.
```

Then merge once CI is green (`gh pr checks --watch`, `gh pr merge --squash`).

## Also outstanding: the deployed test mod carries an experiment

The deployed `ShamwaySelfTest` in the client's `Mods/` still contains the
**last transplant bundle** (stock modules inside our record), not a clean
build. Before any future acceptance run, rebuild and redeploy:

```bash
cd /tmp/7dtd-launchfix/examples/SelfTestMod
ZMOLV_LIBRARY=/tmp/zmol-v/zig-out/lib/libzmolv.so ../../.venv/bin/shamway build
../../.venv/bin/shamway client deploy .
```

(`shamway client deploy` takes the shared client lock itself; needs
`SEVEN_DAYS_TO_DIE_DIR` exported.)

## Context: where the Vulkan investigation stands

Platforms: **OpenGL Core ✅, Direct3D 11 ✅, Direct3D 12 ✅** (all verified in a
live client, d3d12 machine-captured), **Vulkan ❌** magenta.

Proven about the magenta, each with a captured frame:

- stock record + stock modules + stock hash → **renders** in our shader
- our record + stock's own modules + zero hash → **magenta**
- record heads and size tables byte-identical → the **32-byte hash at payload
  words 20..27 is validated** by Unity; mismatch is rejected silently.

The hash is not (all computed with reference SpookyHash V2 and standard
digests): each SMOL-V module, both concatenated, incremental, chained, each
decoded SPIR-V, sub-ranges of the payload, integer-prefixed variants, seed
sweeps including section sizes. Full negative list:
`docs/research/research-provenance.md`, "Hunting the Vulkan hash".

Next real step is disassembly, starting points already located in
`UnityPlayer.dll` (31 MB, in the game install):

- SMOL-V magic `0x534D4F4C` at file offsets `0x8925bc` and `0x8e7a1b`
  (the second is `smolv::Decode`'s header check; `smolv_RemapOp` is nearby)
- SpookyHash constant `0xDEADBEEFDEADBEEF` at 7 sites around `0xa36ef4`

Tools built during the session, all in `/tmp` (rebuild with `zig c++` from
`aras-p/smol-v` + `rurban/smhasher` sources if gone): `spooky_seeded`
(file, two seeds), `spooky_chain` (chained/incremental variants),
`smolv_decode` (SMOL-V → SPIR-V). Reference fixtures: `/tmp/stockA.smolv`,
`/tmp/stockB.smolv` and their decoded `.spv`, with expected halves
`c9dae3ee4501d8bee8b28c965c85e3f9` / `c6db081ec58e178a3377170abf47ac70`.

---

# The actual next task: crack the Vulkan hash

This is the concrete procedure, not just the starting points. Goal: learn what
bytes Unity feeds SpookyHash and with which seeds, so `vulkan_code_blob` can
compute the 32-byte field instead of writing zero. Once it matches, Vulkan
renders (everything else is already stock-equivalent).

## What "done" looks like

A function `vulkan_shader_hash(module_a, module_b) -> bytes(32)` that, given a
stock record's two SMOL-V modules, reproduces that record's stored bytes at
payload offset 80..112. Verify against the fixtures:

- input: `/tmp/stockA.smolv`, `/tmp/stockB.smolv` (and/or their `.spv`)
- expected output halves:
  `c9dae3ee4501d8bee8b28c965c85e3f9` then `c6db081ec58e178a3377170abf47ac70`

## Option A — disassembly (authoritative, ~1-2 h)

Needs a disassembler with cross-references. `objdump` alone is not enough on a
stripped 31 MB DLL; use radare2 or Ghidra.

```bash
sudo pacman -S radare2      # or: yay -S ghidra
G="/home/yannick/Games/Steam/steamapps/common/7 Days To Die"
r2 -A "$G/UnityPlayer.dll"   # -A runs analysis; slow on 31 MB, let it finish
```

1. Seek to the SMOL header check and find its function:

   ```
   [0x...]> s 0x8e7a1b        # second SMOL magic site (Decode's header check)
   [0x...]> af               # analyse the function here
   [0x...]> afi              # its address range and callers
   ```

2. Find that function's **caller** — the hash validation is in the caller, not
   in `Decode` itself:

   ```
   [0x...]> axt $$           # cross-references TO this function
   ```

   Seek to the caller (`s <caller addr>`, `af`, `pdf`). In it, look for:
   - a call passing a buffer pointer + length, whose result (two 64-bit values,
     or a 16-byte write) is **compared** against bytes read from the record at
     `+80` / `+96`;
   - that call target is SpookyHash. Confirm by seeking into it and checking
     for the `0xDEADBEEFDEADBEEF` constant (the 7 sites near `0xa36ef4`).

3. Read off, from the caller: **which buffer** (the raw record slice? each
   module? the decoded SPIR-V? does it decode first?), **what length**, and
   **what seeds** (two registers set before the call — often 0/0, or the
   section size, or a running value).

4. Reproduce it with `/tmp/spooky_seeded <file> <seed1> <seed2>` and the exact
   input the disassembly named. When it matches the expected halves, you have
   the recipe.

## Option B — differential brute force (cheaper, may miss)

If the input is a straightforward slice and only the **seeds** are unknown,
sweep them harder than the session did. A stock record gives a known
(input, output) pair, so this is offline and needs no game.

```bash
cd /tmp/7dtd-launchfix
# extend /tmp/spooky_seeded's sweep: for each candidate input (A.smolv,
# B.smolv, A.spv, B.spv, A+B, payload[80..] etc.) try seed1,seed2 over
# 0..4096 and the set {section sizes, decoded sizes, 25, 18, 0xFFFFFFFF}.
```

The session already tried the small structured seed set and all obvious inputs
(see research-provenance.md "Hunting the Vulkan hash"), so a plain seed sweep is
only worth it up to a few thousand; beyond that, do Option A. If the input is
transformed (debug-info-stripped SPIR-V, a length prefix inside the hashed
buffer), brute force will not find it and Option A is the only route.

## Option C — the shortcut worth trying first (~10 min)

Unity computes this hash **at build time**, from the SPIR-V it compiled, and it
is very likely the plain `Hash128` of the **debug-stripped** SPIR-V module —
the session hashed the *un*stripped decoded SPIR-V and missed. Try:

```bash
# spirv-opt is in the vulkan-tools / spirv-tools package
spirv-opt --strip-debug /tmp/stockA.spv -o /tmp/stockA.stripped.spv
spirv-opt --strip-debug /tmp/stockB.spv -o /tmp/stockB.stripped.spv
/tmp/spooky_seeded /tmp/stockA.stripped.spv 0 0
/tmp/spooky_seeded /tmp/stockB.stripped.spv 0 0
```

Compare each against the expected halves. If a half matches, the recipe is
"decode SMOL-V → strip debug → SpookyHash128 seeds 0,0", and it's a short
addition to `shader_blob.py` (call `smolv_decode`, then `spirv-opt`, then a
SpookyHash binding). If not, fall through to Option A.

## When you have the recipe

Add `vulkan_shader_hash` to `shader_blob.py`, call it from `vulkan_code_blob`
to fill payload bytes 80..112 (currently zeroed there), rebuild the SelfTestMod
bundle, and run the automated Vulkan capture:

```bash
cd /tmp/7dtd-launchfix/examples/SelfTestMod
GFX_API=vulkan bash /tmp/7dtd-launchfix/scripts/playtest-capture.sh --case look_shamwaySelfTestProp --label vk &
GFX_API=vulkan SEVEN_DAYS_TO_DIE_SERVER_DIR=/home/yannick/steam-server-build \
  bash /tmp/7dtd-launchfix/scripts/playtest-acceptance.sh --mod-root .
```

A textured card (not magenta) in the collected frame is the win. Then it's a
normal PR: branch in the worktree, `make check test`, push, `gh pr merge`.
