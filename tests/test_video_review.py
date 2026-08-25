"""The model-video-review lane, entirely offline.

Every networked behaviour is exercised through a stubbed gateway runner; the
real provider is reachable only through the deadeye gateway with an opt-in
credential, so the offline suite never spends money and never sends bytes.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from sevendtd_asset_pipeline import PipelineError, video_review
from sevendtd_asset_pipeline.capture import record_existing_clip
from sevendtd_asset_pipeline.config import load_config, render_config
from sevendtd_asset_pipeline.video_review import (
    INTENT_SCHEMA_VERSION,
    parse_intent,
    parse_intent_text,
    run_review,
    validate_result,
)

VALID_INTENT: dict[str, object] = {
    "schema_version": INTENT_SCHEMA_VERSION,
    "purpose": "show the garment survives a full turn without clipping",
    "subject": "thing (worn garment)",
    "camera_path": "turntable",
    "desired_qualities": "proportions read right from every side",
    "avoid": ["clipping", "popping"],
    "questions": ["does the grip read thin through the turn?"],
    "suite": "demo",
    "case": "thing",
}


def _valid_result() -> dict[str, Any]:
    """The result block of the fake envelope, as a mutable copy."""
    return dict(cast("dict[str, Any]", _gateway_envelope()["result"]))


def _gateway_envelope(frames: int = 8) -> dict[str, object]:
    """A valid deadeye envelope, as the gateway's fake runner would return."""
    return {
        "kind": "deadeye-review",
        "schema_version": 1,
        "tool_version": "0.1.0",
        "created_utc": "2026-08-25T00:00:00+00:00",
        "review_id": "test-review",
        "advisory_only": True,
        "note": "Advisory only",
        "intent": {"sha256": "0" * 64, "schema_version": 1, "content": dict(VALID_INTENT)},
        "media": [
            {
                "path": f"clip/frame-{index:04d}.png",
                "sha256": "0" * 64,
                "bytes": 4,
                "mime_type": "image/png",
                "kind": "frame",
            }
            for index in range(frames)
        ],
        "sampling": {
            "frames_available": 10,
            "frames_submitted": frames,
            "sampled": frames < 10,
            "note": "sampled 10 frames down to 8 (even spacing, first and last kept)",
        },
        "provider": {
            "name": "fake",
            "endpoint_mode": "in-process-fake",
            "model_requested": "deadeye-fake-vision-v1",
            "model_reported": "deadeye-fake-vision-v1",
        },
        "rubric_version": "1",
        "prompt_version": "1",
        "prompt": "You are reviewing a game-asset candidate on screen.",
        "result": {
            "summary": "reads well in motion",
            "strengths": ["silhouette holds through the turn"],
            "issues": [
                {
                    "description": "clips at the shoulder",
                    "at_seconds": [2.0, 3.0],
                    "at_frame": [8, 12],
                }
            ],
            "recommended_changes": ["taper the shoulder seam"],
            "rubric_scores": {"semantic_fit": 4, "clipping_risk": 2},
            "confidence": 0.8,
            "limitations": ["lighting without the engine"],
        },
        "error": None,
        "raw_provider_response": None,
        "usage": {"totalTokenCount": 10},
        "disclosure": {
            "network_consent": True,
            "third_party": "fake",
            "file_count": frames,
            "total_bytes": frames * 4,
        },
        "parameters": {},
    }


