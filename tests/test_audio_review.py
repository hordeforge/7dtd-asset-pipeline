"""The model-audio-review lane, entirely offline.

Every networked behaviour is exercised through the fake adapter or a stubbed
transport; the real provider is reachable only behind an opt-in environment
variable, so the offline suite never spends money and never sends bytes.
"""

from __future__ import annotations

import array
import contextlib
import hashlib
import io
import json
import math
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any
from unittest import mock

from sevendtd_asset_pipeline import OPERATIONS, PipelineError
from sevendtd_asset_pipeline.api import call_json
from sevendtd_asset_pipeline.audio_review import (
    BASE_RUBRIC,
    INTENT_SCHEMA_VERSION,
    LOOP_RUBRIC,
    RESULT_KEYS,
    build_prompt,
    parse_intent,
    parse_intent_text,
    redact,
    rubric_for,
    run_review,
    validate_result,
)
from sevendtd_asset_pipeline.cli import main
from sevendtd_asset_pipeline.providers import (
    PROVIDERS,
    configuration_state,
    resolve_provider,
)
from sevendtd_asset_pipeline.providers.base import ReviewRequest, ReviewResponse
from sevendtd_asset_pipeline.providers.fake import FakeProvider

VALID_INTENT: dict[str, Any] = {
    "schema_version": INTENT_SCHEMA_VERSION,
    "purpose": "a time bomb falling after being thrown off a roof",
    "playback": {
        "mode": "one-shot",
        "expected_duration_seconds": 4,
        "pitch_variation": "slight random detune per play",
    },
    "spatial_context": "3D, entity-bound, heard from 5-30 m",
    "mix_context": "outdoor ambience, occasional gunfire",
    "listener": "the thrower, then anyone near the impact",
    "desired_qualities": "reads as mass descending through air",
    "avoid": ["slide-whistle comedy", "shrillness"],
    "questions": ["is the descent speed audible?"],
}


def write_clip(path: Path, seconds: float = 0.5, rate: int = 44100) -> Path:
    count = int(seconds * rate)
    samples = array.array("h")
    for index in range(count):
        samples.append(int(0.5 * math.sin(2 * math.pi * 220 * index / rate) * 32767))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return path


class IntentTests(unittest.TestCase):
    def test_a_valid_intent_parses_with_every_field(self) -> None:
        intent = parse_intent(dict(VALID_INTENT), "test")
        self.assertIn("bomb", intent.purpose)
        self.assertEqual("one-shot", intent.playback_mode)
        self.assertEqual(4.0, intent.expected_duration_seconds)
        self.assertEqual(("slide-whistle comedy", "shrillness"), intent.avoid)
        self.assertEqual(1, len(intent.questions))

    def test_missing_purpose_and_playback_are_refused_together(self) -> None:
        with self.assertRaisesRegex(PipelineError, "purpose"):
            parse_intent({}, "test")

    def test_an_empty_purpose_is_refused_not_inferred(self) -> None:
        data = dict(VALID_INTENT, purpose="   ")
        with self.assertRaisesRegex(PipelineError, "never inferred"):
            parse_intent(data, "test")

    def test_unknown_fields_are_named_as_likely_typos(self) -> None:
        data = dict(VALID_INTENT, spacial_context="x")
        with self.assertRaisesRegex(PipelineError, "spacial_context"):
            parse_intent(data, "test")

    def test_playback_mode_is_constrained(self) -> None:
        data = {**VALID_INTENT, "playback": {"mode": "occasional"}}
        with self.assertRaisesRegex(PipelineError, "one-shot"):
            parse_intent(data, "test")

    def test_a_wrong_schema_version_is_refused_not_coerced(self) -> None:
        with self.assertRaisesRegex(PipelineError, "schema_version"):
            parse_intent({**VALID_INTENT, "schema_version": 99}, "test")

    def test_references_require_a_stated_purpose(self) -> None:
        data = {**VALID_INTENT, "references": [{"path": "ref.wav"}]}
        with self.assertRaisesRegex(PipelineError, "purpose"):
            parse_intent(data, "test")

    def test_inline_text_round_trips_through_the_same_validator(self) -> None:
        intent, raw = parse_intent_text(json.dumps(VALID_INTENT))
        self.assertEqual(VALID_INTENT["purpose"], intent.purpose)
        self.assertTrue(raw.startswith(b"{"))


