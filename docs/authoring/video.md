# Video: staged motion clips and the deadeye review lane

Sight is the twin of the audio lane's "why a loaded clip can be silent": a
mesh that loads, validates, and renders into a clay icon can still be wrong in
the one way a still cannot show. A garment that clips only mid-turn, a prop
whose silhouette reads wrong only while carried, a shader that pops at an
angle the render never sampled — each needs motion, and motion needs a clip.

This page is the motion side of the authoring lanes: how an asset declares a
staged motion clip, how `shamway acceptance-provider` generates the case that
captures it, how `shamway client capture --clip` adopts the result, and how
`shamway review-video` asks a vision model to look at it — with the same
advisory, never-auto-accepting posture the audio review has.

## Quick start

Declare the motion kind for the asset in `.shamway.toml`, then generate,
adopt, and review:

```toml
[acceptance]
motion_kinds = { thing = "turntable" }
```

```bash
shamway acceptance-provider
# run the suite from a hordeforge/7dtd-playtest checkout (owns the client lock)
shamway client capture thing --clip .local/capture/demo-20260825/thing \
    --observable "grip reads at the right thickness through a full turn"
shamway review-video thing --clip .local/acceptance/thing \
    --intent assets-src/bundle/thing.review.json --allow-network
```

Everything below is detail.

## The motion-kind declaration

`[acceptance] motion_kinds` maps an asset stem to one of three kinds:

| Kind | Generated case | What the case does |
|---|---|---|
| `turntable` | `CaseDef.StagedClip` | stages the prefab in front of the camera and rotates it one full turn, so the captured frames prove the silhouette from every side |
| `walk-cycle` | `CaseDef.Live` + on-demand recording | equips the item on the player (`Helpers.TryEquipItem`) and records the player actually walking with stock autorun (`Helpers.StartWalk`), then stops walk and clip; a walk-cycle declared on a non-wearable asset fails the case rather than holding silently |
| `fixed` | today's `Staged` look case, unchanged | a world-fixed thing has no motion worth capturing; declaring `fixed` opts out |

A stem with no declaration generates exactly what it generated before this
feature existed — byte for byte. A motion kind declared on a member that is
not a mesh/prefab (`GameObject`) is refused, not silently ignored, so a typo
in the stem cannot read as a working motion case.

The declaration lives in the mod's configuration rather than the tracked
manifest on purpose: the manifest is regenerated on every `shamway build`, so
an author-owned declaration there would be wiped. The configuration is the
one per-mod file that survives rebuilds.

## Capturing the clip

`CaseDef.StagedClip` is `7dtd-playtest`'s primitive (see that repository's
`docs/INGAME_VIDEO_CAPTURE.md`): it stages the prefab in front of the camera,
holds for 12 seconds, and writes `frame-XXXX.png` files from the client
process's own framebuffer — no desktop grab, no compositor, the same
"this is this process's own rendering" guarantee a single staged frame has.
`scripts/capture_video.sh` (also in `7dtd-playtest`) waits for the
`clip complete <id>` log line and muxes the frames into an mp4.

`shamway client capture LABEL --clip DIR` adopts that clip directory (frames,
muxed video, `client.log`) into `.local/acceptance/`, hashed and labeled the
same way a single adopted screenshot already is. It records; it never
re-captures, muxes, or reviews. Re-adopting a label replaces its earlier
entry, exactly like a re-captured single frame.

## The review

```bash
shamway review-video thing --clip .local/acceptance/thing \
    --intent assets-src/bundle/thing.review.json \
    --provider gemini --model gemini-2.5-flash --allow-network --json
```

`review-video` only ever runs against a recorded, hash-addressed capture: the
clip must have been adopted by `client capture --clip`, or the command refuses
— the same boundary `client capture --file` already draws between taking a
screenshot and recording one somebody else took.

The intent file, committed beside the source, states what the clip is
supposed to demonstrate:

```json
{
  "schema_version": 1,
  "purpose": "show the garment survives a full turn without clipping",
  "subject": "thing (worn garment)",
  "camera_path": "turntable",
  "desired_qualities": "proportions and silhouette read right from every side",
  "avoid": ["clipping", "popping", "z-fighting"],
  "questions": ["does the grip read thin through the turn?"],
  "suite": "demo",
  "case": "thing"
}
```

`purpose` is required and never inferred from a filename. The actual model I/O
happens through the **deadeye** gateway (`hordeforge/7dtd-vision-review`), the
shared vision-model review component: it samples the clip down to the
provider's frame budget (even spacing, first and last always kept), submits
it, validates the model's answer, and returns one evidence envelope. This
pipeline's operation adds the asset's provenance and its own evidence
document around that envelope.

The result is the same family the audio review uses — `summary`, `strengths`,
`issues` (tied to a timestamp or frame index), `recommended_changes`,
`rubric_scores`, `confidence`, `limitations` — so a caller handling both
review kinds reads one shape.

### Gates and boundaries

- `--allow-network` is required. The submission is networked, billable, and
  sends an authored asset to a third party; nothing here contacts a provider
  implicitly, and no refusal reads credentials before the consent gate.