class _FakeGateway:
    """Records the argv it was given and answers with a valid envelope."""

    def __init__(self, envelope: dict[str, object] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.envelope = envelope or _gateway_envelope()

    def __call__(self, argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(self.envelope), stderr="")


class _ReviewHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.capture_root = self.root / ".local" / "acceptance"
        self._write_mod()
        self._adopt_clip()
        self.intent_file = self.root / "thing.review.json"
        self.intent_file.write_text(json.dumps(VALID_INTENT), encoding="utf-8")
        self.gateway = _FakeGateway()
        # The gateway binary is not on the CI host; the harness tests the
        # orchestration, so availability is stubbed true except where a test
        # specifically checks the refusal.
        patcher = mock.patch.object(video_review, "deadeye_available", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_mod(self) -> None:
        (self.root / "Config").mkdir(parents=True, exist_ok=True)
        (self.root / "Resources").mkdir(parents=True, exist_ok=True)
        (self.root / "tools/shamway/manifests").mkdir(parents=True, exist_ok=True)
        (self.root / "ModInfo.xml").write_text(
            '<?xml version="1.0"?><xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )
        (self.root / ".shamway.toml").write_text(
            render_config(
                mod_name="ExampleMod",
                bundle_name="examplemod.unity3d",
                unity_version="2022.3.62f2",
                bundle_source="synthesized",
            ),
            encoding="utf-8",
        )
        source = self.root / "assets-src" / "bundle"
        source.mkdir(parents=True, exist_ok=True)
        (source / "thing.glb").write_bytes(b"mesh-bytes")
        self.config = load_config(self.root / ".shamway.toml")

    def _adopt_clip(self) -> Path:
        captured = self.root / ".local" / "capture" / "demo-20260825" / "thing"
        captured.mkdir(parents=True, exist_ok=True)
        for index in range(10):
            (captured / f"frame-{index:04d}.png").write_bytes(bytes([index, 0, 0, 0]))
        (captured / "client.log").write_text("clip complete demo/thing frames=10\n")
        record_existing_clip(
            captured,
            "thing",
            "grip reads at the right thickness through a full turn",
            self.capture_root,
        )
        return self.capture_root / "thing"

    def _run(self, **overrides: object) -> dict[str, Any]:
        parameters: dict[str, object] = {
            "stem": "thing",
            "clip": self.capture_root / "thing",
            "provider": "fake",
            "intent_path": self.intent_file,
            "config": self.config,
            "capture_root": self.capture_root,
            "allow_network": True,
            "runner": self.gateway,
        }
        parameters.update(overrides)
        return run_review(**parameters)  # type: ignore[arg-type]


class IntentTests(unittest.TestCase):
    def test_a_valid_intent_parses(self) -> None:
        intent = parse_intent(dict(VALID_INTENT), "test")
        self.assertIn("garment", intent.purpose)
        self.assertEqual("turntable", intent.camera_path)
        self.assertEqual(("clipping", "popping"), intent.avoid)

    def test_purpose_is_required_and_never_inferred(self) -> None:
        with self.assertRaisesRegex(PipelineError, "missing required field 'purpose'"):
            parse_intent({"camera_path": "turntable"}, "test")
        with self.assertRaisesRegex(PipelineError, "never inferred"):
            parse_intent({**VALID_INTENT, "purpose": "   "}, "test")

    def test_unknown_fields_are_refused(self) -> None:
        with self.assertRaisesRegex(PipelineError, "unknown intent field"):
            parse_intent({**VALID_INTENT, "intended_use": "x"}, "test")

    def test_a_wrong_schema_version_is_refused_not_coerced(self) -> None:
        with self.assertRaisesRegex(PipelineError, "schema_version"):
            parse_intent({**VALID_INTENT, "schema_version": 99}, "test")

    def test_inline_text_round_trips_through_the_same_validator(self) -> None:
        intent, raw = parse_intent_text(json.dumps(VALID_INTENT))
        self.assertEqual(VALID_INTENT["purpose"], intent.purpose)
        self.assertTrue(raw.startswith(b"{"))


class ResultTests(unittest.TestCase):
    def test_a_valid_result_normalizes_and_keeps_both_moments(self) -> None:
        result = validate_result(_valid_result())
        self.assertEqual([2.0, 3.0], result["issues"][0]["at_seconds"])
        self.assertEqual([8.0, 12.0], result["issues"][0]["at_frame"])

    def test_a_frame_only_issue_is_accepted(self) -> None:
        data = _valid_result()
        data["issues"] = [{"description": "pops at the end", "at_frame": [38, 39]}]
        result = validate_result(data)
        self.assertNotIn("at_seconds", result["issues"][0])

    def test_bad_moments_are_refused(self) -> None:
        data = _valid_result()
        data["issues"] = [{"description": "x", "at_frame": [-1, 2]}]
        with self.assertRaisesRegex(PipelineError, "at_frame"):
            validate_result(data)

    def test_a_single_frame_index_or_second_normalizes_to_a_pair(self) -> None:
        data = dict(_gateway_envelope()["result"])  # type: ignore[arg-type]
        data["issues"] = [{"description": "pops at frame 10", "at_frame": 10}]
        result = validate_result(data)
        self.assertEqual([10.0, 10.0], result["issues"][0]["at_frame"])
        data = dict(_gateway_envelope()["result"])  # type: ignore[arg-type]
        data["issues"] = [{"description": "starts at 2s", "at_seconds": 2}]
        result = validate_result(data)
        self.assertEqual([2.0, 2.0], result["issues"][0]["at_seconds"])

    def test_a_null_score_is_allowed_but_a_non_number_is_not(self) -> None:
        data = _valid_result()
        data["rubric_scores"] = {"semantic_fit": None, "timing": True}
        with self.assertRaisesRegex(PipelineError, "number or null"):
            validate_result(data)


class RunReviewTests(_ReviewHarness):
    def test_consent_is_demanded_before_the_gateway_is_even_consulted(self) -> None:
        with self.assertRaisesRegex(PipelineError, "allow.network"):
            self._run(allow_network=False)
        self.assertEqual([], self.gateway.calls)

    def test_exactly_one_intent_source_is_required(self) -> None:
        with self.assertRaisesRegex(PipelineError, "exactly one of --intent"):
            self._run(intent_path=None, intent_text=None)

    def test_an_unadopted_directory_is_refused(self) -> None:
        stray = self.root / "somewhere-else"
        stray.mkdir()
        (stray / "frame-0000.png").write_bytes(b"x")
        with self.assertRaisesRegex(PipelineError, "never adopted"):
            self._run(clip=stray)

    def test_the_gateway_receives_the_adopted_clip_and_intent(self) -> None:
        self._run()
        argv = self.gateway.calls[0]
        self.assertIn("review", argv)
        self.assertIn(str(self.capture_root / "thing"), argv)
        self.assertIn("--intent", argv)
        self.assertIn(str(self.intent_file), argv)
        self.assertIn("--provider", argv)
        self.assertIn("fake", argv)
        self.assertIn("--allow-network", argv)
        self.assertIn("--json", argv)

    def test_a_missing_gateway_is_refused_with_the_install_route(self) -> None:
        with (
            mock.patch.object(video_review, "deadeye_available", return_value=False),
            self.assertRaisesRegex(PipelineError, "model-video-review"),
        ):
            self._run()

    def test_the_gateway_refusal_is_a_hard_failure(self) -> None:
        import subprocess

        def refusing(argv: list[str], timeout: float) -> object:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="ERROR: nope")

        with self.assertRaisesRegex(PipelineError, "refused the review"):
            self._run(runner=refusing)

    def test_evidence_names_the_source_hash_and_gateway_envelope(self) -> None:
        output = self.root / "evidence" / "review.json"
        report = self._run(output=output)
        document = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual("shamway-video-review-evidence", document["kind"])
        self.assertEqual("thing", document["asset"]["stem"])
        self.assertIsNotNone(document["asset"]["source_sha256"])
        self.assertIsNone(document["asset"]["generation_parameters"])
        self.assertEqual("deadeye-review", document["gateway"]["kind"])
        self.assertEqual(document["result"], report["review"])
        self.assertTrue(document["disclosure"]["network_consent"])
        self.assertNotIn("GEMINI_API_KEY", output.read_text(encoding="utf-8"))

    def test_an_earlier_evidence_document_is_never_overwritten_by_default(self) -> None:
        output = self.root / "review.json"
        self._run(output=output)
        first = output.read_bytes()
        with self.assertRaisesRegex(PipelineError, "never overwrites"):
            self._run(output=output)
        self.assertEqual(first, output.read_bytes())

    def test_two_reviews_of_one_candidate_are_both_preserved(self) -> None:
        first = self.root / "a.json"
        second = self.root / "b.json"
        self._run(output=first)
        self._run(output=second)
        self.assertTrue(first.stat().st_size > 0)
        self.assertTrue(second.stat().st_size > 0)

    def test_a_stem_with_no_source_file_records_that_honestly(self) -> None:
        (self.root / "assets-src" / "bundle" / "thing.glb").unlink()
        report = self._run()
        self.assertIsNone(report["asset"]["source_sha256"])
        self.assertIn("no source file recorded", report["asset"]["note"])

    def test_usage_unavailability_is_reported_not_estimated(self) -> None:
        envelope = dict(_gateway_envelope())
        envelope["usage"] = None
        report = self._run(runner=_FakeGateway(envelope))
        self.assertFalse(report["usage"]["reported_by_provider"])


class GatewayEnvelopeTests(_ReviewHarness):
    def test_a_non_gateway_envelope_is_refused(self) -> None:
        import subprocess

        def wrong(argv: list[str], timeout: float) -> object:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({"kind": "other"}), stderr=""
            )

        with self.assertRaisesRegex(PipelineError, "unexpected envelope"):
            self._run(runner=wrong)

    def test_an_invalid_result_from_the_gateway_fails_validation(self) -> None:
        envelope = dict(_gateway_envelope())
        envelope["result"] = {"summary": "broken"}
        with self.assertRaisesRegex(PipelineError, "missing key"):
            self._run(runner=_FakeGateway(envelope))
