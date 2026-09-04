"""UnityFS and SerializedFile metadata read through the pinned unityz CLI.

The pipeline keeps its small public ``BundleInfo`` value, while unityz owns
container decompression, format bounds, and SerializedFile parsing. That makes
the gate and the diagnostic commands use the same reader.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import PipelineError
from .unityz import run_json

ASSET_BUNDLE_CLASS_ID = 142


@dataclass(frozen=True)
class BundleInfo:
    path: Path
    unity_version: str
    archive_format: int
    class_ids: tuple[int, ...]

    @property
    def has_assetbundle_object(self) -> bool:
        return ASSET_BUNDLE_CLASS_ID in self.class_ids


def _integer(value: object, field: str, path: Path) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PipelineError(f"unityz info omitted integer {field} metadata for {path}")
    return value


def _serialized_nodes(report: dict[str, object], path: Path) -> list[dict[str, object]]:
    raw_nodes = report.get("nodes_list")
    if not isinstance(raw_nodes, list):
        raise PipelineError(f"unityz info omitted the UnityFS node list for {path}")
    serialized: list[dict[str, object]] = []
    for node in raw_nodes:
        if not isinstance(node, dict):
            raise PipelineError(f"unityz info returned a malformed UnityFS node for {path}")
        metadata = node.get("serialized")
        if metadata is None:
            continue
        if not isinstance(metadata, dict):
            raise PipelineError(
                f"unityz info returned malformed SerializedFile metadata for {path}"
            )
        serialized.append(metadata)
    if not serialized:
        raise PipelineError(f"{path} has no SerializedFile nodes")
    return serialized


def inspect_bundle(path: Path) -> BundleInfo:
    """Read the bundle revision and serialized class IDs through unityz."""
    path = path.resolve()
    try:
        report = run_json("info", path, "--json")
    except PipelineError as exc:
        if not path.is_file():
            raise
        message = f"{path} is not a UnityFS asset bundle readable by unityz: {exc}"
        raise PipelineError(message) from exc
    if report.get("type") != "UnityFS":
        raise PipelineError(f"{path} is not a UnityFS asset bundle")

    revisions: list[str] = []
    class_ids: list[int] = []
    seen_class_ids: set[int] = set()
    for serialized in _serialized_nodes(report, path):
        revision = serialized.get("unity")
        if not isinstance(revision, str) or not revision:
            raise PipelineError(f"unityz info omitted the SerializedFile revision for {path}")
        revisions.append(revision)
        raw_class_ids = serialized.get("class_ids")
        if not isinstance(raw_class_ids, list):
            raise PipelineError(f"unityz info omitted SerializedFile class IDs for {path}")
        for raw_class_id in raw_class_ids:
            class_id = _integer(raw_class_id, "class ID", path)
            if class_id not in seen_class_ids:
                seen_class_ids.add(class_id)
                class_ids.append(class_id)

    distinct_revisions = list(dict.fromkeys(revisions))
    if len(distinct_revisions) != 1:
        joined = ", ".join(distinct_revisions)
        raise PipelineError(f"{path} mixes SerializedFile revisions: {joined}")
    return BundleInfo(
        path=path,
        unity_version=distinct_revisions[0],
        archive_format=_integer(report.get("version"), "UnityFS format", path),
        class_ids=tuple(class_ids),
    )
