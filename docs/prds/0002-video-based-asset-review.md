# PRD — Video-based asset review

## Status

Implemented (2026-08-25). The command, operation, capability and gateway
boundary this page specified all shipped: `shamway review-video` (`cli.py`),
`review_video` in `operations.OPERATIONS` and `api._DISPATCH` (networked,
writes evidence), the `model-video-review` capability in
`capabilities.REGISTRY` (the deadeye CLI on PATH), `shamway client capture
--clip` (`capture.py`'s `record_existing_clip`, one level up from
`record_existing`), and the `[acceptance] motion_kinds` declaration that turns
a mesh/prefab's generated look case into a `CaseDef.StagedClip`.
`tests/test_video_review.py`, `tests/test_capture.py`'s `ClipAdoptionTests`,
and `tests/test_acceptance.py`'s `MotionKindTests` hold the contract together
offline.

The model I/O is delegated to the **deadeye** gateway
(`hordeforge/7dtd-vision-review`), a new sibling repository created to house
the component both this pipeline and `7dtd-playtest` call programmatically:
it forwards frames or a muxed clip plus intent to the vision model backend and
returns the structured feedback. The PRD's "provider adapter in
`providers/`" section below is implemented as that gateway; the open question
about where the adapter lives is thereby answered (a shared gateway, not a
second in-repo adapter). The gateway's own contract is documented there and
mirrored in this repository's `video_review.py`.

Two specified details changed during implementation, both recorded here so the
next reader is not confused:

- **The motion-kind declaration lives in `.shamway.toml`**
  (`[acceptance] motion_kinds = {"thing": "turntable"}`), not on the tracked
  manifest entry. The tracked manifest is regenerated on every `shamway
  build`, so an author-owned field there would be wiped; the configuration is
  the one per-mod file that survives rebuilds. This answers the PRD's open
  question about asset-owned vs playtest-owned declaration: it is
  asset-owned, in the mod's configuration.
- **The evidence's `asset` block names the source file's SHA-256**, because
  this pipeline does not yet record per-asset generation arguments (shape,
  size, seed) anywhere. `generation_parameters` is honestly `null` with a
  note, never guessed — the source hash is the comparable address between
  revisions until generation records its own parameters.

