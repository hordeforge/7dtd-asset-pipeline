from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import typing
import unittest
from pathlib import Path
from typing import cast

from fixtures import unityfs_bundle

from sevendtd_asset_pipeline import OPERATIONS, Pipeline, PipelineError, has_capability, manifest
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
                "review_audio",
                "review_video",
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
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stderr(stderr):
            code = main(["inspect", str(Path(directory) / "absent.unity3d")])
        self.assertEqual(1, code)
        lines = stderr.getvalue().splitlines()
        self.assertEqual(1, len(lines), f"expected one ERROR line, got {lines}")
        self.assertTrue(lines[0].startswith("ERROR: "), lines)


class EntryPointTests(unittest.TestCase):
    """The per-command argument plumbing behind `shamway <command>`.

    `schema` shipped broken once because a local shadow only `run()` could see;
    these exercise the entry point of the cheap read-only commands an agent
    runs first, where a wiring mistake is invisible to the API-level tests.
    """

    def _mod(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )
        _, _ = Pipeline.scaffold(root, unity_version="2022.3.62f2", bundle_name="example.unity3d")
        return temporary, root

    def test_status_exit_code_follows_the_mod_state(self) -> None:
        import contextlib
        import io

        from sevendtd_asset_pipeline.cli import main

        _, root = self._mod()
        config_file = root / ".shamway.toml"
        # Nothing staged yet: status reports, and fails the process.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(1, main(["--config", str(config_file), "status"]))
        # A staged bundle, its manifest, and a matching reference: valid.
        resources = root / "Resources"
        resources.mkdir()
        (resources / "example.unity3d").write_bytes(unityfs_bundle([1, 142]))
        manifest = root / "tools/shamway/manifests/example.unity3d.manifest"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            "ManifestFileVersion: 0\nAssets:\n- Assets/ModAssets/Bundle/exampleThing.prefab\n",
            encoding="utf-8",
        )
        (root / "Config").mkdir()
        (root / "Config/blocks.xml").write_text(
            '<configs><block name="x"><property name="Model" '
            'value="#@modfolder(ExampleMod):Resources/example.unity3d?exampleThing.prefab" />'
            "</block></configs>",
            encoding="utf-8",
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, main(["--config", str(config_file), "status", "--json"]))
        data = json.loads(out.getvalue())
        self.assertTrue(data["valid"], data["problems"])

    def test_inspect_json_publishes_the_container_gate(self) -> None:
        import contextlib
        import io

        from sevendtd_asset_pipeline.cli import main

        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "b.unity3d"
            bundle.write_bytes(unityfs_bundle([1, 142]))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(0, main(["inspect", str(bundle), "--json"]))
            data = json.loads(out.getvalue())
        self.assertEqual("2022.3.62f2", data["unity_version"])
        self.assertIn(142, data["class_ids"])
        self.assertTrue(data["has_assetbundle_object"])

    def test_validate_bundle_standalone_needs_no_configuration(self) -> None:
        import contextlib
        import io

        from sevendtd_asset_pipeline.cli import main

        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "b.unity3d"
            bundle.write_bytes(unityfs_bundle([142]))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(0, main(["validate", "--bundle", str(bundle)]))
        self.assertIn("OK:", out.getvalue())

    def test_refs_prints_one_source_uri_line_per_reference(self) -> None:
        import contextlib
        import io

        from sevendtd_asset_pipeline.cli import main

        _, root = self._mod()
        (root / "Config").mkdir()
        (root / "Config/blocks.xml").write_text(
            '<configs><block name="x"><property name="Model" '
            'value="#@modfolder(ExampleMod):Resources/example.unity3d?exampleThing.prefab" />'
            "</block></configs>",
            encoding="utf-8",
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, main(["--config", str(root / ".shamway.toml"), "refs"]))
        self.assertEqual(
            [
                "Config/blocks.xml:"
                " #@modfolder(ExampleMod):Resources/example.unity3d?exampleThing.prefab"
            ],
            out.getvalue().splitlines(),
        )


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

    def test_unity_release_resolves_a_revision_without_a_unity_project(self) -> None:
        """The default editorless mod has no `ProjectVersion.txt` to read.

        `unity_release()` with no argument resolved the project's file and
        nothing else, so on the default `bundle_source = "synthesized"` it
        failed with a missing-file error for a mod that had recorded its
        revision at scaffold time.
        """
        from sevendtd_asset_pipeline.build import release_unity_version

        self.assertFalse(self.pipeline.config.unity_project.exists())
        self.assertEqual("2022.3.62f2", release_unity_version(self.pipeline.config))

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

    @unittest.skipUnless(
        has_capability("trimesh"), "the mesh gate reads interchange files through trimesh"
    )
    def test_a_stateless_operation_is_called_by_its_published_parameter_names(self) -> None:
        """The bound methods name their parameters to match the schema.

        The stateless entries dispatch straight to the module functions, whose
        own first parameter is `path` where the published one is `mesh`. A
        mismatch there is a `TypeError` from inside the package, so every
        out-of-process caller of the operation got a traceback where a result
        or a `PipelineError` belongs.
        """
        with self.assertRaisesRegex(PipelineError, "no such mesh"):
            call_json(None, "check_mesh", {"mesh": str(self.root / "absent.glb")})

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

    def test_a_parameter_of_the_wrong_type_is_refused_naming_it(self) -> None:
        """JSON has one spelling per type, so nothing here coerces.

        `allow_network="false"` is truthy and would upload the clip, and
        `install="false"` wrote into the shared `Mods/` folder. Every other
        boundary this package owns refuses the quoted form, so the operation
        params do too, with a message that names the parameter.
        """
        with self.assertRaisesRegex(PipelineError, "allow_network='false'"):
            call_json(
                None,
                "review_audio",
                {"clip": "falling.wav", "allow_network": "false"},
            )
        with self.assertRaisesRegex(PipelineError, "expected boolean"):
            self.pipeline.call("client_deploy", {"replace": "false"})

    def test_an_integer_parameter_will_not_accept_a_boolean(self) -> None:
        """`bool` is an `int` subclass, so `True` would pass an integer gate."""
        with self.assertRaisesRegex(PipelineError, "expected integer"):
            self.pipeline.call("client_launch", {"run_seconds": True, "mute": False})

    def test_a_path_parameter_accepts_what_the_facade_documents(self) -> None:
        from sevendtd_asset_pipeline.api import _validated
        from sevendtd_asset_pipeline.operations import get as get_operation

        arguments = _validated(get_operation("inspect"), {"bundle": Path("a.unity3d")})
        self.assertIsInstance(arguments["bundle"], Path)

    def test_the_published_enums_cannot_drift_from_their_registries(self) -> None:
        from sevendtd_asset_pipeline.config import BUNDLE_SOURCES
        from sevendtd_asset_pipeline.prompts import KEYS, KINDS

        by_name = {operation["name"]: operation for operation in manifest()["operations"]}
        prompt = by_name["prompt"]["parameters"]["properties"]
        self.assertEqual(sorted(KINDS), prompt["kind"]["enum"])
        self.assertEqual(["", *sorted(KEYS)], prompt["key"]["enum"])
        init = by_name["init"]["parameters"]["properties"]
        self.assertEqual(list(BUNDLE_SOURCES), init["bundle_source"]["enum"])
        # Deliberately no published default: an absent bundle_source means
        # "synthesized" alone but "unity" with adopt_project, and the schema
        # layer fills defaults before it can see the other parameter.
        self.assertNotIn("default", init["bundle_source"])

    def test_a_published_default_is_applied_and_an_explicit_value_wins(self) -> None:
        """The schema is the only copy of a parameter default.

        `call` fills an absent parameter from the property's declared default,
        so the dispatch layer reads the applied value instead of carrying its
        own fallback literal that could drift from what `shamway schema`
        promises.
        """
        from sevendtd_asset_pipeline.api import _validated
        from sevendtd_asset_pipeline.operations import get as get_operation

        defaulted = _validated(get_operation("prompt"), {"kind": "item-icon", "subject": "a nuke"})
        self.assertEqual("myModThing", defaulted["stem"])
        overridden = _validated(
            get_operation("prompt"), {"kind": "item-icon", "subject": "a nuke", "stem": "thing"}
        )
        self.assertEqual("thing", overridden["stem"])

    def test_config_bound_operation_without_config_explains_itself(self) -> None:
        with self.assertRaisesRegex(PipelineError, "needs a mod configuration"):
            call_json(None, "status")

    def test_a_broken_config_reports_its_own_error_not_needs_config(self) -> None:
        """`shamway call` must not turn an unreadable config into "no config".

        The stateless dispatch degrades to `pipeline=None` only when no
        `.shamway.toml` exists. A file that exists but cannot be parsed has a
        different fix, and swallowing its error here reported "needs a mod
        configuration" for a configuration the caller was staring at.
        """
        from sevendtd_asset_pipeline.cli import main as cli_main

        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / ".shamway.toml"
            broken.write_text("mod_name = [unclosed", encoding="utf-8")
            stderr = io.StringIO()
            stdout = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                code = cli_main(["--config", str(broken), "call", "status"])
            self.assertEqual(1, code)
            self.assertIn("cannot read", stderr.getvalue())
            self.assertNotIn("needs a mod configuration", stderr.getvalue())

    def test_serve_survives_a_resolver_that_raises_on_a_broken_config(self) -> None:
        """A per-request resolve failure is one failed response, not a dead server."""
        from sevendtd_asset_pipeline.errors import PipelineError

        def resolve() -> Pipeline | None:
            raise PipelineError("cannot read .shamway.toml: invalid TOML at line 3")

        output = io.StringIO()
        stream = io.StringIO('{"id":7,"op":"status"}\n{"id":8,"op":"ping"}\n')
        serve(resolve, False, stream, output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertFalse(responses[0]["ok"])
        self.assertEqual(7, responses[0]["id"])
        self.assertIn("cannot read", cast(str, _nested(responses[0], "error")["message"]))
        # The session survives: ping needs no config, so it still answers.
        self.assertTrue(responses[1]["ok"])

    def test_every_result_is_json_serializable(self) -> None:
        for name in ("status", "capabilities", "refs"):
            with self.subTest(name):
                json.dumps(call_json(self.pipeline, name))

    def test_a_stateless_prompt_dispatches_like_the_bound_one(self) -> None:
        """`prompt` runs before a modlet exists, so it must work without config."""
        stateless = call_json(None, "prompt", {"kind": "item-icon", "subject": "a nuke"})
        bound = self.pipeline.call("prompt", {"kind": "item-icon", "subject": "a nuke"})
        self.assertEqual(stateless, bound)
        self.assertIn("Asset type:", stateless["prompt"])

    def test_client_where_resolves_paths_from_an_explicit_game_dir(self) -> None:
        import tempfile as tempdir

        with tempdir.TemporaryDirectory() as game:
            data = call_json(None, "client_where", {"game_dir": str(Path(game) / "7 Days To Die")})
            self.assertIsNone(data["mods_dir"])  # not a Steam library layout
            self.assertEqual(["steam", "-applaunch", "251570"], data["launch"][:3])


def _nested(response: dict[str, object], key: str) -> dict[str, object]:
    """The protocol nests one object under 'result' or 'error'."""
    return cast("dict[str, object]", response[key])


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

    def _run(self, *requests: object, allow_writes: bool = False) -> list[dict[str, object]]:
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
        operations = cast("list[object]", _nested(response, "result")["operations"])
        self.assertEqual(len(OPERATIONS), len(operations))

    def test_writes_are_refused_unless_explicitly_allowed(self) -> None:
        (response,) = self._run({"id": 1, "op": "build", "params": {"probe": True}})
        self.assertFalse(response["ok"])
        self.assertIn("read-only", cast(str, _nested(response, "error")["message"]))

    def test_a_bad_line_does_not_desynchronize_the_session(self) -> None:
        output = io.StringIO()
        stream = io.StringIO('not json\n{"id":2,"op":"ping"}\n')
        serve(lambda: self.pipeline, False, stream, output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(2, len(responses))
        self.assertFalse(responses[0]["ok"])
        self.assertTrue(responses[1]["ok"], "the session must survive a malformed request")

    def test_falsy_non_object_params_are_refused(self) -> None:
        """`params: []` or `""` is not an absent params object.

        Coercing every falsy value to `{}` made the declared type error
        unreachable for exactly those and ran the operation with schema
        defaults instead, so a caller that serialized an argument list got a
        different operation than the one it named.
        """
        for value in cast("list[object]", [[], "", 0, False]):
            with self.subTest(params=value):
                response = handle(
                    {"id": 1, "op": "check_mesh", "params": value}, lambda: self.pipeline, False
                )
                self.assertFalse(response["ok"])
                self.assertIn(
                    "must be a JSON object", cast(str, _nested(response, "error")["message"])
                )

    def test_absent_params_is_an_empty_object(self) -> None:
        response = handle({"id": 1, "op": "capabilities"}, lambda: self.pipeline, False)
        self.assertTrue(response["ok"])

    def test_non_object_request_is_an_error_not_a_crash(self) -> None:
        response = handle([1, 2, 3], lambda: self.pipeline, False)
        self.assertFalse(response["ok"])
        self.assertIn("JSON object", cast(str, _nested(response, "error")["message"]))

    def test_errors_carry_a_type_and_message(self) -> None:
        (response,) = self._run({"id": 1, "op": "validate"})
        self.assertFalse(response["ok"])
        self.assertEqual("PipelineError", _nested(response, "error")["type"])
        self.assertTrue(_nested(response, "error")["message"])


def _annotation_types(annotation: object, builtin: tuple[type, ...]) -> list[type]:
    """The concrete classes named by a return annotation, containers included."""
    found: list[type] = []
    if typing.get_origin(annotation) is not None:
        for argument in typing.get_args(annotation):
            found.extend(_annotation_types(argument, builtin))
    elif isinstance(annotation, type) and not issubclass(annotation, builtin):
        found.append(annotation)
    return found


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
                            alias.name.startswith("sevendtd_asset_pipeline") for alias in sub.names
                        )
                    )
                    if bad:
                        line = getattr(sub, "lineno", "?")
                        self.fail(
                            f"{path.relative_to(root)}:{line}: "
                            f"intra-package import inside {node.name}()"
                        )

    def test_every_pipeline_result_type_is_importable_from_the_package_root(self) -> None:
        """Every type a `Pipeline` method hands back is a supported import.

        `check_texture` returned a `TextureReport` the root package never
        re-exported, so the documented type was unimportable and a consumer
        had to reach into `sevendtd_asset_pipeline.colour` for it, past the
        line the package draws around what is supported.
        """
        import pathlib

        import sevendtd_asset_pipeline as package

        supported = set(package.__all__)
        builtin = (pathlib.PurePath, str, int, float, bool, object, type(None), typing.Any)
        for name in sorted(dir(Pipeline)):
            if name.startswith("_"):
                continue
            method = getattr(Pipeline, name)
            if not callable(method):
                continue
            returns = typing.get_type_hints(method).get("return")
            for named in _annotation_types(returns, builtin):
                with self.subTest(method=name, type=named.__name__):
                    self.assertIn(named.__name__, supported)

    def test_every_documented_pipeline_method_exists(self) -> None:
        """The Python table in docs/consumer-api.md is the hand-off surface.

        A method that exists but is unlisted is one a consumer does not know
        it has, which is the same defect as one that does not exist.
        """
        root = Path(__file__).resolve().parent.parent
        page_file = root / "docs" / "consumer-api.md"
        if not page_file.is_file():
            self.skipTest("running from a packaged install without the repository")
        table = page_file.read_text(encoding="utf-8")
        documented = set(re.findall(r"^\| `\.([a-z_]+)\(", table, re.MULTILINE))
        self.assertTrue(documented, "the Pipeline method table is empty")
        for name in sorted(set(dir(Pipeline)) - set(documented) - {"scaffold", "discover"}):
            if not name.startswith("_") and callable(getattr(Pipeline, name)):
                self.fail(f"Pipeline.{name} is not listed in docs/consumer-api.md")

    def test_every_documented_signature_names_a_real_parameter(self) -> None:
        """A documented call is copied verbatim, so its names must bind.

        The page listed `.check_mesh(path, …)`, `.check_sound(path, …)` and
        `initialize(root, …)` for callables that name those parameters `mesh`,
        `clip`, `mod_root` and `unity_version`. Every one of them works
        positionally and fails as a keyword call, which is how every example
        in the file spells it.
        """
        import inspect

        import sevendtd_asset_pipeline as package

        root = Path(__file__).resolve().parent.parent
        page_file = root / "docs" / "consumer-api.md"
        if not page_file.is_file():
            self.skipTest("running from a packaged install without the repository")
        for line in page_file.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| `"):
                continue
            for dotted, arguments in re.findall(r"`(\.?[A-Za-z_][A-Za-z_0-9.]*)\(([^`]*)\)`", line):
                if dotted.startswith("."):
                    owner: object = Pipeline
                    name = dotted.lstrip(".")
                elif dotted.startswith("Pipeline."):
                    owner, name = Pipeline, dotted.removeprefix("Pipeline.")
                elif dotted in set(package.__all__):
                    owner, name = package, dotted
                else:
                    continue
                target = getattr(owner, name, None)
                if not callable(target):
                    continue
                parameters = inspect.signature(target).parameters
                for written in arguments.split(","):
                    argument = written.strip().lstrip("*")
                    if not argument or argument in ("…", "..."):
                        continue
                    keyword = argument.split("=")[0].split(":")[0].strip()
                    with self.subTest(documented=f"{name}({keyword})"):
                        self.assertIn(keyword, parameters)

    def test_registry_reads_the_version_without_importing_upward(self) -> None:
        from sevendtd_asset_pipeline import operations

        source = Path(operations.__file__).read_text(encoding="utf-8")
        self.assertNotIn("from . import", source)
        self.assertIn("from ._version import __version__", source)
        self.assertEqual(manifest()["version"], __import__("sevendtd_asset_pipeline").__version__)


if __name__ == "__main__":
    unittest.main()
