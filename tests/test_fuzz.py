"""Property-based fuzzing of the two untrusted-input parsers.

Both harnesses cross a trust boundary, which is what makes them worth running
under a generator rather than as a handful of hand-written cases:

- `unityfs.bundle_info` maps a `unityz info --json` report onto `BundleInfo`.
  unityz is a separately versioned reader speaking to the Python gate over a
  pipe, so every field is foreign, and a malformed report must end as an
  actionable `PipelineError` rather than a traceback from the mapping layer.
- `references` parses the mod's own `Config/**.xml`, `ModInfo.xml` and
  tracked manifest, all of which arrive from a modlet this repository did not
  write.

A fuzzer proves a bug exists; the assertions here are what make a *correct*
parser's output into a liveness failure when it stops being one, so the
harness reports a broken invariant rather than a silent drift. Seeds are real
shapes from the parsers' own tests, not zero-filled input: a generator that
never reaches the accepting branch proves nothing about it.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from hypothesis import example, given, settings
from hypothesis import strategies as st

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.references import (
    MODFOLDER,
    AssetReference,
    manifest_assets,
    parse_reference,
    read_mod_info,
)
from sevendtd_asset_pipeline.unityfs import ASSET_BUNDLE_CLASS_ID, bundle_info

# Neither parser touches the filesystem, so the subjects are names, not files.
BUNDLE = Path("fuzz-bundle.unity3d")
SOURCE = Path("Config/items.xml")

# Enough structure to reach every branch of both parsers without shrinking the
# report so far that a malformed node list is never generated.
MAX_EXAMPLES = 400

json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(max_size=16),
    st.floats(allow_nan=True, allow_infinity=True),
)
json_values = st.recursive(
    json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=6), children, max_size=4),
    ),
    max_leaves=12,
)
json_objects = st.dictionaries(st.text(max_size=8), json_values, min_size=0, max_size=6)

uri_bodies = st.text(max_size=40)
manifest_lines = st.lists(st.text(max_size=24), max_size=8)
mod_info_xml = st.builds(
    lambda body: f"<ModInfo>{body}</ModInfo>",
    st.lists(st.text(max_size=32), max_size=4),
)

# Pure JSON generation almost never builds a report a reader accepts: the
# node list, the SerializedFile metadata and the class IDs each have to be
# present, nested and correctly typed at once. This strategy builds those
# shapes first and then breaks one field at a time, so both the accepting
# branch and every rejection it must be able to reach are sampled directly.
REVISIONS = ("2022.3.62f2", "2021.3.1f1")
# Each field is generated valid more often than not: a report only reaches the
# accepting branch when every field is valid at once, so an all-broken strategy
# would fuzz the rejection path and never the one the gate runs on.
class_ids = st.one_of(
    st.lists(st.integers(min_value=0, max_value=2048), max_size=4),
    st.lists(st.one_of(st.text(max_size=3), st.none(), st.booleans()), max_size=3),
    st.text(max_size=4),
    st.none(),
)
revisions = st.one_of(
    st.sampled_from(REVISIONS),
    st.text(max_size=8),
    st.integers(),
    st.just(""),
)
serialized_metadata = st.fixed_dictionaries(
    {},
    optional={
        "unity": revisions,
        "class_ids": class_ids,
        "path": st.text(max_size=4),
    },
)
node_values = st.one_of(
    st.builds(
        lambda metadata: {"path": "CAB-0123456789abcdef", "serialized": metadata},
        serialized_metadata,
    ),
    st.builds(
        lambda revision, ids: {"serialized": {"unity": revision, "class_ids": ids}},
        st.sampled_from(REVISIONS),
        st.lists(st.integers(min_value=0, max_value=2048), max_size=4),
    ),
    st.fixed_dictionaries({}, optional={"serialized": serialized_metadata}),
    st.just({"serialized": None}),
    st.just({}),
    st.text(max_size=4),
    st.none(),
)
unityz_reports = st.builds(
    lambda report_type, version, nodes: {
        "type": report_type,
        "version": version,
        "nodes_list": nodes,
    },
    st.sampled_from(("UnityFS", "UnityFS", "UnityFS", "SerializedFile", "", 7)),
    st.one_of(st.integers(min_value=-2, max_value=64), st.text(max_size=3), st.none()),
    st.lists(node_values, max_size=3),
)
reports = st.one_of(json_objects, unityz_reports)


def unityz_report(revision: str, class_ids: list[object]) -> dict[str, object]:
    """The report shape unityz prints for a real generated bundle."""
    return {
        "type": "UnityFS",
        "version": 8,
        "nodes_list": [
            {
                "path": "CAB-0123456789abcdef0123456789abcdef",
                "serialized": {"unity": revision, "class_ids": class_ids},
            }
        ],
    }


def multi_node_report(revisions: list[str], class_ids: list[object]) -> dict[str, object]:
    """One UnityFS container over several SerializedFiles, as unityz reports it."""
    return {
        "type": "UnityFS",
        "version": 8,
        "nodes_list": [
            {"path": f"CAB-{index:032x}", "serialized": {"unity": rev, "class_ids": class_ids}}
            for index, rev in enumerate(revisions)
        ],
    }


class UnityzReportMappingTests(unittest.TestCase):
    """`unityfs.bundle_info` over arbitrary unityz JSON reports."""

    @example(report=unityz_report("2022.3.62f2", [142, 28]))
    @example(report=unityz_report("", [142]))
    @example(report=unityz_report("2022.3.62f2", [142, "28"]))
    @example(report={"type": "UnityFS", "version": 8, "nodes_list": []})
    @example(report={"type": "UnityFS", "version": 8, "nodes_list": [{}, 7]})
    @example(report={"type": "UnityFS", "nodes_list": [{"serialized": {"unity": "a"}}]})
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(report=reports)
    def test_mapping_is_total_and_its_result_is_well_formed(self, report: dict[str, Any]) -> None:
        try:
            info = bundle_info(report, BUNDLE)
        except PipelineError:
            return
        except Exception as exc:  # noqa: BLE001 - the finding this harness exists for
            self.fail(f"bundle_info raised {type(exc).__name__} on {report!r}: {exc}")

        self.assertIsInstance(info.unity_version, str)
        self.assertTrue(info.unity_version, f"empty revision accepted from {report!r}")
        self.assertIsInstance(info.archive_format, int)
        self.assertNotIsInstance(info.archive_format, bool)
        self.assertEqual(
            len(set(info.class_ids)),
            len(info.class_ids),
            f"duplicate class IDs survived into {info.class_ids!r}",
        )
        for class_id in info.class_ids:
            self.assertIsInstance(class_id, int)
            self.assertNotIsInstance(class_id, bool)
        self.assertEqual(
            info.has_assetbundle_object,
            ASSET_BUNDLE_CLASS_ID in info.class_ids,
        )
        self.assertIs(info.path, BUNDLE)

    @example(report=multi_node_report(["2022.3.62f2"], [1, 142]))
    @example(report=multi_node_report(["2022.3.62f2", "2022.3.62f2"], [1, 142]))
    # Two SerializedFiles of different revisions: the case that must be
    # rejected, pinned so the generator cannot simply stop producing it.
    @example(report=multi_node_report(["2022.3.62f2", "2021.3.1f1"], [142]))
    @example(
        report={
            "type": "UnityFS",
            "version": 8,
            "nodes_list": [
                {"serialized": {"unity": "2022.3.62f2", "class_ids": [1, 142]}},
                {"serialized": {"unity": "2022.3.62f2", "class_ids": [142, 28]}},
            ],
        }
    )
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(report=reports)
    def test_a_bundle_is_accepted_only_when_every_node_agrees(self, report: dict[str, Any]) -> None:
        """Two SerializedFiles of one revision merge; anything else is rejected.

        This is the class-142 gate's own precondition, so it is asserted
        rather than left to the fuzzer: a mapping that accepted mixed
        revisions would report a bundle the installed game cannot load.
        """
        try:
            bundle_info(report, BUNDLE)
        except PipelineError:
            return
        nodes = report.get("nodes_list")
        if not isinstance(nodes, list):
            self.fail(f"accepted a report with no node list: {report!r}")
        revisions = {
            node["serialized"]["unity"]
            for node in nodes
            if isinstance(node, dict)
            and isinstance(node.get("serialized"), dict)
            and isinstance(node["serialized"].get("unity"), str)
        }
        self.assertLessEqual(len(revisions), 1, f"mixed revisions accepted from {report!r}")


class ModReferenceParsingTests(unittest.TestCase):
    """`references` over arbitrary URIs, manifests and ModInfo.xml documents."""

    def setUp(self) -> None:
        # One directory per test rather than per generated example: a fresh
        # TemporaryDirectory per example costs more than the parser it feeds,
        # and these tests already run hundreds of examples.
        self._scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self._scratch.cleanup)
        self._writes = 0

    def _subject(self, name: str, text: str) -> Path:
        self._writes += 1
        path = Path(self._scratch.name) / f"{self._writes:06d}-{name}"
        path.write_text(text, encoding="utf-8")
        return path

    @example(uri="#@modfolder():assets/items.unity3d?myItem")
    @example(uri="#@modfolder(MyMod):assets/items.unity3d?myItem")
    @example(uri="#no-question-mark")
    @example(uri="#?")
    @example(uri="#@modfolder():x?")
    @example(uri="#@modfolder():#?a")
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(uri=uri_bodies)
    def test_uri_parsing_is_total_and_its_result_is_internally_consistent(self, uri: str) -> None:
        try:
            reference = parse_reference(SOURCE, uri)
        except PipelineError:
            return
        except Exception as exc:  # noqa: BLE001 - the finding this harness exists for
            self.fail(f"parse_reference raised {type(exc).__name__} on {uri!r}: {exc}")

        self.assertIsInstance(reference, AssetReference)
        self.assertEqual(reference.source, SOURCE)
        self.assertEqual(reference.uri, uri)
        body, separator, asset = uri[1:].partition("?")
        self.assertTrue(separator and asset, f"accepted a URI with no asset: {uri!r}")
        self.assertEqual(reference.asset_name, asset)
        self.assertEqual(reference.is_modfolder, MODFOLDER.search(body) is not None)
        if reference.is_modfolder:
            # The token is rewritten away before the path reaches the filesystem.
            self.assertNotIn("@modfolder", reference.bundle_path.lower())
            self.assertTrue(reference.mod_name is None or reference.mod_name)
        else:
            self.assertIsNone(reference.mod_name)
            self.assertEqual(reference.bundle_path, body)
        self.assertEqual(
            reference.asset_stem,
            Path(reference.asset_name.replace("\\", "/")).stem,
        )

    @example(lines=["Assets:", "- shamwayselftest"])
    @example(lines=["Assets:"])
    @example(lines=["- only-a-list"])
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(lines=manifest_lines)
    def test_manifest_parsing_is_total_and_never_returns_empty_entries(
        self, lines: list[str]
    ) -> None:
        manifest = self._subject("manifest.txt", "\n".join(lines))
        try:
            assets = manifest_assets(manifest)
        except PipelineError:
            return
        except Exception as exc:  # noqa: BLE001 - the finding this harness exists for
            self.fail(f"manifest_assets raised {type(exc).__name__} on {lines!r}: {exc}")
        self.assertTrue(assets, "manifest_assets returned an empty list instead of an error")
        for entry in assets:
            self.assertIsInstance(entry, str)
            self.assertTrue(entry.strip(), f"blank manifest entry from {lines!r}")

    @example(document='<ModInfo><Name value="SelfTestMod"/><Version value="1.0.0"/></ModInfo>')
    @example(document="<ModInfo></ModInfo>")
    @example(document='<ModInfo><Name value=""/></ModInfo>')
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(document=mod_info_xml)
    def test_mod_info_parsing_is_total_and_always_names_the_mod(self, document: str) -> None:
        mod_info = self._subject("ModInfo.xml", document)
        try:
            info = read_mod_info(mod_info)
        except PipelineError:
            return
        except Exception as exc:  # noqa: BLE001 - the finding this harness exists for
            self.fail(f"read_mod_info raised {type(exc).__name__} on {document!r}: {exc}")
        self.assertTrue(info.name.strip(), f"blank mod name accepted from {document!r}")


if __name__ == "__main__":
    unittest.main()
