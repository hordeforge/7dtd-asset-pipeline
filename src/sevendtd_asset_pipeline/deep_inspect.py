"""Per-object and per-prefab bundle inspection through the pinned unityz CLI.

The public report stays Python data, but Unity container parsing, object
decoding, hierarchy recovery, and self-verification have one owner: unityz.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .errors import PipelineError
from .unityz import Unityz


@dataclass
class BundleEntry:
    """One addressable asset in the bundle, as the runtime will see it."""

    container_path: str
    type: str
    object_name: str
    asset_stem: str
    object_count: int = 1
    components: dict[str, int] = field(default_factory=dict)
    partial: bool = False


@dataclass
class DeepReport:
    path: str
    object_count: int
    type_counts: dict[str, int]
    entries: list[BundleEntry]
    skipped_children: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "object_count": self.object_count,
            "type_counts": self.type_counts,
            "entries": [asdict(entry) for entry in self.entries],
            "skipped_children": self.skipped_children,
        }


@dataclass(frozen=True)
class _Object:
    node: str | None
    path_id: int
    class_id: int
    name: str


def _integer(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PipelineError(f"unityz omitted integer {field_name} from deep inspection")
    return value


def _objects(report: dict[str, object]) -> list[_Object]:
    raw_objects = report.get("object_list")
    if not isinstance(raw_objects, list):
        raise PipelineError("unityz info omitted object_list from deep inspection")
    objects: list[_Object] = []
    for raw in raw_objects:
        if not isinstance(raw, dict):
            raise PipelineError("unityz info returned a malformed object_list entry")
        node = raw.get("node")
        if node is not None and not isinstance(node, str):
            raise PipelineError("unityz info returned a malformed object node")
        name = raw.get("name", "")
        if not isinstance(name, str):
            raise PipelineError("unityz info returned a malformed object name")
        objects.append(
            _Object(
                node=node,
                path_id=_integer(raw.get("path_id"), "object path_id"),
                class_id=_integer(raw.get("class"), "object class"),
                name=name,
            )
        )
    return objects


def _require_embedded_type_trees(report: dict[str, object], path: Path) -> None:
    raw_nodes = report.get("nodes_list")
    if not isinstance(raw_nodes, list):
        raise PipelineError("unityz info omitted the node list from deep inspection")
    found = False
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            raise PipelineError("unityz info returned a malformed deep-inspection node")
        serialized = raw_node.get("serialized")
        if serialized is None:
            continue
        found = True
        if not isinstance(serialized, dict) or not isinstance(serialized.get("type_tree"), bool):
            raise PipelineError("unityz info omitted the SerializedFile type-tree state")
        if not serialized["type_tree"]:
            raise PipelineError(
                f"shamway inspect --deep refuses {path}: it has stripped type trees, "
                "and pinned unityz has no built-in release-indexed tree source yet; "
                "this UnityPy-covered case is recorded in the unityz capability audit"
            )
    if not found:
        raise PipelineError(f"unityz found no SerializedFile to inspect deeply in {path}")


def _type_census(report: dict[str, object]) -> tuple[int, dict[int, str], dict[str, int]]:
    object_count = _integer(report.get("objects"), "stats object count")
    raw_classes = report.get("classes")
    if not isinstance(raw_classes, dict):
        raise PipelineError("unityz stats omitted the class census")
    names: dict[int, str] = {}
    counts: Counter[str] = Counter()
    for raw_class_id, raw in raw_classes.items():
        if not isinstance(raw_class_id, str) or not isinstance(raw, dict):
            raise PipelineError("unityz stats returned a malformed class census")
        try:
            class_id = int(raw_class_id)
        except ValueError as exc:
            raise PipelineError("unityz stats returned a non-numeric class ID") from exc
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise PipelineError("unityz stats omitted a class name")
        names[class_id] = name
        counts[name] += _integer(raw.get("count"), f"{name} count")
    return object_count, names, dict(sorted(counts.items()))


def _container_entries(value: dict[str, object]) -> dict[str, tuple[int, int]]:
    raw_entries = value.get("m_Container")
    if not isinstance(raw_entries, list):
        raise PipelineError("unityz show omitted AssetBundle.m_Container")
    entries: dict[str, tuple[int, int]] = {}
    for raw in raw_entries:
        if not isinstance(raw, list) or len(raw) != 2 or not isinstance(raw[0], str):
            raise PipelineError("unityz show returned a malformed AssetBundle container entry")
        preload = raw[1]
        if not isinstance(preload, dict):
            raise PipelineError("unityz show returned a malformed AssetBundle preload entry")
        asset = preload.get("asset")
        if not isinstance(asset, dict):
            raise PipelineError("unityz show omitted an AssetBundle entry pointer")
        entries[raw[0]] = (
            _integer(asset.get("m_FileID"), "AssetBundle m_FileID"),
            _integer(asset.get("m_PathID"), "AssetBundle m_PathID"),
        )
    return entries


def _hierarchy_index(
    documents: list[dict[str, object]],
) -> tuple[dict[tuple[str | None, int], dict[str, object]], dict[str | None, int]]:
    index: dict[tuple[str | None, int], dict[str, object]] = {}
    document_skips: dict[str | None, int] = {}

    def add(node_name: str | None, raw: object) -> None:
        if not isinstance(raw, dict):
            raise PipelineError("unityz hierarchy returned a malformed node")
        game_object = _integer(raw.get("gameObject"), "hierarchy gameObject")
        index[(node_name, game_object)] = raw
        children = raw.get("children")
        if not isinstance(children, list):
            raise PipelineError("unityz hierarchy omitted a child list")
        for child in children:
            add(node_name, child)

    for document in documents:
        node_name = document.get("node")
        if node_name is not None and not isinstance(node_name, str):
            raise PipelineError("unityz hierarchy returned a malformed container node")
        roots = document.get("hierarchy")
        if not isinstance(roots, list):
            raise PipelineError("unityz hierarchy omitted its root list")
        document_skips[node_name] = _integer(
            document.get("skipped_children"), "hierarchy skipped_children"
        )
        for root in roots:
            add(node_name, root)
    return index, document_skips


def _walk_hierarchy(
    raw: dict[str, object], class_names: dict[int, str], depth: int = 0
) -> tuple[Counter[str], int]:
    """Count GameObjects and components with the old report's depth bound."""
    if depth > 64:
        return Counter(), 1
    raw_components = raw.get("components")
    raw_children = raw.get("children")
    if not isinstance(raw_components, list) or not isinstance(raw_children, list):
        raise PipelineError("unityz hierarchy returned a malformed prefab node")
    counts: Counter[str] = Counter()
    for raw_class_id in raw_components:
        class_id = _integer(raw_class_id, "hierarchy component class")
        counts[class_names.get(class_id, f"Class{class_id}")] += 1
    total = 1
    for child in raw_children:
        if not isinstance(child, dict):
            raise PipelineError("unityz hierarchy returned a malformed prefab child")
        child_counts, child_total = _walk_hierarchy(child, class_names, depth + 1)
        counts += child_counts
        total += child_total
    return counts, total


