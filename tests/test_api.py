from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline import OPERATIONS, Pipeline, PipelineError, manifest
from sevendtd_asset_pipeline.api import call_json
from sevendtd_asset_pipeline.serve import handle, serve


class ManifestTests(unittest.TestCase):
    """The published contract is what out-of-process consumers build against."""

    def test_manifest_is_json_serializable_and_complete(self) -> None:
        published = json.loads(json.dumps(manifest()))
        self.assertEqual(len(OPERATIONS), len(published["operations"]))
        for operation in published["operations"]:
            with self.subTest(operation["name"]):
                self.assertTrue(operation["summary"])
                self.assertEqual("object", operation["parameters"]["type"])
                self.assertIn(operation["cost"], ("instant", "fast", "seconds", "minutes"))
                self.assertIsInstance(operation["writes"], bool)
                self.assertIsInstance(operation["needs_config"], bool)
                self.assertTrue(operation["returns"])

    def test_every_operation_is_dispatchable(self) -> None:
        from sevendtd_asset_pipeline.api import _DISPATCH

        self.assertEqual(set(OPERATIONS), set(_DISPATCH), "registry and dispatch must agree")

    def test_stateless_operations_are_dispatchable_without_config(self) -> None:
        from sevendtd_asset_pipeline.api import _STATELESS

        stateless = {name for name, op in OPERATIONS.items() if not op.needs_config}
        self.assertEqual(stateless, set(_STATELESS))

    def test_only_build_and_init_declare_writes(self) -> None:
        writers = {name for name, op in OPERATIONS.items() if op.writes}
        self.assertEqual({"build", "init"}, writers)


class DispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )
        self.pipeline, self.created = Pipeline.scaffold(
            self.root, unity_version="2022.3.62f2", bundle_name="example.unity3d"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_scaffold_returns_a_usable_pipeline(self) -> None:
        self.assertEqual("ExampleMod", self.pipeline.config.mod_name)
        self.assertTrue(any(path.name == "AGENTS.md" for path in self.created))

    def test_call_matches_the_direct_method(self) -> None:
        self.assertEqual(self.pipeline.status().as_dict(), call_json(self.pipeline, "status"))

    def test_unknown_operation_lists_the_known_ones(self) -> None:
        with self.assertRaisesRegex(PipelineError, "unknown operation"):
            self.pipeline.call("teleport")

    def test_unknown_parameter_is_rejected_with_what_is_accepted(self) -> None:
        with self.assertRaisesRegex(PipelineError, "unknown parameter"):
            self.pipeline.call("status", {"bundle": "x"})

    def test_missing_required_parameter_is_named(self) -> None:
        with self.assertRaisesRegex(PipelineError, "requires parameter 'mesh'"):
            call_json(None, "check_mesh", {})

    def test_config_bound_operation_without_config_explains_itself(self) -> None:
        with self.assertRaisesRegex(PipelineError, "needs a mod configuration"):
            call_json(None, "status")

    def test_every_result_is_json_serializable(self) -> None:
        for name in ("status", "capabilities", "refs"):
            with self.subTest(name):
                json.dumps(call_json(self.pipeline, name))


class ServeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )
        self.pipeline, _ = Pipeline.scaffold(self.root, unity_version="2022.3.62f2")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run(self, *requests: object, allow_writes: bool = False) -> list[dict]:
        payload = "".join(json.dumps(request) + "\n" for request in requests)
        output = io.StringIO()
        serve(lambda: self.pipeline, allow_writes, io.StringIO(payload), output)
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def test_responses_echo_ids_in_order(self) -> None:
        responses = self._run(
            {"id": "a", "op": "ping"}, {"id": 2, "op": "capabilities"}, {"id": None, "op": "refs"}
        )
        self.assertEqual(["a", 2, None], [item["id"] for item in responses])
        self.assertTrue(all(item["ok"] for item in responses))

    def test_schema_is_served_over_the_same_channel(self) -> None:
        (response,) = self._run({"id": 1, "op": "schema"})
        self.assertEqual(len(OPERATIONS), len(response["result"]["operations"]))

    def test_writes_are_refused_unless_explicitly_allowed(self) -> None:
        (response,) = self._run({"id": 1, "op": "build", "params": {"probe": True}})
        self.assertFalse(response["ok"])
        self.assertIn("read-only", response["error"]["message"])

    def test_a_bad_line_does_not_desynchronize_the_session(self) -> None:
        output = io.StringIO()
        stream = io.StringIO('not json\n{"id":2,"op":"ping"}\n')
        serve(lambda: self.pipeline, False, stream, output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(2, len(responses))
        self.assertFalse(responses[0]["ok"])
        self.assertTrue(responses[1]["ok"], "the session must survive a malformed request")

    def test_non_object_request_is_an_error_not_a_crash(self) -> None:
        response = handle([1, 2, 3], lambda: self.pipeline, False)
        self.assertFalse(response["ok"])
        self.assertIn("JSON object", response["error"]["message"])

    def test_errors_carry_a_type_and_message(self) -> None:
        (response,) = self._run({"id": 1, "op": "validate"})
        self.assertFalse(response["ok"])
        self.assertEqual("PipelineError", response["error"]["type"])
        self.assertTrue(response["error"]["message"])


if __name__ == "__main__":
    unittest.main()
