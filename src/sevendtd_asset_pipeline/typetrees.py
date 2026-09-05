"""The engine's own per-revision class type trees, served by unityz.

A type tree is Unity's field layout for one class at one exact revision.
unityz ships a release-indexed database of them (`unityz trees --builtin`),
matched by exact revision string with no nearest-version fallback, and
`unityz create` serializes objects by walking those same trees. This module
is the one place the pipeline asks for a tree: the writer embeds it, and the
animation and particle authors walk it for version-correct defaults. A class
or revision the database does not carry is refused here; guessing a layout is
how a bundle becomes a silent load failure.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass, field

from . import unityz
from .errors import PipelineError

TreesTable = dict[str, object]


@dataclass
class TreeNode:
    """One type-tree node, nested, as the default walkers read it."""

    kind: str
    name: str
    version: int = 1
    byte_size: int = -1
    meta_flag: int = 0
    type_flags: int = 0
    children: list[TreeNode] = field(default_factory=list)


@functools.lru_cache(maxsize=4)
def release_table(unity_version: str) -> TreesTable:
    """The whole built-in trees export for one revision, in the `--trees` shape."""
    result = unityz.invoke("trees", "--builtin", unity_version, subject=unity_version)
    if result.returncode != 0:
        raise PipelineError(
            f"no built-in type trees for Unity {unity_version}: "
            + (result.stderr.strip() or "unityz gave no diagnostic")
            + ". The type tree is the engine's own field layout; without it this "
            "backend will not guess one."
        )
    try:
        table = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PipelineError(
            f"unityz trees returned invalid JSON for {unity_version}: {exc}"
        ) from exc
    if not isinstance(table, dict) or not isinstance(table.get("__class_ids__"), dict):
        raise PipelineError(f"unityz trees returned no __class_ids__ table for {unity_version}")
    return table


def class_name(class_id: int, unity_version: str) -> str:
    ids = release_table(unity_version)["__class_ids__"]
    if not isinstance(ids, dict):
        raise PipelineError(f"unityz trees returned a malformed __class_ids__ for {unity_version}")
    for name, found in ids.items():
        if found == class_id:
            return str(name)
    raise PipelineError(
        f"no type tree for class {class_id} at Unity {unity_version}: the built-in "
        "database has no such class. The type tree is the engine's own field "
        "layout; without it this backend will not guess one."
    )


def class_trees(class_ids: set[int], unity_version: str) -> TreesTable:
    """A `--trees` table holding exactly `class_ids`, for a `unityz create` spec."""
    table = release_table(unity_version)
    names = {class_id: class_name(class_id, unity_version) for class_id in class_ids}
    subset: TreesTable = {"__class_ids__": {name: cid for cid, name in names.items()}}
    for name in names.values():
        subset[name] = table[name]
    return subset


def release_tree(class_id: int, unity_version: str) -> TreeNode:
    """The tree for one class, nested for the default walkers."""
    name = class_name(class_id, unity_version)
    flat = release_table(unity_version)[name]
    if not isinstance(flat, list):
        raise PipelineError(f"unityz trees returned a malformed {name} tree for {unity_version}")
    stack: list[TreeNode] = []
    root: TreeNode | None = None
    for raw in flat:
        if not isinstance(raw, dict):
            raise PipelineError(
                f"unityz trees returned a malformed {name} node for {unity_version}"
            )
        node = TreeNode(
            kind=str(raw["m_Type"]),
            name=str(raw["m_Name"]),
            version=int(raw.get("m_Version", 1)),
            byte_size=int(raw.get("m_ByteSize", -1)),
            meta_flag=int(raw.get("m_MetaFlag", 0)),
            type_flags=int(raw.get("m_TypeFlags", 0)),
        )
        level = int(raw["m_Level"])
        del stack[level:]
        if stack:
            stack[-1].children.append(node)
        else:
            root = node
        stack.append(node)
    if root is None:
        raise PipelineError(f"the built-in tree for class {class_id} at {unity_version} is empty")
    return root
