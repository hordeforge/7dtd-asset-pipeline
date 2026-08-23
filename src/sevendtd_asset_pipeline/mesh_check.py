"""Pre-Unity checks for an authored mesh, using optional OSS tools.

The mesh lane can produce geometry that imports without complaint and is still
wrong in game: authored in centimetres so it arrives a hundred times too big,
non-watertight so a collider behaves oddly, or carrying glTF that Unity accepts
but another consumer rejects. Catching that before Unity import is far cheaper
than catching it in a fresh client.

Two independent OSS tools do the work, each optional and each reported
separately so a partial toolchain still gives a partial answer:

- trimesh for extents, watertightness, and counts
  <https://trimesh.org>
- the Khronos glTF Validator CLI for interchange conformance
  <https://github.com/KhronosGroup/glTF-Validator>
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .capabilities import extra_install, has_capability
from .errors import PipelineError

GLTF_SUFFIXES = (".glb", ".gltf")
# `skipped` gains exactly one entry per lane: trimesh's absence from
# `_measure`, and either gltf_validator's absence or the not-a-glTF scope
# note. Two entries therefore mean no lane produced any evidence at all.
TOOL_COUNT = 2


@dataclass
class MeshReport:
    path: str
    extents: list[float] | None = None
    geometry_count: int | None = None
    vertex_count: int | None = None
    face_count: int | None = None
    watertight: bool | None = None
    gltf_errors: int | None = None
    gltf_warnings: int | None = None
    problems: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def _measure(path: Path, report: MeshReport, max_extent: float) -> None:
    if not has_capability("trimesh"):
        report.skipped.append(
            "geometry checks need the 'trimesh' capability: " + extra_install("mesh")
        )
        return
    import trimesh
    try:
        loaded = trimesh.load(str(path), force=None)
    except Exception as exc:  # noqa: BLE001 - trimesh raises many unrelated types
        report.problems.append(f"trimesh could not load the mesh: {exc}")
        return

    geometries = list(getattr(loaded, "geometry", {}).values()) or [loaded]
    report.geometry_count = len(geometries)
    report.vertex_count = sum(len(getattr(g, "vertices", ())) for g in geometries)
    report.face_count = sum(len(getattr(g, "faces", ())) for g in geometries)
    # Reported, not enforced: glTF export splits vertices at UV and normal
    # seams, so a perfectly good exported cylinder is routinely not watertight.
    # It matters for a mesh intended as a collider, and is noise otherwise.
    report.watertight = all(bool(getattr(g, "is_watertight", False)) for g in geometries)
    extents = getattr(loaded, "extents", None)
    if extents is not None:
        report.extents = [round(float(value), 6) for value in extents]

    if report.vertex_count == 0:
        report.problems.append("the mesh has no vertices")
    if report.extents:
        largest = max(report.extents)
        if largest > max_extent:
            # Unity treats one unit as one metre and so does 7DTD. A mesh
            # authored in centimetres arrives 100x too large and reads as a
            # scale bug in game rather than an export bug.
            report.problems.append(
                f"largest extent is {largest:.3f} m, over --max-extent {max_extent} m; "
                "check the export unit scale (centimetres arrive 100x too large)"
            )
        if largest <= 0:
            report.problems.append("the mesh has zero size")


def _validate_gltf(path: Path, report: MeshReport, strict: bool) -> None:
    validator = shutil.which("gltf_validator") or shutil.which("gltf-validator")
    if not validator:
        report.skipped.append(
            "glTF conformance needs the 'gltf_validator' capability: "
            "scripts/install-tools.sh --with-authoring"
        )
        return
    try:
        result = subprocess.run(
            [validator, "--stdout", "--validate-resources", str(path)],
            check=False, capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        report.problems.append(f"could not run the glTF validator: {exc}")
        return
    try:
        payload = json.loads(result.stdout)
        issues = payload.get("issues", {})
        report.gltf_errors = int(issues.get("numErrors", 0))
        report.gltf_warnings = int(issues.get("numWarnings", 0))
    except (json.JSONDecodeError, TypeError, ValueError):
        if result.returncode != 0:
            report.problems.append(
                f"glTF validator exited {result.returncode}: {result.stderr.strip()[:200]}"
            )
        return
    if report.gltf_errors:
        report.problems.append(f"glTF validation reported {report.gltf_errors} error(s)")
    if strict and report.gltf_warnings:
        report.problems.append(f"glTF validation reported {report.gltf_warnings} warning(s)")


def check_mesh(path: Path, max_extent: float = 16.0, strict: bool = False) -> MeshReport:
    path = path.resolve()
    if not path.is_file():
        raise PipelineError(f"no such mesh: {path}")
    report = MeshReport(path=str(path))
    _measure(path, report, max_extent)
    if path.suffix.lower() in GLTF_SUFFIXES:
        _validate_gltf(path, report, strict)
    else:
        report.skipped.append(f"glTF conformance applies to {'/'.join(GLTF_SUFFIXES)} only")
    if len(report.skipped) == TOOL_COUNT and not report.problems:
        raise PipelineError(
            "no mesh tooling is available. Install it with "
            "scripts/install-tools.sh --with-authoring, or " + extra_install("mesh")
        )
    return report
