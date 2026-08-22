"""One-call machine-readable state of a consumer mod's asset pipeline.

`doctor` answers "is this host able to build?" and `validate` answers "is the
staged artifact correct?", both by failing. An agent orienting in an unfamiliar
mod needs a third answer first: what exists right now, without anything raising.
`collect_status` never raises for a mod-state problem; it records the problem in
the structure and lets the caller decide what to do.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import PipelineConfig
from .errors import PipelineError
from .game import game_unity_version
from .references import discover_references, manifest_assets, read_mod_name
from .unityfs import inspect_bundle
from .validation import validate_mod


@dataclass
class Status:
    mod_name: str
    mod_root: str
    bundle_name: str
    bundle_path: str
    bundle_present: bool
    manifest_path: str
    manifest_present: bool
    unity_project: str
    source_root: str
    game_dir: str | None
    unity_editor: str | None
    bundle_unity_version: str | None = None
    bundle_has_assetbundle_object: bool | None = None
    game_unity_version: str | None = None
    version_matches_game: bool | None = None
    asset_count: int | None = None
    assets: list[str] = field(default_factory=list)
    reference_count: int = 0
    references: list[dict[str, object]] = field(default_factory=list)
    valid: bool | None = None
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _record(status: Status, action):
    try:
        return action()
    except PipelineError as exc:
        status.problems.append(str(exc))
        return None


def collect_status(config: PipelineConfig) -> Status:
    status = Status(
        mod_name=config.mod_name,
        mod_root=str(config.mod_root),
        bundle_name=config.bundle_name,
        bundle_path=str(config.bundle_output),
        bundle_present=config.bundle_output.is_file(),
        manifest_path=str(config.tracked_manifest),
        manifest_present=config.tracked_manifest.is_file(),
        unity_project=str(config.unity_project),
        source_root=config.source_root,
        game_dir=str(config.game_dir) if config.game_dir else None,
        unity_editor=str(config.unity_editor) if config.unity_editor else None,
    )

    declared = _record(status, lambda: read_mod_name(config.mod_root / "ModInfo.xml"))
    if declared is not None and declared != config.mod_name:
        status.problems.append(
            f"ModInfo.xml Name is {declared!r}, configuration says {config.mod_name!r}"
        )

    if config.game_dir:
        discovered = _record(status, lambda: game_unity_version(config.game_dir))
        if discovered is not None:
            status.game_unity_version = discovered[0]

    if status.bundle_present:
        info = _record(status, lambda: inspect_bundle(config.bundle_output))
        if info is not None:
            status.bundle_unity_version = info.unity_version
            status.bundle_has_assetbundle_object = info.has_assetbundle_object
            if status.game_unity_version:
                status.version_matches_game = info.unity_version == status.game_unity_version

    if status.manifest_present:
        assets = _record(status, lambda: manifest_assets(config.tracked_manifest))
        if assets is not None:
            status.assets = assets
            status.asset_count = len(assets)

    references = _record(status, lambda: discover_references(config.config_dir)) or []
    status.reference_count = len(references)
    status.references = [
        {
            "source": str(reference.source),
            "uri": reference.uri,
            "mod_name": reference.mod_name,
            "bundle_path": reference.bundle_path,
            "asset_stem": reference.asset_stem,
        }
        for reference in references
    ]

    # The full validator is the authority on correctness; run it last so the
    # descriptive fields above are populated even when it rejects the mod.
    try:
        validate_mod(config)
        status.valid = True
    except PipelineError as exc:
        status.valid = False
        status.problems.append(str(exc))
    return status
