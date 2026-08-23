"""Read-only discovery of the Unity revision used by an installed game."""

from __future__ import annotations

from pathlib import Path

from .errors import PipelineError
from .unityfs import inspect_bundle

PREFERRED_BUNDLES = (
    "Data/Bundles/Standalone/Entities/Entities",
    "Data/Bundles/Standalone/Entities/trees",
)


def validate_game_dir(game_dir: Path) -> None:
    marker = game_dir / "Data" / "Config" / "items.xml"
    if not marker.is_file():
        raise PipelineError(f"{game_dir} is not a 7 Days to Die install ({marker} is missing)")


def game_unity_version(game_dir: Path) -> tuple[str, Path]:
    validate_game_dir(game_dir)
    candidates = [game_dir / relative for relative in PREFERRED_BUNDLES]
    bundles = game_dir / "Data" / "Bundles"
    if bundles.is_dir():
        candidates.extend(
            path
            for path in sorted(bundles.rglob("*"))
            if path.is_file() and path.suffix != ".manifest"
        )
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        try:
            return inspect_bundle(candidate).unity_version, candidate
        except PipelineError:
            continue
    raise PipelineError(f"no readable UnityFS bundle found below {bundles}")


def project_unity_version(project: Path) -> str:
    version_file = project / "ProjectSettings" / "ProjectVersion.txt"
    try:
        lines = version_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PipelineError(f"cannot read {version_file}: {exc}") from exc
    for line in lines:
        if line.startswith("m_EditorVersion:"):
            return line.partition(":")[2].strip()
    raise PipelineError(f"{version_file} has no m_EditorVersion")
