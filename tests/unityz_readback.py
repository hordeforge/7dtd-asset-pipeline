"""Independent read-back of pipeline-authored bundles through unityz.

The production writer owns the bytes. Tests use this adapter to ask the pinned
Zig implementation what those bytes contain, preserving the independent-reader
boundary without depending on UnityPy's Python object wrappers.
"""

from __future__ import annotations

import base64
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sevendtd_asset_pipeline.unityz import Unityz


def decoded_bytes(value: object) -> bytes:
    """Decode unityz's JSON representation of a serialized byte array."""
    if not isinstance(value, str):
        raise AssertionError(f"unityz byte array is not a base64 string: {type(value).__name__}")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise AssertionError("unityz byte array is not valid base64") from exc


@dataclass(frozen=True)
class ReadbackObject:
    path_id: int
    class_id: int
    name: str | None
    tree: dict[str, Any]


@dataclass(frozen=True)
class BundleReadback:
    objects: tuple[ReadbackObject, ...]
    raw_files: dict[str, bytes]

    def trees_by_class(self) -> dict[int, list[dict[str, Any]]]:
        found: dict[int, list[dict[str, Any]]] = {}
        for obj in self.objects:
            found.setdefault(obj.class_id, []).append(obj.tree)
        return found

    def first_path_ids_by_class(self) -> dict[int, int]:
        found: dict[int, int] = {}
        for obj in self.objects:
            found.setdefault(obj.class_id, obj.path_id)
        return found

    def raw_files_ending(self, suffix: str) -> dict[str, bytes]:
        return {name: data for name, data in self.raw_files.items() if name.endswith(suffix)}


def read_bundle(bundle: Path) -> BundleReadback:
    """Extract every object tree and raw top-level node through unityz once."""
    reader = Unityz(bundle)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        reader.text("extract", "--json", "--outdir", str(root))
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        entries = manifest.get("objects") if isinstance(manifest, dict) else None
        if not isinstance(entries, list):
            raise AssertionError("unityz extract manifest has no objects array")

        objects: list[ReadbackObject] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise AssertionError("unityz extract manifest contains a non-object entry")
            relative = entry.get("file")
            if not isinstance(relative, str):
                raise AssertionError("unityz extract manifest entry has no file")
            object_path = (root / relative).resolve()
            if not object_path.is_relative_to(root.resolve()):
                raise AssertionError(
                    f"unityz extract path escapes its output directory: {relative}"
                )
            tree = json.loads(object_path.read_text(encoding="utf-8"))
            if not isinstance(tree, dict):
                raise AssertionError(f"unityz object JSON is not an object: {relative}")
            name = entry.get("name")
            objects.append(
                ReadbackObject(
                    path_id=int(entry["path_id"]),
                    class_id=int(entry["class"]),
                    name=name if isinstance(name, str) else None,
                    tree=tree,
                )
            )

        raw_files = {
            path.name: path.read_bytes()
            for path in root.iterdir()
            if path.is_file() and path.name != "manifest.json"
        }
        return BundleReadback(tuple(objects), raw_files)


def show_object(bundle: Path, class_id: int) -> dict[str, Any]:
    """Return unityz's enriched view of the only object of one class."""
    reader = Unityz(bundle)
    report = reader.json("info", "--json", "--objects")
    entries = report.get("object_list")
    if not isinstance(entries, list):
        raise AssertionError("unityz info report has no object_list array")
    matches = [
        entry for entry in entries if isinstance(entry, dict) and entry.get("class") == class_id
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"unityz info found {len(matches)} class-{class_id} objects; expected exactly one"
        )
    entry = matches[0]
    node = entry.get("node")
    path_id = entry.get("path_id")
    if not isinstance(node, str) or not isinstance(path_id, int):
        raise AssertionError(f"unityz class-{class_id} object has no node/path ID")
    return dict(reader.json("show", f"{node}:{path_id}", "--json"))