- Credentials come from the provider's environment variables
  (`GEMINI_API_KEY` / `GOOGLE_API_KEY` for gemini, `NVIDIA_API_KEY` for
  nvidia) or from the gateway's gitignored `config.local.toml`
  (`[providers.<name>] api_key`, see the gateway's README for the
  precedence). They are never accepted as
  a command argument, printed, or written into evidence.
- The verdict is advisory. `ADVISORY_NOTE` rides every result: a model
  critique is evidence about the submitted clip under the recorded intent; it
  cannot satisfy the fresh-client human-look acceptance gate. Model review may
  block promotion only when a consuming project explicitly configures that
  policy.
- The evidence document (default beside the clip, or `--output`) is
  hash-addressed: SHA-256 of every submitted frame/clip file and the intent
  file, the asset's source file and its hash (per-asset generation arguments
  are not yet recorded by this pipeline, so the source hash is the comparable
  address between revisions — never a guess), the sampling record, provider
  and model, rubric and prompt versions, and the full gateway envelope. A
  later review never overwrites an earlier document.

### The provider capability

`shamway capabilities --json` reports `model-video-review`: the deadeye
gateway CLI on PATH, plus the provider's credential environment. Install it
with:

```bash
uv tool install --from git+https://github.com/hordeforge/7dtd-vision-review
```

`deadeye doctor --json` reports which providers are configured without
contacting any of them.

## The offline gate table, extended

| Evidence | What it proves |
|---|---|
| `check-mesh` | The source is mechanically healthy |
| `render-icon` | A clay render exists for the icon path |
| model video review | A named model critiqued the submitted clip under recorded context and generation parameters |
| `acceptance-provider` case | The game loaded/played the asset in the tested path |
| `client capture` + human look | A person accepted the experience in its actual game context |

A load is not a look. A green acceptance suite and a passing model critique
are both evidence; only the human look at the end accepts anything.

## Worked example

### The end-to-end test

The specific, runnable proof of the whole loop is one opt-in live test:

```text
tests/test_video_review_live.py
  └─ test_the_full_chain_reviews_a_real_clip_and_names_the_pop
```

It scaffolds a minimal mod, generates a synthetic 12-frame clip (a red marker
that sweeps smoothly and disappears for one frame), muxes it to `clip.mp4`
with ffmpeg, adopts it through the same `record_existing_clip` path
`shamway client capture --clip` uses, writes the intent, and runs the real
review against the NVIDIA omni model. It asserts the evidence document, the
asset provenance, that no credential leaked, that the muxed video actually
reached the provider (not sampled frames), and that the verdict passes the
result schema; then it prints the model's verdict for the human.

Run it from this repository's root, with the gateway configured (its
`deadeye` on PATH and the key in its `config.local.toml`):

```bash
export PATH="$HOME/code/hordeforge/7dtd-vision-review/.venv/bin:$PATH"
export DEADEYE_CONFIG_DIR="$HOME/code/hordeforge/7dtd-vision-review"
export SHAMWAY_NETWORK_TESTS=nvidia
PYTHONPATH=src:tests python3 -m unittest tests.test_video_review_live -v
```

Real output from a green run:

```text
test_the_full_chain_reviews_a_real_clip_and_names_the_pop ... ok

LIVE REVIEW SUMMARY: The red square moves smoothly from left to right across a
         black background, maintaining a consistent size and clear silhouette.
LIVE REVIEW ISSUE: Marker decelerates, indicating non-even spacing of motion
LIVE REVIEW CONFIDENCE: 0.96
```

### The same loop by hand

The test's steps are the real commands for a captured clip (here a
`frame-*.png` sequence muxed to `clip.mp4` by `capture_video.sh`):

The intent file, committed beside the source:

```json
{
  "schema_version": 1,
  "purpose": "verify the marker moves smoothly across the clip without popping or jumping",
  "subject": "thing (synthetic marker)",
  "camera_path": "fixed",
  "desired_qualities": "continuous, evenly spaced motion",
  "avoid": ["popping", "jumping", "jitter"],
  "questions": ["does the marker pop at any point?"],
  "suite": "demo",
  "case": "thing"
}
```

Adopt the captured clip, then review it:

```bash
shamway client capture thing --clip .local/capture/demo-20260825/thing \
    --observable "the marker must sweep smoothly without popping"
shamway review-video thing --clip .local/acceptance/thing \
    --intent assets-src/bundle/thing.review.json \
    --provider nvidia --allow-network --json
```

The muxed mp4 is submitted as video (`video_url`, not sampled frames — the
evidence's `sampling` note says so), and the evidence document lands beside
the clip. The model's verdict on that run:

```text
summary: The red square moves smoothly from left to right across a black
         background, maintaining a consistent size and clear silhouette.
         The motion is continuous with no visible popping, jumping, or
         clipping, meeting the author's criteria.
issue:   Marker decelerates, indicating non-even spacing of motion
confidence: 0.96
```

Optionally, before submitting anything, render the exact instruction the
gateway will inject (the prompt is built for you; this just shows it):

```bash
deadeye prompt --intent assets-src/bundle/thing.review.json --clip .local/acceptance/thing
```

Model verdicts are advisory and vary by run (the same clip's disappearance
was named "marker disappears (pop)" on an earlier run; the positional-jump
variant has been called both smooth and flagged). The review is evidence for
the human look, never a substitute — and the evidence document is what makes
each run's verdict citable and comparable.
