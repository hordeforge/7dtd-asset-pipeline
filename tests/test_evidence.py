"""The shared evidence helpers every review lane reads untrusted input through.

`audio_review` and `video_review` both decode a caller's or a model's JSON
document through these functions before anything else looks at it, and both
record hash-addressed evidence through the same three. Each behaviour here is
specified by the helper's own docstring or its error message, and none of the
type rejections was reachable from a lane's own tests, so a non-string field
could have been accepted silently.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from sevendtd_asset_pipeline import PipelineError, evidence


class DecodeTests(unittest.TestCase):
    def test_valid_utf8_json_decodes(self) -> None:
        self.assertEqual({"a": 1}, evidence.decode_json(b'{"a": 1}', "document"))

    def test_malformed_json_names_the_origin(self) -> None:
        with self.assertRaisesRegex(PipelineError, "document is not valid JSON"):
            evidence.decode_json(b"{not json", "document")

    def test_bytes_that_are_not_utf8_name_the_origin(self) -> None:
        with self.assertRaisesRegex(PipelineError, "document is not valid JSON"):
            evidence.decode_json(b"\xff\xfe", "document")


class StringFieldTests(unittest.TestCase):
    def test_an_absent_field_is_empty_and_an_explicit_null_too(self) -> None:
        self.assertEqual("", evidence.string_field({}, "purpose", "intent"))
        self.assertEqual("", evidence.string_field({"purpose": None}, "purpose", "intent"))

    def test_surrounding_whitespace_is_stripped(self) -> None:
        self.assertEqual(
            "show the rig",
            evidence.string_field({"purpose": "  show the rig\n"}, "purpose", "intent"),
        )

    def test_a_non_string_field_is_refused_by_type(self) -> None:
        """The value is JSON a caller or a model wrote, so a number is an error."""
        with self.assertRaisesRegex(
            PipelineError, r"intent: field 'purpose' must be a string, got int"
        ):
            evidence.string_field({"purpose": 7}, "purpose", "intent")

    def test_a_list_field_is_refused_rather_than_stringified(self) -> None:
        with self.assertRaisesRegex(PipelineError, "must be a string, got list"):
            evidence.string_field({"purpose": ["a", "b"]}, "purpose", "intent")


class StringListTests(unittest.TestCase):
    def test_an_absent_or_null_field_is_empty(self) -> None:
        self.assertEqual((), evidence.string_list({}, "avoid", "intent"))
        self.assertEqual((), evidence.string_list({"avoid": None}, "avoid", "intent"))

    def test_items_are_stripped_and_blanks_dropped(self) -> None:
        self.assertEqual(
            ("clipping", "popping"),
            evidence.string_list(
                {"avoid": [" clipping ", "", "   ", "popping"]}, "avoid", "intent"
            ),
        )

    def test_a_non_list_is_refused(self) -> None:
        with self.assertRaisesRegex(
            PipelineError, r"intent: field 'avoid' must be a list of strings"
        ):
            evidence.string_list({"avoid": "clipping"}, "avoid", "intent")

    def test_one_non_string_item_refuses_the_whole_list(self) -> None:
        """A partly numeric list is malformed, not a list with the numbers skipped."""
        with self.assertRaisesRegex(PipelineError, "must be a list of strings"):
            evidence.string_list({"avoid": ["clipping", 3]}, "avoid", "intent")


class IntentFileTests(unittest.TestCase):
    def test_the_document_and_its_exact_bytes_both_come_back(self) -> None:
        """The raw bytes are what the evidence document hashes, so they must be
        the file's own bytes and not a re-serialization of the parse."""
        raw = b'{"purpose": "  show the rig  "}\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "intent.json"
            path.write_bytes(raw)
            document, returned = evidence.load_intent_file(path, lambda data, _origin: data)
        self.assertEqual(raw, returned)
        self.assertEqual({"purpose": "  show the rig  "}, document)

    def test_the_origin_reaches_the_lane_validator(self) -> None:
        seen: list[str] = []

        def parse(_data: Any, origin: str) -> Any:
            seen.append(origin)
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "intent.json"
            path.write_text("{}", encoding="utf-8")
            evidence.load_intent_file(path, parse)
        self.assertEqual([f"intent file {path}"], seen)

    def test_a_missing_file_names_the_path_rather_than_the_os_error(self) -> None:
        with self.assertRaisesRegex(PipelineError, "cannot read intent file"):
            evidence.load_intent_file(Path("/nonexistent/intent.json"), lambda data, _origin: data)

    def test_malformed_content_is_refused_before_the_validator_sees_it(self) -> None:
        def parse(_data: Any, _origin: str) -> Any:
            self.fail("the validator ran on a document that never decoded")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "intent.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "is not valid JSON"):
                evidence.load_intent_file(path, parse)