class RubricTests(unittest.TestCase):
    def test_loop_scoring_applies_only_when_playback_loops(self) -> None:
        one_shot = parse_intent(VALID_INTENT, "test")
        looping = parse_intent({**VALID_INTENT, "playback": {"mode": "loop"}}, "test")
        self.assertNotIn("loop_seam_risk", {item.key for item in rubric_for(one_shot)})
        self.assertIn("loop_seam_risk", {item.key for item in rubric_for(looping)})

    def test_the_prompt_carries_the_complete_intent(self) -> None:
        data = {
            **VALID_INTENT,
            "references": [{"path": "ref.wav", "purpose": "the vanilla cue"}],
        }
        intent = parse_intent(data, "test")
        prompt = build_prompt(intent, rubric_for(intent))
        for fragment in (
            intent.purpose,
            intent.spatial_context,
            intent.mix_context,
            VALID_INTENT["avoid"][0],
            VALID_INTENT["questions"][0],
            "semantic_fit",
            "the vanilla cue",
        ):
            self.assertIn(fragment, prompt)


class ResultTests(unittest.TestCase):
    def _valid_result(self) -> dict[str, Any]:
        return {
            "summary": "Reads as a descending object.",
            "strengths": ["clean tail"],
            "issues": [
                {"description": "shrill at the start", "at_seconds": [0.2, 0.8]},
                {"description": "loop seam click"},
            ],
            "recommended_changes": ["low-pass the first second"],
            "rubric_scores": {"semantic_fit": 4, "harshness_risk": None},
            "confidence": 0.7,
            "limitations": ["no in-game spatialisation"],
        }

    def test_a_valid_result_normalizes(self) -> None:
        result = validate_result(self._valid_result(), BASE_RUBRIC + LOOP_RUBRIC)
        self.assertEqual(set(result), set(RESULT_KEYS))
        self.assertEqual([0.2, 0.8], result["issues"][0]["at_seconds"])
        self.assertIsNone(result["rubric_scores"]["harshness_risk"])

    def test_missing_and_unknown_keys_fail(self) -> None:
        with self.assertRaisesRegex(PipelineError, "missing key"):
            validate_result({"summary": "x"}, BASE_RUBRIC + LOOP_RUBRIC)
        bloated = self._valid_result()
        bloated["verdict"] = "pass"
        with self.assertRaisesRegex(PipelineError, "unexpected key"):
            validate_result(bloated, BASE_RUBRIC + LOOP_RUBRIC)

    def test_unknown_rubric_dimensions_fail(self) -> None:
        broken = self._valid_result()
        broken["rubric_scores"]["vibes"] = 3
        with self.assertRaisesRegex(PipelineError, "vibes"):
            validate_result(broken, BASE_RUBRIC + LOOP_RUBRIC)

    def test_out_of_range_scores_and_confidence_fail(self) -> None:
        broken = self._valid_result()
        broken["rubric_scores"]["semantic_fit"] = 9
        with self.assertRaisesRegex(PipelineError, "within 0-5"):
            validate_result(broken, BASE_RUBRIC + LOOP_RUBRIC)
        broken = self._valid_result()
        broken["confidence"] = 1.5
        with self.assertRaisesRegex(PipelineError, "confidence"):
            validate_result(broken, BASE_RUBRIC + LOOP_RUBRIC)

    def test_malformed_at_seconds_fails(self) -> None:
        broken = self._valid_result()
        broken["issues"][0]["at_seconds"] = [1.0, 0.0]
        with self.assertRaisesRegex(PipelineError, "at_seconds"):
            validate_result(broken, BASE_RUBRIC + LOOP_RUBRIC)

    def test_fenced_json_is_extracted_from_a_model_response(self) -> None:
        from sevendtd_asset_pipeline.audio_review import parse_model_json

        fenced = "```json\n" + json.dumps(self._valid_result()) + "\n```"
        parsed = parse_model_json(fenced)
        self.assertIn("summary", parsed)


class RedactionTests(unittest.TestCase):
    def test_credential_shaped_keys_never_survive(self) -> None:
        nested = {
            "provider": "gemini",
            "api_key": "AIzA-secret",
            "GEMINI_API_KEY": "also-secret",
            "request": {"Authorization": "Bearer x", "model": "gemini-2.5-flash"},
        }
        cleaned = redact(nested)
        flattened = json.dumps(cleaned)
        for secret in ("AIzA-secret", "also-secret", "Bearer x"):
            self.assertNotIn(secret, flattened)
        self.assertEqual("gemini", cleaned["provider"])
        self.assertEqual("gemini-2.5-flash", cleaned["request"]["model"])

    def test_a_bare_key_attribute_is_dropped(self) -> None:
        self.assertNotIn("key", redact({"key": "value", "name": "keep"}))


