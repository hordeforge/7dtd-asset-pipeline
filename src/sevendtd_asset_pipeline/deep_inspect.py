"""Per-object bundle inspection, backed by UnityPy when it is installed.

The built-in UnityFS reader answers the class-142 gate and nothing more, on
purpose: it must stay dependency-free and auditable. But "the bundle contains a
class-142 object" does not answer the question that follows a stripped engine
module — *did my prefab's ParticleSystem actually survive serialization?* The
tracked manifest cannot answer it either; it lists source paths, not the
objects Unity emitted.

UnityPy can, so this uses it when present and says how to get it when absent.
It is diagnostic only: nothing here gates a build, and the authoritative
container/revision checks stay in `unityfs.py`.

Source: <https://github.com/K0lb3/UnityPy>
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from .capabilities import require_capability
from .errors import PipelineError


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


def _load_unitypy() -> ModuleType:
    require_capability("UnityPy")
    import UnityPy

    # follow_imports=skip leaves the capability module Any; the boundary lies here.
    return cast(ModuleType, UnityPy)


def _walk(game_object: Any, depth: int = 0) -> tuple[Counter[str], int, int]:
    """Count components across a prefab's whole hierarchy.

    A prefab root usually carries only a Transform; the components that matter
    hang off its children, so a root-only census answers nothing.

    Returns ``(counts, total, skipped)`` where *skipped* is the number of
    child objects that could not be read (corrupt pointer, missing object,
    or depth limit).
    """
    counts: Counter[str] = Counter()
    total = 1
    skipped = 0
    if depth > 64:  # A malformed hierarchy must not become infinite recursion.
        return counts, total, skipped
    transform = None
    for reference in getattr(game_object, "m_Component", []) or []:
        pointer = getattr(reference, "component", reference)
        try:
            type_name = pointer.type.name
        except AttributeError:
            continue
        counts[type_name] += 1
        if type_name == "Transform":
            transform = pointer
    if transform is None:
        return counts, total, skipped
    try:
        children = getattr(transform.read(), "m_Children", []) or []
    except Exception:  # noqa: BLE001 - a child we cannot read must not abort the report
        return counts, total, skipped
    for child in children:
        try:
            child_object = child.read().m_GameObject.read()
        except Exception:  # noqa: BLE001, S112 - an unreadable child must not abort the walk
            skipped += 1
            continue
        child_counts, child_total, child_skipped = _walk(child_object, depth + 1)
        counts += child_counts
        total += child_total
        skipped += child_skipped
    return counts, total, skipped


def deep_inspect(path: Path) -> DeepReport:
    unity_py = _load_unitypy()
    path = path.resolve()
    if not path.is_file():
        raise PipelineError(f"cannot read bundle {path}: no such file")
    # Read the bundle here and hand UnityPy bytes. Loading from a path makes
    # UnityPy hold the file descriptor in a reference-cyclic reader graph with
    # no close() on the environment, so release would be delegated to the
    # cyclic collector — an fd per load until it runs, on every inspect_deep
    # call inside a long-lived serve session.
    try:
        payload = path.read_bytes()
        environment = unity_py.load(payload)
        objects = list(environment.objects)
        container = dict(environment.container)
    except OSError as exc:
        raise PipelineError(f"cannot read bundle {path}: {exc}") from exc
    except Exception as exc:
        raise PipelineError(f"UnityPy could not read {path}: {exc}") from exc

    entries: list[BundleEntry] = []
    skipped_children = 0
    for container_path, obj in sorted(container.items()):
        type_name = getattr(obj.type, "name", "Unknown")
        components: dict[str, int] = {}
        object_count = 1
        object_name = ""
        entry_partial = False
        try:
            data = obj.read()
            object_name = getattr(data, "m_Name", "") or ""
            if type_name == "GameObject":
                counts, object_count, entry_skipped = _walk(data)
                components = dict(sorted(counts.items()))
                skipped_children += entry_skipped
                if entry_skipped:
                    entry_partial = True
        except Exception:  # noqa: BLE001 - report the entry even if it cannot be read
            object_name = ""
            entry_partial = True
        entries.append(
            BundleEntry(
                container_path=container_path,
                type=type_name,
                object_name=object_name,
                # 7DTD addresses assets by file-name stem, so surface the key
                # it will actually look up rather than the full container path.
                asset_stem=Path(container_path).stem,
                object_count=object_count,
                components=components,
                partial=entry_partial,
            )
        )

    return DeepReport(
        path=str(path),
        object_count=len(objects),
        # The same tolerance the per-entry loop above applies: one object whose
        # type cannot be read must not abort a report whose entries succeeded.
        type_counts=dict(
            sorted(Counter(getattr(o.type, "name", "Unknown") for o in objects).items())
        ),
        entries=entries,
        skipped_children=skipped_children,
    )