class DigestTests(unittest.TestCase):
    def test_an_empty_file_hashes_to_the_empty_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.bin"
            path.write_bytes(b"")
            digest, size = evidence.sha256_file(path)
        self.assertEqual(hashlib.sha256(b"").hexdigest(), digest)
        self.assertEqual(0, size)

    def test_a_file_larger_than_one_chunk_digests_whole(self) -> None:
        """The read is chunked, so the boundary is where a partial update hides."""
        payload = bytes(range(256)) * 8192  # 2 MiB, past the 1 MiB chunk
        self.assertGreater(len(payload), 1024 * 1024)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.bin"
            path.write_bytes(payload)
            digest, size = evidence.sha256_file(path)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), digest)
        self.assertEqual(len(payload), size)
        self.assertEqual(digest, evidence.sha256_bytes(payload))


class RedactionTests(unittest.TestCase):
    def test_credential_bearing_keys_are_dropped_at_every_depth(self) -> None:
        document = {
            "model": "fake",
            "api_key": "sk-live",
            "nested": {"Authorization": "Bearer x", "seed": 3},
            "list": [{"password": "hunter2", "keep": True}],
        }
        self.assertEqual(
            {"model": "fake", "nested": {"seed": 3}, "list": [{"keep": True}]},
            evidence.redact(document),
        )

    def test_a_bare_key_name_is_dropped_because_a_provider_names_it_that(self) -> None:
        self.assertEqual({"kept": 1}, evidence.redact({"key": "sk-live", "kept": 1}))

    def test_usage_keeps_token_counts_but_drops_the_names_a_secret_travels_in(self) -> None:
        """`token` is billing inside a usage block and authentication outside it."""
        usage = {"totalTokenCount": 12, "api_key": "sk-live", "secret_id": "s"}
        self.assertEqual(
            {"totalTokenCount": 12},
            evidence.redact(usage, evidence.USAGE_SENSITIVE_KEY_PARTS),
        )
        # The broad rule has no such exception, so the same block loses its
        # count too. That asymmetry is the reason the narrow one exists.
        self.assertEqual({}, evidence.redact(usage))

    def test_scalars_and_lists_pass_through_unchanged(self) -> None:
        self.assertEqual("plain", evidence.redact("plain"))
        self.assertEqual([1, None, True], evidence.redact([1, None, True]))

    def test_redaction_does_not_mutate_the_document_it_copies(self) -> None:
        document = {"api_key": "sk-live", "nested": {"secret": "s", "keep": 1}}
        evidence.redact(document)
        self.assertEqual({"api_key": "sk-live", "nested": {"secret": "s", "keep": 1}}, document)

    def test_a_non_string_mapping_key_is_dropped_rather_than_kept(self) -> None:
        self.assertEqual(
            {"keep": 1},
            evidence.redact({1: "dropped", "keep": 1}),
        )

    def test_the_redacted_document_is_still_serializable(self) -> None:
        document = {"api_key": "sk-live", "parameters": {"seed": 3, "token": "t"}}
        self.assertEqual(
            '{"parameters": {"seed": 3}}', json.dumps(evidence.redact(document), sort_keys=True)
        )

    def test_a_credential_in_free_text_is_scrubbed_under_any_key_name(self) -> None:
        """The gateway inherits the environment, so its envelope can quote the key.

        The drop rule above only sees mapping keys. A gateway error that
        echoes the request that carried the key puts it inside an ordinary
        string under a name like `error`, which is what a stored evidence
        document written to be read by somebody else must not carry.
        """
        document = {"gateway": {"error": "401 for x-goog-api-key: AIzaSyD9xQ2mVb7Kt3Rp"}}
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaSyD9xQ2mVb7Kt3Rp"}):
            scrubbed = evidence.redact(document)
        self.assertEqual({"gateway": {"error": "401 for x-goog-api-key: [redacted]"}}, scrubbed)

    def test_a_credential_from_the_environment_is_scrubbed_wherever_it_appears(self) -> None:
        with mock.patch.dict(os.environ, {"SOME_VENDOR_TOKEN": "tok-abcdef123456"}):
            scrubbed = evidence.redact({"note": "gateway echoed tok-abcdef123456 in prose"})
        self.assertEqual({"note": "gateway echoed [redacted] in prose"}, scrubbed)

    def test_inline_credential_syntax_is_scrubbed_without_knowing_the_value(self) -> None:
        """A credential this process never held is still not evidence."""
        self.assertEqual(
            {"error": "[redacted]"},
            evidence.redact({"error": "Authorization: Bearer sk-live-0123456789"}),
        )

    def test_a_short_environment_value_is_not_used_as_a_pattern(self) -> None:
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "abc"}):
            self.assertEqual("abc", evidence.scrub("abc"))
            self.assertNotIn("abc", evidence.environment_secrets())

    def test_a_sensitive_name_holding_a_path_is_not_treated_as_a_credential(self) -> None:
        """`*_TOKEN_PATH` names a directory; a citation is not a secret."""
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"VENDOR_TOKEN_PATH": tmp}),
        ):
            self.assertNotIn(tmp, evidence.environment_secrets())

    def test_ordinary_prose_survives_redaction(self) -> None:
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaSyD9xQ2mVb7Kt3Rp"}):
            self.assertEqual(
                "the ring was centred and the beeps were clean",
                evidence.redact("the ring was centred and the beeps were clean"),
            )