class StubResponse:
    """A stand-in for what `provider.review` returns."""

    def __init__(self, raw_text: str) -> None:
        self.raw_text = raw_text
        self.usage = None
        self.model_reported = None


class RunReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.clip = write_clip(self.root / "falling.wav")
        self.intent_file = self.root / "falling.review.json"
        self.intent_file.write_text(json.dumps(VALID_INTENT), encoding="utf-8")
        self.provider = FakeProvider()

    def _run(self, **overrides: object) -> dict[str, Any]:
        parameters: dict[str, object] = {
            "clip": self.clip,
            "provider": self.provider,
            "intent_path": self.intent_file,
            "allow_network": True,
        }
        parameters.update(overrides)
        return run_review(**parameters)  # type: ignore[arg-type]

    def test_consent_is_demanded_before_credentials_are_even_read(self) -> None:
        def explode() -> bool:
            raise AssertionError("credentials were read before consent")

        with (
            mock.patch.object(FakeProvider, "is_configured", staticmethod(explode)),
            self.assertRaisesRegex(PipelineError, "allow.network"),
        ):
            self._run(allow_network=False)

    def test_the_exact_candidate_bytes_reach_the_boundary(self) -> None:
        self._run()
        request = self.provider.requests[0]
        submitted = request.audios[0]
        self.assertEqual(1, len(request.audios))
        self.assertEqual(
            hashlib.sha256(self.clip.read_bytes()).hexdigest(),
            hashlib.sha256(submitted.data).hexdigest(),
            "the adapter must receive the file's exact bytes, not a path or transcript",
        )

    def test_the_complete_intent_reaches_the_boundary(self) -> None:
        self._run()
        prompt = self.provider.requests[0].prompt
        for fragment in (VALID_INTENT["purpose"], VALID_INTENT["questions"][0], "one-shot"):
            self.assertIn(fragment, prompt)

    def test_reference_clips_travel_with_their_purpose(self) -> None:
        reference = write_clip(self.root / "vanilla-ref.wav")
        data = {
            **VALID_INTENT,
            "references": [{"path": str(reference), "purpose": "the vanilla cue"}],
        }
        self.intent_file.write_text(json.dumps(data), encoding="utf-8")
        self._run()
        request = self.provider.requests[0]
        self.assertEqual(2, len(request.audios))
        self.assertIn("the vanilla cue", request.prompt)

    def test_unsupported_format_is_refused_locally(self) -> None:
        text = self.root / "notes.txt"
        text.write_text("not audio", encoding="utf-8")
        with self.assertRaisesRegex(PipelineError, "not a format provider"):
            self._run(clip=text)

    def test_an_oversized_payload_is_refused_before_any_upload(self) -> None:
        big = self.root / "big.wav"
        budget = self.provider.limits.max_bytes
        assert budget is not None
        big.write_bytes(b"\x00" * (budget + 1))
        with self.assertRaisesRegex(PipelineError, "accepts at most"):
            self._run(clip=big)

    def test_evidence_is_written_and_hashes_address_it(self) -> None:
        output = self.root / "evidence" / "review.json"
        report = self._run(output=output)
        document = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(document["result"], report["review"])
        self.assertTrue(document["disclosure"]["network_consent"])
        self.assertEqual(
            hashlib.sha256(self.clip.read_bytes()).hexdigest(),
            document["clip"]["sha256"],
        )
        self.assertEqual(
            report["evidence"]["sha256"],
            hashlib.sha256(output.read_bytes()).hexdigest(),
        )
        # Credentials have no route into the evidence even if a caller tried.
        self.assertNotIn("GEMINI_API_KEY", output.read_text(encoding="utf-8"))

    def test_an_earlier_evidence_document_is_never_overwritten_by_default(self) -> None:
        output = self.root / "review.json"
        self._run(output=output)
        first = output.read_bytes()
        with self.assertRaisesRegex(PipelineError, "already holds an earlier review"):
            self._run(output=output)
        self.assertEqual(first, output.read_bytes())

    def test_two_reviews_of_one_candidate_are_both_preserved(self) -> None:
        first = self.root / "a.json"
        second = self.root / "b.json"
        self._run(output=first)
        self._run(output=second)
        self.assertTrue(first.stat().st_size > 0)
        self.assertTrue(second.stat().st_size > 0)

    def test_usage_unavailability_is_reported_not_estimated(self) -> None:
        report = self._run()
        self.assertFalse(report["usage"]["reported_by_provider"])

    def test_invalid_structure_preserves_redacted_raw_only_when_requested(self) -> None:
        def broken(_self: FakeProvider, _request: object) -> StubResponse:
            return StubResponse('{"summary": 3}')

        output = self.root / "failed.json"
        with (
            mock.patch.object(FakeProvider, "review", broken),
            self.assertRaisesRegex(PipelineError, "invalid structure"),
        ):
            self._run(output=output)
        self.assertFalse(output.exists(), "raw responses are opt-in")

        def raw_only(_self: FakeProvider, _request: object) -> StubResponse:
            return StubResponse("nope")

        with (
            mock.patch.object(FakeProvider, "review", raw_only),
            self.assertRaisesRegex(PipelineError, "preserved at"),
        ):
            self._run(output=output, keep_raw_response=True)
        document = json.loads(output.read_text(encoding="utf-8"))
        self.assertIsNone(document["result"])
        self.assertEqual("nope", document["raw_provider_response"])

    def test_provider_timeout_produces_no_partial_verdict(self) -> None:
        def slow(_self: FakeProvider, _request: object) -> object:
            raise TimeoutError("socket timed out")

        with (
            mock.patch.object(FakeProvider, "review", slow),
            self.assertRaisesRegex(PipelineError, "did not answer"),
        ):
            self._run()

    def test_provider_refusal_produces_no_partial_verdict(self) -> None:
        def refusing(_self: FakeProvider, _request: object) -> object:
            raise PipelineError("provider 'fake' refused the review (HTTP 403)")

        with (
            mock.patch.object(FakeProvider, "review", refusing),
            self.assertRaisesRegex(PipelineError, "refused"),
        ):
            self._run()

    def test_intent_exclusivity_is_enforced(self) -> None:
        with self.assertRaisesRegex(PipelineError, "exactly one"):
            self._run(intent_path=None, intent_text=None)

    def test_disclosure_is_issued_before_submission(self) -> None:
        sequence: list[str] = []
        original = FakeProvider.review

        def recording(provider: FakeProvider, request: ReviewRequest) -> ReviewResponse:
            sequence.append("submit")
            return original(provider, request)

        with mock.patch.object(FakeProvider, "review", recording):
            self._run(notify=sequence.append)
        joined = "\n".join(sequence)
        self.assertIn("provider: fake", joined)
        self.assertIn("model:", joined)
        self.assertIn("bytes", joined)
        self.assertIn("retention", joined)
        self.assertLess(
            next(index for index, item in enumerate(sequence) if item.startswith("uploading")),
            sequence.index("submit"),
            "the disclosure must be printed before anything is submitted",
        )


