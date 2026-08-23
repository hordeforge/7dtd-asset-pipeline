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

    def test_the_writing_operations_are_exactly_the_expected_set(self) -> None:
        """A caller decides what is safe to run from `writes`, so guard the set."""
        writers = {name for name, op in OPERATIONS.items() if op.writes}
        self.assertEqual(
            {
                "build",
                "pack",
                "stage",
                "init",
                "render_icon",
                "client_deploy",
                "client_launch",
                "acceptance_provider",
            },
            writers,
        )


class CommandLineTests(unittest.TestCase):
    """Run the CLI the way a user does.

    `shamway schema` shipped broken once: a local variable in `run()` shadowed
    the module-level `manifest` import for the whole function, which no test
    that called the API could see. Exercising the entry point is what catches
    that class of mistake.
    """

    def test_schema_prints_the_operation_manifest(self) -> None:
        import io
        from contextlib import redirect_stdout

        from sevendtd_asset_pipeline.cli import main

        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(["schema"])
        self.assertEqual(0, code)
        published = json.loads(stream.getvalue())
        self.assertEqual(set(OPERATIONS), {item["name"] for item in published["operations"]})

    def test_a_failed_gate_exits_non_zero_with_one_error_line(self) -> None:
        """The published agent contract: exit code over parsing prose.

        AGENTS.md promises every failing command a single `ERROR:` line on
        stderr and a non-zero exit; agents and CI key on exactly that shape.
        """
        import contextlib
        import io

        from sevendtd_asset_pipeline.cli import main

        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with contextlib.redirect_stderr(stderr):
                code = main(["inspect", str(Path(directory) / "absent.unity3d")])
        self.assertEqual(1, code)
        lines = stderr.getvalue().splitlines()
        self.assertEqual(1, len(lines), f"expected one ERROR line, got {lines}")
        self.assertTrue(lines[0].startswith("ERROR: "), lines)


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

    def test_a_published_enum_is_enforced_before_any_work_starts(self) -> None:
        """`shamway schema` publishes enums, so `call` holds params to them.

        init's bundle_source is a write: an unvalidated value used to scaffold
        the whole modlet and only then fail on load, or worse, report success
        through `serve` with a configuration nothing can open.
        """
        with tempfile.TemporaryDirectory() as directory:
            mod_root = Path(directory) / "mod"
            mod_root.mkdir()
            (mod_root / "ModInfo.xml").write_text(
                '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
            )
            with self.assertRaisesRegex(PipelineError, "expected one of"):
                call_json(None, "init", {"mod_root": str(mod_root), "bundle_source": "bogus"})
            self.assertFalse((mod_root / ".shamway.toml").exists(), "nothing may be written")

    def test_the_published_enums_cannot_drift_from_their_registries(self) -> None:
        from sevendtd_asset_pipeline.config import BUNDLE_SOURCES
        from sevendtd_asset_pipeline.prompts import KEYS, KINDS

        by_name = {operation["name"]: operation for operation in manifest()["operations"]}
        prompt = by_name["prompt"]["parameters"]["properties"]
        self.assertEqual(sorted(KINDS), prompt["kind"]["enum"])
        self.assertEqual(["", *sorted(KEYS)], prompt["key"]["enum"])
        init = by_name["init"]["parameters"]["properties"]
        self.assertEqual(sorted(BUNDLE_SOURCES), init["bundle_source"]["enum"])

    def test_config_bound_operation_without_config_explains_itself(self) -> None:
        with self.assertRaisesRegex(PipelineError, "needs a mod configuration"):
            call_json(None, "status")

    def test_every_result_is_json_serializable(self) -> None:
        for name in ("status", "capabilities", "refs"):
            with self.subTest(name):
                json.dumps(call_json(self.pipeline, name))

    def test_a_stateless_prompt_dispatches_like_the_bound_one(self) -> None:
        """`prompt` runs before a modlet exists, so it must work without config."""
        stateless = call_json(
            None, "prompt", {"kind": "item-icon", "subject": "a nuke"}
        )
        bound = self.pipeline.call("prompt", {"kind": "item-icon", "subject": "a nuke"})
        self.assertEqual(stateless, bound)
        self.assertIn("Asset type:", stateless["prompt"])

    def test_client_where_resolves_paths_from_an_explicit_game_dir(self) -> None:
        import tempfile as tempdir

        with tempdir.TemporaryDirectory() as game:
            data = call_json(None, "client_where", {"game_dir": str(Path(game) / "7 Days To Die")})
            self.assertIsNone(data["mods_dir"])  # not a Steam library layout
            self.assertEqual(["steam", "-applaunch", "251570"], data["launch"][:3])


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


class ImportHygieneTests(unittest.TestCase):
    """The package is a layered graph: leaf modules must not import upward.

    `__init__` imports the facade, which imports the registry, so any
    module-level import of the package root from below it is a cycle that only
    works while every consumer enters through `__init__`. The convention this
    pins: intra-package imports sit at module top level, and they point
    downward (errors, _version, capabilities) or sideways, never up.
    """

    def test_every_module_imports_cleanly(self) -> None:
        import importlib
        import pkgutil

        import sevendtd_asset_pipeline

        for module in pkgutil.walk_packages(
            sevendtd_asset_pipeline.__path__, prefix="sevendtd_asset_pipeline."
        ):
            if module.name.endswith(".__main__"):
                # An entry point runs main() at import time by design; it is
                # not part of the importable surface this test covers.
                continue
            with self.subTest(module.name):
                importlib.import_module(module.name)

    def test_no_intra_package_import_inside_a_function(self) -> None:
        import ast

        import sevendtd_asset_pipeline

        root = Path(sevendtd_asset_pipeline.__file__).resolve().parent
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for sub in ast.walk(node):
                    bad = (isinstance(sub, ast.ImportFrom) and sub.level > 0) or (
                        isinstance(sub, ast.Import)
                        and any(
                            alias.name.startswith("sevendtd_asset_pipeline")
                            for alias in sub.names
                        )
                    )
                    if bad:
                        self.fail(f"{path.relative_to(root)}:{sub.lineno}: "
                                  f"intra-package import inside {node.name}()")

    def test_registry_reads_the_version_without_importing_upward(self) -> None:
        from sevendtd_asset_pipeline import operations

        source = Path(operations.__file__).read_text(encoding="utf-8")
        self.assertNotIn("from . import", source)
        self.assertIn("from ._version import __version__", source)
        self.assertEqual(manifest()["version"], __import__("sevendtd_asset_pipeline").__version__)


if __name__ == "__main__":
    unittest.main()
