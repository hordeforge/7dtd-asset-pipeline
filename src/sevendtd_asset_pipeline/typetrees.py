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
import os
import shutil
from dataclasses import dataclass, field
from typing import Any

from . import unityz
from .errors import PipelineError

TreesTable = dict[str, object]

# The revision this pipeline asks unityz for when nothing else names one. It is
# the revision the author-side defaults are read from and the one 7DTD V ships:
# unityz matches a tree by exact revision with no nearest-version fallback, so
# a default read here has to name the release the game's own assets carry
# (2022.3.62f2) rather than the revision a caller happens to be building for.
# Named here rather than repeated at each call site, because a per-module copy
# is how two of them end up disagreeing with the database and with each other.
DEFAULT_UNITY_REVISION = "2022.3.62f2"


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


UNITYZ_EXECUTABLE = "unityz"


def backend_identity() -> str:
    """Which `unityz` answers, closely enough to notice it was replaced.

    The trees table belongs to the reader, not to the revision: unityz ships a
    release-indexed database beside that executable, so a reinstalled or
    upgraded one can answer a different table for the same revision string. A
    `shamway serve` session outlives the install its own error message calls
    for (the same argument `capabilities.smolv_library` is written on), and a
    table cached across that upgrade is a stale type tree embedded in a bundle,
    which is the silent load failure this module exists to prevent. Path, size
    and mtime are what a replacement changes; the cost is one `which` and one
    `stat` against the subprocess and JSON parse they guard.
    """
    found = shutil.which(UNITYZ_EXECUTABLE)
    if found is None:
        return f"{UNITYZ_EXECUTABLE}:absent"
    try:
        stat = os.stat(found)
    except OSError:
        # Present on PATH, unreadable to stat. The identity stays what it can be,
        # and a failing run reports the real reason from `unityz.invoke`.
        return f"{UNITYZ_EXECUTABLE}:{found}"
    return f"{UNITYZ_EXECUTABLE}:{found}:{stat.st_size}:{stat.st_mtime_ns}"


@functools.lru_cache(maxsize=4)
def _release_table(unity_version: str, backend: str) -> TreesTable:
    """The whole built-in trees export for one revision, in the `--trees` shape.

    Keyed by the reader as well as the revision (`backend_identity`): the two
    together identify the database, and a cache holding a table from a reader
    this host no longer has is worse than no cache at all.
    """
    del backend  # The identity is the key; unityz.invoke resolves the reader itself.
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


def release_table(unity_version: str) -> TreesTable:
    """The trees table for one revision, from whatever unityz is on PATH now.

    The backend is part of the key rather than an assumption: the table is the
    reader's own database, and a session that outlives an upgrade of that
    reader must not keep serving the previous one.
    """
    return _release_table(unity_version, backend_identity())


@functools.lru_cache(maxsize=4)
def _class_ids(unity_version: str, backend: str) -> dict[int, str]:
    """`__class_ids__` inverted, so `class_name` is a lookup and not a table scan.

    Unity's table holds an entry per class, and `class_trees` and `release_tree`
    both ask for one name per class id, so scanning it per id was quadratic in
    the number of classes a bundle carries. Where two names share an id the
    first in the export wins, which is what the old scan returned.

    The reader is part of the key for the same reason it is one for
    `_release_table`: this is that table's own content, and an id it no longer
    carries, or a name it has renamed, must not be served across a reinstall.
    """
    ids = _release_table(unity_version, backend)["__class_ids__"]
    if not isinstance(ids, dict):
        raise PipelineError(f"unityz trees returned a malformed __class_ids__ for {unity_version}")
    return {found: str(name) for name, found in ids.items()}


def class_name(class_id: int, unity_version: str) -> str:
    try:
        return _class_ids(unity_version, backend_identity())[class_id]
    except KeyError as exc:
        raise PipelineError(
            f"no type tree for class {class_id} at Unity {unity_version}: the built-in "
            "database has no such class. The type tree is the engine's own field "
            "layout; without it this backend will not guess one."
        ) from exc


def class_trees(class_ids: set[int], unity_version: str) -> TreesTable:
    """A `--trees` table holding exactly `class_ids`, for a `unityz create` spec."""
    table = release_table(unity_version)
    names = {class_id: class_name(class_id, unity_version) for class_id in class_ids}
    subset: TreesTable = {"__class_ids__": {name: cid for cid, name in names.items()}}
    for name in names.values():
        subset[name] = table[name]
    return subset


@functools.lru_cache(maxsize=32)
def _release_tree(class_id: int, unity_version: str, backend: str) -> TreeNode:
    """The tree for one class, nested for the default walkers.

    Cached and shared, because rebuilding the whole `TreeNode` forest from the
    flat node list cost the same on every call and `typetree_default` only ever
    reads it. A caller that needs to change a node must copy it first.

    The reader is part of the key because this tree is that reader's own field
    layout: a session outliving `shamway script install-unityz` would otherwise
    keep embedding the replaced reader's layout while `release_table` beside it
    had already reloaded.
    """
    try:
        name = _class_ids(unity_version, backend)[class_id]
    except KeyError as exc:
        raise PipelineError(
            f"no type tree for class {class_id} at Unity {unity_version}: the built-in "
            "database has no such class. The type tree is the engine's own field "
            "layout; without it this backend will not guess one."
        ) from exc
    flat = _release_table(unity_version, backend)[name]
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


def release_tree(class_id: int, unity_version: str) -> TreeNode:
    """`_release_tree` under the reader on PATH now, which is half its key."""
    return _release_tree(class_id, unity_version, backend_identity())


def typetree_default(node: TreeNode) -> Any:
    """A default value for every type-tree node.

    The writer (`unityz create`) requires every field the tree names, so an
    object dict is the tree's defaults deep-merged with the fields an author
    module sets. This is the one walker; `anim.py` and `particles.py` import it.
    """
    kind = node.kind
    children = node.children
    if kind in {
        "int",
        "SInt32",
        "UInt32",
        "unsigned int",
        "SInt64",
        "UInt64",
        "SInt16",
        "UInt16",
        "UInt8",
        "SInt8",
        "char",
        "short",
        "unsigned short",
        "long long",
        "unsigned long long",
    }:
        return 0
    if kind in {"float", "double"}:
        return 0.0
    if kind == "bool":
        return False
    if kind == "string":
        return ""
    if kind == "TypelessData":
        return b""
    if kind.startswith("PPtr"):
        return {"m_FileID": 0, "m_PathID": 0}
    if kind in {"vector", "staticvector", "Array", "map"}:
        return []
    fields: dict[str, Any] = {}
    for child in children:
        if child.kind == "Array" and child.name == "Array":
            return []
        fields[child.name] = typetree_default(child)
    return fields