class HomeAbbreviationTests(unittest.TestCase):
    """A stored document must not carry the account name of whoever ran the run."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        patcher = mock.patch.dict(os.environ, {"HOME": self.temporary.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.home = os.path.realpath(self.temporary.name)

    def test_a_path_under_the_home_directory_loses_the_account_name(self) -> None:
        document = {"clip": {"path": f"{self.home}/MyMod/.local/acceptance/thing/frame-0000.png"}}
        self.assertEqual(
            {"clip": {"path": "~/MyMod/.local/acceptance/thing/frame-0000.png"}},
            evidence.redact(document),
        )

    def test_the_home_directory_alone_becomes_a_tilde(self) -> None:
        self.assertEqual("~", evidence.abbreviate_home(self.home))

    def test_a_path_outside_the_home_directory_is_left_alone(self) -> None:
        self.assertEqual("/opt/7DaysToDie/Mods", evidence.abbreviate_home("/opt/7DaysToDie/Mods"))

    def test_a_sibling_sharing_the_prefix_characters_is_not_a_path(self) -> None:
        """`/tmp/user-archive` is beside the home directory, not inside it."""
        self.assertEqual(
            f"{self.home}-archive/mod", evidence.abbreviate_home(f"{self.home}-archive/mod")
        )

    def test_a_host_without_a_home_leaves_every_string_alone(self) -> None:
        with mock.patch.dict(os.environ, {"HOME": ""}):
            self.assertEqual(f"{self.home}/mod", evidence.abbreviate_home(f"{self.home}/mod"))