def _verification_failures(
    report: dict[str, object], objects: list[_Object]
) -> set[tuple[str | None, int]]:
    raw_failures = report.get("failures")
    if not isinstance(raw_failures, list):
        raise PipelineError("unityz verify omitted its failure list")
    failed: set[tuple[str | None, int]] = set()
    for raw in raw_failures:
        if not isinstance(raw, dict):
            raise PipelineError("unityz verify returned a malformed failure")
        node = raw.get("node")
        if node is not None and not isinstance(node, str):
            raise PipelineError("unityz verify returned a malformed failure node")
        path_id = _integer(raw.get("path_id"), "verification path_id")
        if path_id == -1:
            failed.update((item.node, item.path_id) for item in objects if item.node == node)
        else:
            failed.add((node, path_id))
    if _integer(report.get("skipped"), "verification skipped count"):
        # A typeless object has no per-object record in the current unityz
        # report. Conservatively mark all entries; the documented built-in
        # type-tree gap must never read as a complete inspection.
        failed.update((item.node, item.path_id) for item in objects)
    return failed


def deep_inspect(path: Path) -> DeepReport:
    path = path.resolve()
    reader = Unityz(path)
    info = reader.json("info", "--json", "--objects")
    _require_embedded_type_trees(info, path)
    objects = _objects(info)
    stats = reader.json("stats", "--json")
    object_count, class_names, type_counts = _type_census(stats)
    hierarchy, document_skips = _hierarchy_index(reader.json_lines("hierarchy", "--json"))
    failed = _verification_failures(reader.json_report("verify", "--json"), objects)
    by_key = {(item.node, item.path_id): item for item in objects}

    container: dict[str, tuple[str | None, int, int]] = {}
    for asset_bundle in (item for item in objects if item.class_id == 142):
        selector = (
            f"{asset_bundle.node}:{asset_bundle.path_id}"
            if asset_bundle.node is not None
            else str(asset_bundle.path_id)
        )
        value = reader.json("show", selector)
        for container_path, (file_id, path_id) in _container_entries(value).items():
            container[container_path] = (asset_bundle.node, file_id, path_id)

    entries: list[BundleEntry] = []
    skipped_children = 0
    for container_path, (node, file_id, path_id) in sorted(container.items()):
        target = by_key.get((node, path_id)) if file_id == 0 else None
        partial = target is None
        type_name = (
            class_names.get(target.class_id, f"Class{target.class_id}") if target else "Unknown"
        )
        object_name = target.name if target else ""
        object_count_for_entry = 1
        components: dict[str, int] = {}
        if target is not None:
            partial = partial or (target.node, target.path_id) in failed
            if target.class_id == 1:
                root = hierarchy.get((target.node, target.path_id))
                if root is None:
                    partial = True
                else:
                    counts, object_count_for_entry = _walk_hierarchy(root, class_names)
                    components = dict(sorted(counts.items()))
                    root_skips = _integer(root.get("skipped_children"), "prefab skipped_children")
                    skipped_children += root_skips
                    partial = partial or root_skips != 0
        entries.append(
            BundleEntry(
                container_path=container_path,
                type=type_name,
                object_name=object_name,
                asset_stem=Path(container_path).stem,
                object_count=object_count_for_entry,
                components=components,
                partial=partial,
            )
        )

    # A document-level omission outside every addressable prefab cannot be
    # assigned to an entry, but still belongs in the report's global signal.
    assigned = skipped_children
    total_document_skips = sum(document_skips.values())
    skipped_children += max(0, total_document_skips - assigned)
    return DeepReport(
        path=str(path),
        object_count=object_count,
        type_counts=type_counts,
        entries=entries,
        skipped_children=skipped_children,
    )