class ProviderRegistryTests(unittest.TestCase):
    def test_every_registered_provider_resolves(self) -> None:
        for name in PROVIDERS:
            provider = resolve_provider(name)
            self.assertEqual(name, provider.name)

    def test_unknown_names_name_the_known_ones(self) -> None:
        with self.assertRaisesRegex(PipelineError, "gemini"):
            resolve_provider("gpt-audio")

    def test_configuration_state_reports_offline_presence_only(self) -> None:
        state = configuration_state()
        # Credential-bearing providers only; the fake is deliberately absent.
        self.assertEqual({"gemini"}, set(state))
        self.assertLessEqual(set(state.values()), {"configured", "unavailable"})

    def test_gemini_reads_only_its_documented_environment_variables(self) -> None:
        gemini = resolve_provider("gemini")
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}, clear=True):
            self.assertTrue(gemini.is_configured())
        with mock.patch.dict("os.environ", {"GOOGLE_API_KEY": "k"}, clear=True):
            self.assertTrue(gemini.is_configured())
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(gemini.is_configured())


class OperationSurfaceTests(unittest.TestCase):
    """The published contract must agree with the implementation."""

    def test_the_operation_is_registered_with_explicit_network_cost(self) -> None:
        operation = OPERATIONS["review_audio"]
        self.assertTrue(operation.needs_network)
        self.assertIn("model-audio-review", operation.capabilities)
        self.assertIn("advisory", operation.summary.lower())
        self.assertEqual(
            sorted(PROVIDERS),
            operation.parameters["properties"]["provider"]["enum"],
        )

    def test_call_dispatch_runs_end_to_end_over_the_fake_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clip = write_clip(Path(directory) / "falling.wav")
            intent = Path(directory) / "falling.review.json"
            intent.write_text(json.dumps(VALID_INTENT), encoding="utf-8")
            with (
                mock.patch(
                    "sevendtd_asset_pipeline.capabilities._availability",
                    return_value={"model-audio-review": True},
                ),
                mock.patch(
                    "sevendtd_asset_pipeline.api.resolve_provider",
                    return_value=FakeProvider(),
                ),
            ):
                report = call_json(
                    None,
                    "review_audio",
                    {
                        "clip": clip,
                        "intent": str(intent),
                        "provider": "fake",
                        "allow_network": True,
                    },
                )
        self.assertTrue(report["advisory_only"])
        self.assertIn("summary", report["review"])

    def test_cli_requires_explicit_consent_and_prints_one_error_line(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            clip = write_clip(Path(directory) / "c.wav")
            with contextlib.redirect_stderr(stderr):
                code = main(["review-audio", str(clip)])
        self.assertEqual(1, code)
        lines = stderr.getvalue().splitlines()
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0].startswith("ERROR: "), lines)

    def _run_cli_review(self, *extra: str) -> tuple[int, str]:
        """Run `review-audio` over the fake provider with consent, capture stdout."""
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clip = write_clip(root / "falling.wav")
            intent = root / "falling.review.json"
            intent.write_text(json.dumps(VALID_INTENT), encoding="utf-8")
            with (
                mock.patch(
                    "sevendtd_asset_pipeline.capabilities._availability",
                    return_value={"model-audio-review": True},
                ),
                mock.patch(
                    "sevendtd_asset_pipeline.cli.resolve_provider",
                    return_value=FakeProvider(),
                ),
                contextlib.redirect_stdout(stdout),
            ):
                code = main(
                    [
                        "review-audio",
                        str(clip),
                        "--intent",
                        str(intent),
                        "--provider",
                        "fake",
                        "--allow-network",
                        *extra,
                    ]
                )
        return code, stdout.getvalue()

    def test_cli_completes_over_the_fake_provider_with_consent(self) -> None:
        code, text = self._run_cli_review("--json")
        self.assertEqual(0, code)
        report = json.loads(text[text.index("{") :])
        self.assertEqual("fake", report["provider"])
        self.assertTrue(report["advisory_only"])

    def test_cli_text_output_survives_an_unjudgeable_score(self) -> None:
        """The fake provider scores nothing, so the human-readable lane hits nulls.

        A regression once formatted the 'unjudgeable' placeholder with a number
        format spec and crashed after a paid submission had already completed;
        this pins the whole non-JSON path, disclosure through advisory note.
        """
        code, text = self._run_cli_review()
        self.assertEqual(0, code)
        lines = text.splitlines()
        self.assertIn("score: semantic_fit = unjudgeable", lines)
        self.assertTrue(any(line.startswith("summary: ") for line in lines))
        self.assertTrue(any(line.startswith("warning: ") for line in lines))
        self.assertTrue(any(line.startswith("note: Advisory only") for line in lines))


class NetworkOptInTests(unittest.TestCase):
    """Real-provider checks cost money and leave the host: strictly opt-in.

    Run with SHAMWAY_NETWORK_TESTS=gemini plus GEMINI_API_KEY set; never part
    of the offline suite.
    """

    def test_real_gemini_reviews_a_non_speech_generated_sound(self) -> None:
        import os

        if os.environ.get("SHAMWAY_NETWORK_TESTS") != "gemini":
            self.skipTest("opt-in: set SHAMWAY_NETWORK_TESTS=gemini and GEMINI_API_KEY")
        provider = resolve_provider("gemini")
        with tempfile.TemporaryDirectory() as directory:
            clip = write_clip(Path(directory) / "whistle.wav")
            report = run_review(
                clip,
                provider=provider,
                intent_text=json.dumps(VALID_INTENT),
                allow_network=True,
            )
        self.assertTrue(report["review"]["summary"])


if __name__ == "__main__":
    unittest.main()
