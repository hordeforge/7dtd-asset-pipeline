# PRD — Contextual model audio review

## Status

Implemented (2026-08-25). The command, operation, capability and provider
package this page specified all shipped:
`shamway review-audio` (`cli.py`), `review_audio` in
`operations.OPERATIONS` and `api._DISPATCH` (networked, writes evidence),
the `model-audio-review` capability in `capabilities.REGISTRY`, and
`src/sevendtd_asset_pipeline/providers/` with Gemini as the first adapter
behind one resolve point — which answers the first open question below.
The design in this page is the contract the implementation follows; where
this page and the code could disagree, `tests/test_audio_review.py` holds them
together (intent and result validation, consent before credentials are
read, exact bytes at the provider boundary, evidence hashing and
no-overwrite, redaction).

Still owed, and why three boxes under Acceptance criteria stay unchecked:
the live-provider run is strictly opt-in
(`SHAMWAY_NETWORK_TESTS=gemini` + `GEMINI_API_KEY`) and has not been
recorded here, and no fresh-client human listen has yet compared a model
critique against an experienced sound. Every criterion an offline run can
prove is checked below, with its pinning test named where one exists.

## Problem

`shamway check-sound` catches measurable defects such as clipping, DC offset,
silence, and unsupported formats. Live acceptance proves that the game can
load and play a clip. Neither answers whether the sound fits its purpose. A
synthetic falling-whistle cue can pass every existing gate and still sound
harsh, comic, cheap, fatiguing, or unlike an object falling through air.

A model cannot assess that fit from the waveform alone. The same rising tone
may be appropriate for an interface warning and wrong for an entity-bound,
three-dimensional bomb cue. Review therefore needs the actual audio together
with intended use, playback behaviour, listener position, mix context, and
the qualities the author wants checked.

Audio-capable model APIs exist today. Google's official Gemini documentation
describes audio understanding from uploaded or inline audio, while OpenAI's
official audio documentation describes models and APIs that accept and
produce audio. Provider support and model identifiers change, so the pipeline
must discover configured capability rather than hard-code one vendor as the
product contract.

The operation is necessarily networked for hosted providers, may incur cost,
and sends an authored asset to a third party. It must never happen implicitly.
An adopting mod may have only the installed `shamway` package, with no checkout
of this repository, so the command, schema, rubric, and documentation must all
ship in the package.

Sources consulted 2026-08-24:

- [Google Gemini API: Audio understanding](https://ai.google.dev/gemini-api/docs/audio)
- [OpenAI API: Audio and speech](https://developers.openai.com/api/docs/guides/audio)

## Goals

1. Let an agent submit the actual audio bytes plus explicit intended-use
   context to a configured audio-capable model.
2. Return structured, actionable criticism whose evidence can be stored with
   the asset candidate and compared across revisions.
3. Make network use, credentials, provider, model, cost exposure, and asset
   disclosure explicit before submission.
4. Preserve the existing acceptance boundary: model review supplements but
   never replaces a fresh-client human listen.
5. Expose the operation through the same CLI, operation registry, schema, and
   installed documentation surfaces as the rest of `shamway`.

## Non-goals

- **No automatic creative approval.** A model verdict cannot mark an audio
  asset accepted or satisfy the human-listen gate.
- **No sound generation or mutation.** The operation critiques a candidate;
  generators and audio conversion remain separate authoring steps.
- **No transcription-only fallback.** Speech transcription does not audition
  timbre, pitch motion, loop seams, spatial plausibility, or mix fatigue.
- **No spectrogram-only claim.** Derived measurements may accompany the
  waveform, but a provider that cannot receive the audio itself does not meet
  this capability.
- **No silent upload.** Validation, builds, generators, and ordinary
  `check-sound` runs remain offline and never trigger review.
- **No provider-specific result as the stable format.** Vendor payloads may be
  retained as evidence, but callers consume a pipeline-owned schema.

## Design

### Command and context

The primary surface is:

```bash
shamway review-audio assets-src/audio/falling-whistle.wav \
    --intent assets-src/audio/falling-whistle.review.json \
    --provider PROVIDER --model MODEL --allow-network --json
```

The intent file is committed beside the authored source. It contains:

| Field | Meaning |
|---|---|
| `purpose` | What game event the clip represents |
| `playback` | One-shot or loop, expected duration, repeat rate, and pitch variation |
| `spatial_context` | 2D or 3D, entity-bound or world-fixed, distance and movement |
| `mix_context` | Ambience, simultaneous effects, expected loudness, and masking risks |
| `listener` | Where and when a player hears it |
| `desired_qualities` | Concrete target qualities and emotional reading |
| `avoid` | Failure qualities such as shrillness, comedy, artificiality, or fatigue |
| `references` | Optional licensed/local comparison clips with their purpose stated |
| `questions` | Asset-specific concerns the reviewer must answer |

`--intent-text` may supply the same information interactively, but the JSON
file is the reproducible route. The command refuses an empty purpose and
refuses to infer context from a filename.

Before upload, the command prints the resolved provider, model, file count,
total bytes, and retention/privacy warning. Submission requires
`--allow-network`; JSON/operation callers set the corresponding explicit
boolean. Credentials come only from provider configuration or environment
variables and are never accepted as command arguments, printed, or written
into evidence.

### Review rubric and result

The pipeline supplies a versioned rubric and asks the model for a structured
result. Every review covers:

- semantic fit for the stated event;
- timbre, pitch contour, dynamics, transient, tail, and perceived scale;
- harshness, artificiality, unintended comedy, repetition fatigue, and likely
  masking in the described mix;
- loop seam and repetition only when playback says they apply;
- spatial and motion plausibility for the described source;
- specific problems tied to audible moments or time ranges;
- actionable revision advice, confidence, and limitations.

The stable result contains `summary`, `strengths`, `issues`,
`recommended_changes`, `rubric_scores`, `confidence`, and `limitations`.
Scores are diagnostic, not pass/fail. An honest response may say that a
property cannot be judged without in-game spatialisation or mix playback.

### Evidence and reproducibility

`--output PATH` writes an evidence document containing:

- SHA-256 of every submitted audio/reference file and the intent file;
- provider, model identifier, endpoint mode, and review timestamp;
- rubric and prompt versions;
- normalized structured result and optionally the raw provider response;
- disclosure confirmation and whether the provider reported usage;
- tool version and operation parameters, with credentials removed.

The evidence makes a judgement traceable; it does not make the judgement
deterministic. A later review must not overwrite an earlier one by default.
Comparing providers or repeated reviews is allowed, and disagreement is
reported rather than averaged into false certainty.

### Provider boundary

Providers implement a narrow adapter: capability probe, supported audio
formats/size limits, submission of audio plus text, structured-response
handling, usage metadata, and redaction. The first implementation may support
one provider, but the operation and result schema remain provider-neutral.

The capability registry reports whether credentials and the optional client
dependency are present. It must distinguish `unavailable`, `configured`, and
`not probed`; it must not test credentials or contact a provider during
`doctor`, `status`, schema listing, or an offline build.

### Gates

This adds an **advisory semantic-review gate**. It does not weaken clip-format
checks, bundle verification, fresh-client loading, or the required human
listen. Reports must label these separately:

| Evidence | What it proves |
|---|---|
| `check-sound` | The source is mechanically healthy |
| model review | A named model critiqued the submitted bytes under recorded context |
| fresh-client case | The game loaded/played the asset in the tested path |
| human listen | A person accepted the experience in its actual game context |

Model review may block promotion only when a consuming project explicitly
configures that policy. It can never create human-acceptance evidence.

### Registries

Implementation adds:

- `review_audio` to `operations.OPERATIONS` and `api._DISPATCH`;
- the audio-review provider capability to `capabilities.REGISTRY`;
- `model-audio-review` to `docs.TOPICS`;
- the command to the README command table and audio authoring page.

It does not add a generator, prompt kind, host script, or Unity editor script.

### Implementation

1. Define the versioned intent and result schemas in
   `src/sevendtd_asset_pipeline/audio_review.py`, with offline validation and
   credential redaction tests.
2. Add a provider protocol and the first adapter under
   `src/sevendtd_asset_pipeline/providers/`; prove with a fake local adapter
   that actual audio bytes, not a path or transcript, reach the boundary.
3. Register the optional capability in `capabilities.REGISTRY` without making
   any network request during discovery.
4. Add the `review_audio` operation to `operations.OPERATIONS` and
   `api._DISPATCH`, then expose `shamway review-audio` with explicit
   `--allow-network` consent.
5. Add fixtures for malformed intent, unsupported media, oversized payload,
   provider refusal, invalid structured output, timeout, and credential
   redaction. Network tests remain opt-in and never run in the offline suite.
6. Update `README.md`, `docs/authoring/audio.md`, `docs/consumer-api.md`, and
   the packaged documentation mirror while implementing each surface.
7. Run model reviews on generated known-fit and deliberately mismatched clips,
   then finish acceptance with fresh-client human listening. Record where
   model feedback helped, failed, or disagreed with the listener.

## Failure modes

| Condition | Behaviour |
|---|---|
| `--allow-network` absent | Refuse before reading credentials or contacting a provider |
| intent lacks purpose or playback context | Refuse locally with the missing fields |
| provider/model not configured | Report the capability state and configuration route |
| unsupported format or payload too large | Refuse locally when provider limits are known |
| provider timeout/rate limit/refusal | Exit non-zero; preserve no partial verdict as a completed review |
| model returns invalid structure | Preserve a redacted raw response only when requested; fail validation |
| provider cannot consume actual audio | Refuse the adapter; transcription is not a substitute |
| usage/cost metadata unavailable | Mark it unavailable rather than estimating it |
| multiple reviews disagree | Preserve each result and surface disagreement |
| model says “pass” | Record advisory wording only; do not mark the asset accepted |
| human disagrees with the model | Human sign-off controls acceptance; retain disagreement as evaluation evidence |

## Acceptance criteria

- [x] Goal 1: a fake adapter test proves the exact candidate bytes and complete
  intent reach the provider boundary.
  (`test_the_exact_candidate_bytes_reach_the_boundary`,
  `test_the_complete_intent_reaches_the_boundary`)
- [ ] Goal 1: at least one real audio-capable provider reviews a non-speech
  generated sound and identifies audible properties beyond transcription.
- [x] Goal 2: output validates against the stable schema and names actionable
  observations with timestamps/time ranges where applicable.
  (`validate_result` refuses every deviation; `test_a_valid_result_normalizes`)
- [x] Goal 2: rerunning against a revised candidate preserves both hash-addressed
  evidence documents for comparison. Pinned by
  `test_an_earlier_evidence_document_is_never_overwritten_by_default`,
  `test_two_reviews_of_one_candidate_are_both_preserved`, and the evidence
  sha256 in `test_evidence_is_written_and_hashes_address_it`.
- [x] Goal 3: no network call occurs without explicit consent, and credentials
  are absent from stdout, JSON results, logs, and stored evidence. Pinned by
  `test_consent_is_demanded_before_credentials_are_even_read`, the redaction
  tests, and the usage backstop that keeps vendor payload out of both report
  and evidence.
- [x] Goal 3: schema/capability discovery works offline with no provider SDK or
  credentials installed. The probe reads environment presence only, held there
  by `test_the_model_review_capability_never_probes_a_provider`.
- [x] Goal 4: documentation and result wording state that model review is
  advisory and cannot satisfy human acceptance. (`ADVISORY_NOTE` rides every
  result; README, audio authoring page and this PRD say it in prose)
- [x] Goal 5: CLI, `shamway call`, `shamway serve`, schema, capability listing,
  `shamway docs`, and packaged/source documentation agree. (verified against
  the running tool on 2026-08-25; `OperationSurfaceTests` pins the registry
  side)
- [x] Offline tests pass with fake adapters and no network. (`make check test`;
  the one skipped case in `test_audio_review.py` is the opt-in live-provider run)
- [ ] A fresh client plays the reviewed candidate in its intended event path.
- [ ] A human listens in game and records whether the model's critique matched
  the experienced sound; only that human review may accept the asset.

## Open questions

- Which provider adapter should ship first, based on non-speech audio
  understanding, structured output, retention controls, cost, and SDK weight?
- Should raw provider responses be retained by default, opt-in, or never, given
  their debugging value and possible sensitive metadata?
- Should the versioned default rubric live as package data or Python data, and
  how should consuming mods extend it without making results incomparable?
- Which consuming-project policy, if any, may require advisory review before
  promotion while still making human sign-off the final authority?