Still owed, and why the live boxes under Acceptance criteria stay unchecked:
the live-provider run is strictly opt-in (`GEMINI_API_KEY` for the deadeye
gateway's gemini provider) and has not been recorded here, and no fresh-client
human look has yet compared a model critique against an experienced motion.
Every criterion an offline run can prove is checked below, with its pinning
test named where one exists.

Companion to
[0001-contextual-model-audio-review.md](0001-contextual-model-audio-review.md),
mirroring its shape for sight instead of hearing, and to
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
in-engine, multi-frame staged clip capability (`CaseDef.StagedClip`, see its
[docs/INGAME_VIDEO_CAPTURE.md](https://github.com/hordeforge/7dtd-playtest/blob/main/docs/INGAME_VIDEO_CAPTURE.md))
and a vision-model review of the result
([docs/VIDEO_MODEL_FEEDBACK.md](https://github.com/hordeforge/7dtd-playtest/blob/main/docs/VIDEO_MODEL_FEEDBACK.md)).
That capability
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
- the reviewed asset's provenance: its bundle_source, the source file the
  stem resolves to in the tracked manifest, and that file's SHA-256 when it
  exists. Per-asset generation arguments (seed, shape, size) are not yet
  recorded anywhere in this pipeline, so `generation_parameters` is honestly
  `null` with a note naming the source hash as the comparable address —
  never a guess;
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
manifest entry plus, for each prefab, a `Staged` look case (`generate` in
`acceptance.py`, invoked by `generate_acceptance_provider` in `api.py`).
This PRD adds one optional declaration per mesh/prefab entry, in the mod's
`.shamway.toml`:

```toml
[acceptance]
motion_kinds = { thing = "turntable" }
```

A motion kind (`turntable` | `walk-cycle` | `fixed`) changes that entry's
generated look case: `turntable` stages the prefab in front of the camera
and rotates it one full turn over a `CaseDef.StagedClip` hold, so the
captured frames prove the silhouette from every side; `walk-cycle` generates
a `CaseDef.Live` case that equips the item on the player
(`Helpers.TryEquipItem`), records an on-demand clip
(`Helpers.BeginClip`/`EndClip`) while the player actually walks with stock
autorun (`Helpers.StartWalk`), then stops both — the motion is the game's own
animation, not a staged spin, and a walk-cycle declared on a non-wearable
asset fails the case rather than holding silently; `fixed` keeps today's
generation byte-for-byte — a world-fixed thing has no motion worth
capturing. The `Live`/`Staged` load case stays in every case: a clip is
motion evidence, not the load gate. When the field is absent, generation is
byte-for-byte unchanged from today. The declaration lives in the mod's
configuration rather than the tracked manifest because the manifest is
regenerated on every `shamway build`; see Status for the record of that
change.

### `client capture --clip`

`capture.py` already has the shape this needs: `record_existing(file,
label, observable, root)` adopts a screenshot somebody else took rather than
taking its own. `--clip DIR` is the same operation one level up: adopt an
already-captured `7dtd-playtest` clip directory (frames, muxed video,
`client.log`) into `.local/acceptance/`, hashed and labeled the same way a
single adopted screenshot already is, so `review-video` has a stable,
recorded input to read.

### Provider boundary

The model I/O runs through the **deadeye** gateway
(`hordeforge/7dtd-vision-review`), the shared vision-model review component
created with this PRD. The gateway owns the narrow adapter surface `0001`
specifies for its audio provider — capability probe (accepted formats, frame
count/size limits), submission of frames or video plus text,
structured-response handling, usage metadata, redaction — and this repository
calls it over the CLI subprocess boundary documented in the gateway's
`docs/integration.md`. Credentials come only from provider configuration or
environment variables, never as a command argument, printed output, or stored
evidence, matching `0001` exactly. The capability registry reports the
gateway CLI on PATH (`model-video-review`) without contacting a provider
during `doctor`, `status`, schema listing, or an offline build; the gateway's
own `deadeye doctor` reports provider configuration the same way.

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
- the `model-video-review` capability to `capabilities.REGISTRY`;
- `model-video-review` and `video` to `docs.TOPICS`;
- the `[acceptance] motion_kinds` declaration to `config.py` and `acceptance.py`'s
  generator (in the mod's `.shamway.toml`, not the regenerated manifest — see
  Status);
- `--clip` to `capture.py`'s CLI surface;
- the command to the README command table and a new authoring page
  (`docs/authoring/video.md`, mirroring `docs/authoring/audio.md`).

It does not add a generator, a prompt kind, a Unity editor script, or an
in-repo provider adapter (the gateway owns that surface).

### Implementation

1. Define the versioned intent and result schemas in
   `src/sevendtd_asset_pipeline/video_review.py`, sharing the result shape
   with `0001`'s audio result where the shapes are identical (issues may also
   carry `at_frame`), with offline validation and credential-redaction tests.
2. Add `--clip` to `capture.py` (`record_existing_clip`), proving with a test
   that an adopted clip directory's frames are hashed and recorded without
   re-capturing anything.
3. Call the deadeye gateway over a subprocess boundary (the provider
   boundary, per the gateway's `docs/integration.md`), proving with a stubbed
   gateway runner that the adopted clip and the complete intent reach the
   boundary and the envelope round-trips. The gateway's own fake-provider
   test proves the exact frame/video bytes reach its provider boundary.
4. Register the `model-video-review` capability in `capabilities.REGISTRY`
   without a network request during discovery.
5. Add the `[acceptance] motion_kinds` declaration to the config and
   `acceptance.py`'s generated provider, with a fixture proving a `fixed`-kind
   entry still generates today's cases byte-for-byte unchanged.
6. Add the `review_video` operation to `operations.OPERATIONS` and
   `api._DISPATCH`, then expose `shamway review-video` with explicit
   `--allow-network` consent.
7. Add fixtures for malformed intent, an unadopted clip directory, gateway
   absence and refusal, invalid structured output, missing generation
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

- [x] Goal 1: the gateway's fake-provider test proves the exact candidate
  frames/video and complete intent reach its provider boundary, and this
  repository's stubbed-runner tests prove the adopted clip and complete
  intent reach the gateway boundary (`test_the_gateway_receives_the_adopted_clip_and_intent`,
  plus the gateway's own suite).
- [ ] Goal 1: at least one real video-capable provider reviews a non-trivial
  staged clip and identifies a motion-dependent property a single still
  could not show. (Opt-in live run; not yet recorded.)
- [x] Goal 2: output validates against the stable result schema shared with
  `0001`'s audio result shape, with `at_frame` as the video addition
  (`ResultTests`).
- [x] Goal 3: the evidence document names the reviewed candidate's source
  file and its SHA-256 (generation arguments are not yet recorded, so the
  source hash is the comparable address, honestly labelled); rerunning
  against a revised candidate preserves both hash-addressed evidence
  documents (`test_evidence_names_the_source_hash_and_gateway_envelope`,
  `test_an_earlier_evidence_document_is_never_overwritten_by_default`,
  `test_two_reviews_of_one_candidate_are_both_preserved`).
- [x] Goal 4: a mesh/prefab declared with a `turntable` or `walk-cycle` motion
  kind generates a `CaseDef.StagedClip` case; one without a declaration, or
  with `fixed`, generates today's cases byte-for-byte unchanged
  (`MotionKindTests`).
- [x] Goal 4: `client capture --clip` adopts an externally captured clip
  directory into `.local/acceptance/`, hashed and labeled
  (`ClipAdoptionTests`).
- [x] Goal 5: no network call occurs without explicit consent, and
  credentials are absent from stdout, JSON results, logs, and evidence
  (`test_consent_is_demanded_before_the_gateway_is_even_consulted`,
  `test_evidence_names_the_source_hash_and_gateway_envelope`).
- [x] Goal 5: schema/capability discovery works offline with no gateway
  binary or credentials installed (`test_a_missing_gateway_is_refused_with_the_install_route`;
  `deadeye doctor` is offline by construction).
- [x] CLI, `shamway call`, `shamway serve`, schema, capability listing,
  `shamway docs`, and packaged/source documentation agree. (verified against
  the running tool on 2026-08-25; `OperationSurfaceTests` pins the registry
  side)
- [x] Offline tests pass with stubbed runners and no network. (`make check
  test`; the shader-writer and packaged-mirror failures are the pre-existing
  baseline, present on main)
- [ ] A fresh client stages and plays the reviewed candidate's clip in its
  intended path. (needs the playtest side and a live run)
- [ ] A human watches the clip in game and records whether the model's
  critique matched the experienced motion; only that human review may
  accept the asset.

## Open questions

- ~~Should the provider adapter and result-schema module be shared code with
  `0001`'s audio review, or kept parallel?~~ **Resolved**: the provider
  boundary is the shared deadeye gateway in its own repository, called over a
  subprocess; `0001`'s in-repo adapter stays as it shipped.
- ~~Does the motion-kind manifest field belong here or in `7dtd-playtest`'s
  suite configuration?~~ **Resolved**: asset-owned, in the mod's
  `.shamway.toml` under `[acceptance] motion_kinds` (the tracked manifest is
  regenerated every build and cannot hold author-owned state).
- Should `--clip` accept a raw frame directory when no muxed video exists (a
  host without `ffmpeg`), or require a muxed video, given provider
  capability for actual video ingestion varies? **Open**: adoption accepts
  either (the gateway samples frames when no muxed video fits); the playtest
  capture side decides whether a raw frame directory without any muxed video
  is acceptable evidence.
- Which provider ships first, based on real video/multi-frame understanding,
  structured output, retention controls, cost, and SDK weight, and is it the
  same provider `0001` eventually chooses for audio? **Open**: gemini ships
  first (same vendor as `0001`'s audio choice); other providers are an
  adapter in the gateway.
