# PRD — Video-based asset review

## Status

Draft. This specifies an unbuilt `shamway review-video` command, a
`review_video` operation in `operations.OPERATIONS` and `api._DISPATCH`, an
optional video-review provider capability in `capabilities.REGISTRY`, and a
motion-kind field on the `acceptance-provider` manifest (`acceptance.py`). No
current command sends a clip or a frame sequence to a model, and no
`acceptance-provider`-generated case does anything but load an asset once.
Companion to `0001-contextual-model-audio-review.md`, mirroring its shape for
sight instead of hearing, and to
[`7dtd-playtest`'s video-capture and video-review
plans](https://github.com/hordeforge/7dtd-playtest/blob/main/docs/ASSET_VIDEO_FEEDBACK_LOOP.md),
which this PRD is the asset-pipeline half of.

## Problem

`shamway render-icon` renders a candidate mesh with headless Blender: fast,
needs no editor, but no lighting, no animation, no pose, no engine. `shamway
client capture` proves a person looked at a real, in-game moment, but it is
one frame, chosen and framed by a human at capture time. Neither shows a
worn, placed, or moving asset the way a player actually sees it, and a still
cannot show a defect that only exists in motion: a garment that clips only
mid-turn, a prop whose silhouette reads wrong only while carried, a shader
that pops at an angle the render never sampled.

`7dtd-playtest` (a sibling repository this project already generates
acceptance scenarios for, via `shamway acceptance-provider`) is adding an
in-engine, multi-frame staged clip capability
(`CaseDef.StagedClip`, see its `docs/INGAME_VIDEO_CAPTURE.md`) and a vision-
model review of the result (`docs/VIDEO_MODEL_FEEDBACK.md`). That capability
answers "does this motion look right" for a playtest suite generally. This
PRD is about the one thing only this project can add: connecting a reviewed
clip back to the exact generation parameters that produced the candidate, so
the critique is actionable at the point a mod actually edits its assets, and
comparable across the revisions `shamway generate mesh` produces.

Video-capable model APIs exist today, the same landscape `0001` already
surveys for audio: Google's Gemini API documents video understanding from
uploaded video, and multi-image input is broadly supported across vision-
chat APIs even where native video upload is not. Provider support and model
identifiers change, so this pipeline discovers configured capability rather
than hard-coding one vendor, exactly as `0001` already requires for audio.

## Goals

1. Let an agent submit an already-captured clip (frames and/or a muxed
   video), the asset's generation parameters, and explicit intended-use
   context to a configured video-capable model.
2. Return structured, actionable criticism in the same result shape
   `0001` already defines for audio (`summary`, `strengths`, `issues`,
   `recommended_changes`, `rubric_scores`, `confidence`, `limitations`), so a
   caller handling both review kinds sees one family of results.
3. Carry the reviewed candidate's generation parameters (mesh seed, shape,
   size, or the source file's hash for an adopted/external asset) in the
   evidence document, so a later revision's review is comparable to the one
   it replaced.
4. Let `shamway acceptance-provider` generate a `StagedClip`-shaped case
   (turntable or walk-cycle, per asset kind) instead of only a bare `Live`
   load, and let `shamway client capture` adopt the resulting clip directory
   the same way it already adopts a single external screenshot.
5. Make network use, credentials, provider, model, cost exposure, and asset
   disclosure explicit before submission, and preserve the same advisory,
   never-auto-accepting posture `0001` already establishes for audio.

## Non-goals

- **No automatic creative approval or mesh regeneration.** A model verdict
  cannot mark a video asset accepted, and cannot trigger a new
  `shamway generate mesh` call on its own. A person, or an agent acting on
  their behalf, reads the critique and decides the next generation call.
- **No replacement for `render-icon` or `client capture`.** The clay render
  stays the fast, editor-optional icon path; a single adopted frame stays
  valid evidence for a case that does not need motion. This adds a
  live-engine, multi-frame supplement, not a replacement for either.
- **No clip capture of its own.** Capturing a `StagedClip` is
  `7dtd-playtest`'s job (`CaseDef.StagedClip`); this project only adopts an
  already-captured clip directory, the same boundary `client capture`
  already draws between taking a screenshot and recording one somebody else
  took (`capture.py`'s `record_existing`).
- **No silent upload.** `build`, `validate`, `check-mesh`, and an ordinary
  `acceptance-provider` run stay entirely offline; nothing here triggers a
  network call implicitly.
- **No frame-only claim if the provider cannot actually receive motion.** A
  provider limited to a single still does not meet this capability.
- **No provider-specific result as the stable format**, and no change to
  `check-mesh`, `validate`, or `verify-bundle`; those gates run exactly as
  they do today, unaffected by anything in this PRD.

## Design

### Command and context

```bash
shamway review-video thing --clip .local/acceptance/thing/clip \
    --intent assets-src/bundle/thing.review.json \
    --provider PROVIDER --model MODEL --allow-network --json
```

`--clip` points at a directory already adopted by `shamway client capture
--clip` (Goal 4), so the frames/video, the observable, and the capture's own
hash are already on record; `review-video` reads that record rather than
re-deriving it. `thing` is the manifest stem, which is how generation
parameters (Design, "Evidence") get attached without the caller repeating
them.

The intent file, committed beside the authored source next to the mesh it
describes, mirrors `0001`'s intent schema with sight's own fields in place
of playback/spatial/mix context:

| Field | Meaning |
|---|---|
| `purpose` | What the clip is supposed to demonstrate |
| `camera_path` | `turntable`, `walk-cycle`, `fixed`, or a description |
| `desired_qualities` | Proportions, silhouette, material read, timing |
| `avoid` | Clipping, popping, wrong scale, z-fighting, jitter |
| `references` | Optional comparison assets, with their purpose stated |
| `questions` | Asset-specific concerns the reviewer must answer |

`--intent-text` may supply the same information interactively; the command
refuses an empty `purpose`, matching `0001`'s own refusal.

### Review rubric and result

Same result shape `0001` already specifies for audio: `summary`,
`strengths`, `issues` (each tied to a frame index or timestamp),
`recommended_changes`, `rubric_scores`, `confidence`, `limitations`. Sharing
the shape, not just the spirit, means a caller (or a future digest
summarizing many reviews) does not need to branch on whether a given
critique was of a sound or a mesh.

### Evidence and reproducibility

`--output PATH` (default beside the adopted clip) writes:

- SHA-256 of every submitted frame/clip file and the intent file;
- the reviewed asset's generation parameters: `shamway generate mesh`'s
  arguments (seed, shape, size) when the manifest entry's `bundle_source` is
  `synthesized`, or the source file's SHA-256 when it is `external`/`unity`,
  or an explicit "not recorded" when neither is known, never a guess;
- provider, model identifier, review timestamp;
- rubric and prompt versions;
- the structured result, and optionally the raw provider response;
- disclosure confirmation and usage metadata if reported;
- tool version and parameters, credentials removed.

A later review of a revised candidate never overwrites an earlier evidence
document; both remain, hash-addressed, exactly the comparability `0001`
already requires for repeated audio reviews.

### `acceptance-provider` motion kind

`acceptance.py`'s generated provider currently emits one `Live` case per
manifest entry (`generate` in `acceptance.py`, invoked by
`generate_acceptance_provider` in `api.py:31`). This PRD adds one optional
manifest field per mesh/prefab entry: a motion kind (`turntable` |
`walk-cycle` | `fixed`, default `turntable` for a bare mesh/prefab, `fixed`
for anything the manifest already knows is world-fixed). When present, the
generated case becomes a `CaseDef.StagedClip` call (7dtd-playtest's
primitive) instead of `CaseDef.Live`; when absent, generation is byte-for-
byte unchanged from today.

### `client capture --clip`

`capture.py` already has the shape this needs: `record_existing(file,
label, observable, root)` adopts a screenshot somebody else took rather than
taking its own. `--clip DIR` is the same operation one level up: adopt an
already-captured `7dtd-playtest` clip directory (frames, muxed video,
`client.log`) into `.local/acceptance/`, hashed and labeled the same way a
single adopted screenshot already is, so `review-video` has a stable,
recorded input to read.

### Provider boundary

A narrow adapter, in the same shape `0001` specifies for its audio provider:
capability probe (accepted formats, frame count/size limits), submission of
frames or video plus text, structured-response handling, usage metadata,
redaction. Credentials come only from provider configuration or environment
variables, never as a command argument, printed output, or stored evidence,
matching `0001` exactly. The capability registry reports `unavailable`,
`configured`, or `not probed` without contacting a provider during
`doctor`, `status`, schema listing, or an offline build.

### Gates

An **advisory semantic-review gate**, additive to the existing table `0001`
already establishes for audio:

| Evidence | What it proves |
|---|---|
| `check-mesh` | The source is mechanically healthy |
| `render-icon` | A clay render exists for the icon path |
| model video review | A named model critiqued the submitted clip under recorded context and generation parameters |
| `acceptance-provider` case | The game loaded/played the asset in the tested path |
| `client capture` + human look | A person accepted the experience in its actual game context |

Model review may block promotion only when a consuming project explicitly
configures that policy, and can never create human-acceptance evidence,
identical to `0001`'s own rule.

### Registries

Implementation adds:

- `review_video` to `operations.OPERATIONS` and `api._DISPATCH`;
- the video-review provider capability to `capabilities.REGISTRY`;
- `model-video-review` to `docs.TOPICS`;
- the motion-kind manifest field to `acceptance.py`'s generator;
- `--clip` to `capture.py`'s CLI surface;
- the command to the README command table and a new authoring page
  (`docs/authoring/video.md`, mirroring `docs/authoring/audio.md`).

It does not add a generator, a prompt kind, or a Unity editor script.

### Implementation

1. Define the versioned intent and result schemas in
   `src/sevendtd_asset_pipeline/video_review.py`, sharing the result schema
   module with `0001`'s audio result where the shapes are identical, with
   offline validation and credential-redaction tests.
2. Add `--clip` to `capture.py`, proving with a test that an adopted clip
   directory's frames are hashed and recorded without re-capturing anything.
3. Add a provider protocol and the first adapter under
   `src/sevendtd_asset_pipeline/providers/` (reusing `0001`'s provider
   protocol module if it has already landed), proving with a fake local
   adapter that actual frame/video bytes, not a path, reach the boundary.
4. Register the optional capability in `capabilities.REGISTRY` without a
   network request during discovery.
5. Add the motion-kind field to `acceptance.py`'s manifest handling and
   generated provider, with a fixture proving a `fixed`-kind entry still
   generates a plain `Live` case unchanged.
6. Add the `review_video` operation to `operations.OPERATIONS` and
   `api._DISPATCH`, then expose `shamway review-video` with explicit
   `--allow-network` consent.
7. Add fixtures for malformed intent, unsupported media, oversized payload,
   provider refusal, invalid structured output, timeout, missing generation
   parameters, and credential redaction.
8. Update `README.md`, `docs/authoring/video.md`, `docs/consumer-api.md`,
   and the packaged documentation mirror (via `setup.py`'s existing
   `build_py` hook, no change needed there) while implementing each surface.
9. Run reviews on a known-fit and a deliberately mismatched clip (an
   intentionally clipping garment, staged on purpose), then finish
   acceptance with a fresh client and a human look. Record where the
   model's critique helped, missed, or disagreed with the human, and record
   at least one instance where a critique's pattern is written down as a
   [research note](../research/README.md) or [digest](../digests/README.md)
   for future generation defaults.

## Failure modes

| Condition | Behaviour |
|---|---|
| `--allow-network` absent | Refuse before reading credentials or contacting a provider |
| intent lacks `purpose` | Refuse locally with the missing field |
| `--clip` points at a directory `client capture` never adopted | Refuse; review only ever runs against a recorded, hash-addressed capture |
| provider/model not configured | Report the capability state and configuration route |
| clip exceeds provider's frame/size limit | Sample down (even spacing, always first/last frame), record the sampling in evidence |
| provider cannot ingest actual frames/video | Refuse the adapter; a stills-incapable transcription is not a substitute |
| provider timeout/rate limit/refusal | Exit non-zero; preserve no partial verdict as a completed review |
| model returns invalid structure | Preserve a redacted raw response only when requested; fail validation |
| asset has no known generation parameters | Record the evidence with that field honestly empty, never guessed |
| usage/cost metadata unavailable | Mark unavailable rather than estimated |
| multiple reviews disagree | Preserve each result and surface disagreement |
| model says "looks right" | Record advisory wording only; never marks the asset accepted |
| human disagrees with the model | Human sign-off controls acceptance; disagreement retained as evaluation evidence |

## Acceptance criteria

- [ ] Goal 1: a fake adapter test proves the exact candidate frames/video and
  complete intent reach the provider boundary.
- [ ] Goal 1: at least one real video-capable provider reviews a non-trivial
  staged clip and identifies a motion-dependent property a single still
  could not show.
- [ ] Goal 2: output validates against the stable result schema shared with
  `0001`'s audio result shape.
- [ ] Goal 3: the evidence document names the reviewed candidate's exact
  generation parameters or source hash; rerunning against a revised
  candidate preserves both hash-addressed evidence documents.
- [ ] Goal 4: an `acceptance-provider` manifest entry with a motion-kind
  field generates a `StagedClip` case; one without it generates the same
  `Live` case as today, unchanged.
- [ ] Goal 4: `client capture --clip` adopts an externally captured clip
  directory into `.local/acceptance/`, hashed and labeled.
- [ ] Goal 5: no network call occurs without explicit consent, and
  credentials are absent from stdout, JSON results, logs, and evidence.
- [ ] Goal 5: schema/capability discovery works offline with no provider
  SDK or credentials installed.
- [ ] CLI, `shamway call`, `shamway serve`, schema, capability listing,
  `shamway docs`, and packaged/source documentation agree.
- [ ] Offline tests pass with fake adapters and no network.
- [ ] A fresh client stages and plays the reviewed candidate's clip in its
  intended path.
- [ ] A human watches the clip in game and records whether the model's
  critique matched the experienced motion; only that human review may
  accept the asset.

## Open questions

- Should the provider adapter and result-schema module be shared code with
  `0001`'s audio review (one `providers/` package, one result-schema base),
  or kept parallel until both have shipped once and the actual overlap is
  known?
- Does the motion-kind manifest field belong here (asset-owned) or should
  `7dtd-playtest` own the equivalent decision through its own suite
  configuration, given the two repositories intentionally share no schema
  today?
- Should `--clip` accept a raw frame directory when no muxed video exists
  (a host without `ffmpeg`), or require a muxed video, given provider
  capability for actual video ingestion varies?
- Which provider ships first, based on real video/multi-frame understanding,
  structured output, retention controls, cost, and SDK weight, and is it the
  same provider `0001` eventually chooses for audio?
