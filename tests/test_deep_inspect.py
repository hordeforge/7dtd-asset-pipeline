"""deep_inspect must not hold the bundle's descriptor after it returns.

UnityPy keeps every loaded file open inside a reference-cyclic reader graph,
and its Environment has no close(): loading from a path left one descriptor
behind per call until the cyclic collector happened to run. Inside a long-lived
`shamway serve` session that is an accumulation on every inspect_deep request.
deep_inspect now hands UnityPy bytes instead, so no descriptor is ever held;
this test pins that with the cycle collector switched off, so any return to
path-based loading fails here rather than silently re-leaking.
"""

from __future__ import annotations

import gc
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sevendtd_asset_pipeline.bundle_writer import build_bundle, text_asset
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.deep_inspect import _walk, deep_inspect
from sevendtd_asset_pipeline.errors import PipelineError

REVISION = "2022.3.62f2"


def open_descriptor_count() -> int | None:
    """How many descriptors this process holds, or None off /proc hosts."""
    directory = "/proc/self/fd"
    if not os.path.isdir(directory):
        return None
    return len(os.listdir(directory))


@unittest.skipUnless(has_capability("UnityPy"), "deep_inspect needs UnityPy")
class DeepInspectResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "inspect.unity3d"
        self.bundle.write_bytes(
            build_bundle([text_asset("myModNote", "hello")], REVISION, "inspect.unity3d")
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_repeated_inspections_do_not_accumulate_descriptors(self) -> None:
        before = open_descriptor_count()
        if before is None:
            self.skipTest("no /proc/self/fd on this host")
        # Collector off: refcounting alone must reclaim everything the call
        # acquired, because nothing outside the call can reach it.
        gc.disable()
        try:
            report = None
            for _ in range(50):
                report = deep_inspect(self.bundle)
            assert report is not None, "deep_inspect returned no report in 50 runs"
            self.assertEqual(["mymodnote"], [entry.asset_stem for entry in report.entries])
        finally:
            gc.enable()
        after = open_descriptor_count()
        assert after is not None  # `before` already proved /proc/self/fd exists
        # Not `assertEqual`: the count is process-wide, so a descriptor another
        # test left reachable can be released *during* this one and the total
        # drops. CI caught exactly that — 10 before, 7 after — and a decrease
        # is not the failure this test is named for. Accumulation is, and 50
        # iterations make even a one-per-call leak show as +50.
        self.assertLessEqual(
            after, before, f"deep_inspect accumulated {after - before} descriptors"
        )

    def test_a_missing_bundle_is_a_pipeline_error_not_a_raw_os_error(self) -> None:
        # deep_inspect is diagnostic: every failure it reports must be
        # actionable (PipelineError), never a bare OSError from UnityPy.
        with self.assertRaisesRegex(PipelineError, "no such file"):
            deep_inspect(self.root / "absent.unity3d")


def _pointer(name: str) -> SimpleNamespace:
    """A component reference the way UnityPy hands one over."""
    return SimpleNamespace(type=SimpleNamespace(name=name))


class _Transform(SimpleNamespace):
    """A Transform pointer whose read() answers its children."""

    def __init__(self, children: list[object] | None = None) -> None:
        super().__init__(type=SimpleNamespace(name="Transform"))
        self.children = list(children or [])

    def read(self) -> SimpleNamespace:
        return SimpleNamespace(m_Children=list(self.children))


def _game_object(*component_names: str, transform: _Transform | None = None) -> SimpleNamespace:
    components = [_pointer(name) for name in component_names]
    if transform is not None:
        components.append(transform)
    return SimpleNamespace(m_Component=[SimpleNamespace(component=c) for c in components])


def _child_link(child_object: SimpleNamespace) -> SimpleNamespace:
    """A m_Children entry: read().m_GameObject.read() yields the child."""

    def read() -> SimpleNamespace:
        pointer = SimpleNamespace(read=lambda: child_object)
        return SimpleNamespace(m_GameObject=pointer)

    return SimpleNamespace(read=read)


class WalkCensusTests(unittest.TestCase):
    """The per-prefab component census, against duck-typed stand-ins.

    `_walk` is the part of deep_inspect that answers "did my ParticleSystem
    survive serialization": it must count across the whole hierarchy (a root
    usually carries only its Transform), survive an unreadable component or
    child, and stop a cyclic or absurdly deep chain instead of recursing
    forever. deep_inspect() itself needs UnityPy and a real bundle; this logic
    only needs objects shaped like the ones it reads, so it is pinned here.
    """

    def test_the_census_reaches_the_children_where_components_live(self) -> None:
        leaf = _game_object("ParticleSystem", "Renderer", transform=_Transform())
        middle = _game_object("AudioSource", transform=_Transform(children=[_child_link(leaf)]))
        root = _game_object(transform=_Transform(children=[_child_link(middle)]))
        counts, total, skipped = _walk(root)
        self.assertEqual(3, total)
        self.assertEqual(0, skipped)
        self.assertEqual(
            {"Transform": 3, "ParticleSystem": 1, "Renderer": 1, "AudioSource": 1},
            dict(counts),
        )

    def test_a_root_without_a_transform_counts_itself_only(self) -> None:
        counts, total, skipped = _walk(_game_object("MonoBehaviour"))
        self.assertEqual(({"MonoBehaviour": 1}, 1, 0), (dict(counts), total, skipped))

    def test_a_component_that_cannot_be_read_is_skipped_not_fatal(self) -> None:
        game_object = SimpleNamespace(m_Component=[object()])  # no .component attribute
        counts, total, skipped = _walk(game_object)
        self.assertEqual(({}, 1, 0), (dict(counts), total, skipped))

    def test_an_unreadable_child_is_skipped_and_its_siblings_still_count(self) -> None:
        good = _game_object("Light", transform=_Transform())

        class _TornChild:
            def read(self) -> object:
                raise RuntimeError("torn object")

        root = _game_object(transform=_Transform(children=[_TornChild(), _child_link(good)]))
        counts, total, skipped = _walk(root)
        self.assertEqual(2, total, "root plus only the readable child")
        self.assertEqual(1, skipped, "the torn child must be counted as skipped")
        self.assertEqual({"Transform": 2, "Light": 1}, dict(counts))

    def test_a_deep_chain_terminates_instead_of_recurring_forever(self) -> None:
        """A malformed hierarchy must not become infinite recursion."""
        depth = 200
        leaf = _game_object(transform=_Transform())
        for _ in range(depth - 1):
            leaf = _game_object(transform=_Transform(children=[_child_link(leaf)]))
        root = leaf
        counts, total, skipped = _walk(root)
        # The guard counts components through depth 64, then stops at depth 65.
        # The total still records that bounded final visit.
        self.assertEqual(65, counts.get("Transform", 0))
        self.assertEqual(66, total)
        self.assertEqual(0, skipped)


if __name__ == "__main__":
    unittest.main()
