"""One-call machine-readable state of a consumer mod's asset pipeline.

`doctor` answers "is this host able to build?" and `validate` answers "is the
staged artifact correct?", both by failing. An agent orienting in an unfamiliar
mod needs a third answer first: what exists right now, without anything raising.
`collect_status` never raises for a mod-state problem; it records the problem in
the structure and lets the caller decide what to do.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TypeVar

from .capabilities import capabilities
from .config import PipelineConfig
from .errors import PipelineError
from .game import game_unity_version
from .references import AssetReference, discover_references, manifest_assets, read_mod_name
from .unityfs import inspect_bundle
from .validation import validate_mod


@dataclass
class Status:
    mod_name: str
    mod_root: str
    bundle_source: str
    """Where the bundle comes from: one of config.BUNDLE_SOURCES."""
    bundle_name: str | None
    bundle_path: str | None
    bundle_present: bool
    manifest_path: str | None
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
    capabilities: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


_T = TypeVar("_T")


def _record(status: Status, action: Callable[[], _T]) -> _T | None:
    try:
        return action()
    except PipelineError as exc:
        status.problems.append(str(exc))
        return None


def collect_status(config: PipelineConfig) -> Status:
    # A mod with no bundle has no bundle path, no manifest, and no Unity of any
    # kind; the fields stay in the shape a consumer already parses, reported as
    # null rather than as a missing file.
    bundle = config.bundle_output if config.has_bundle else None
    manifest = config.tracked_manifest if config.has_bundle else None
    status = Status(
        mod_name=config.mod_name,
        mod_root=str(config.mod_root),
        bundle_source=config.bundle_source,
        bundle_name=config.bundle_name or None,
        bundle_path=str(bundle) if bundle else None,
        bundle_present=bundle.is_file() if bundle else False,
        manifest_path=str(manifest) if manifest else None,
        manifest_present=manifest.is_file() if manifest else False,
        unity_project=str(config.unity_project),
        source_root=config.source_root,
        game_dir=str(config.game_dir) if config.game_dir else None,
        unity_editor=str(config.unity_editor) if config.unity_editor else None,
    )

    status.capabilities = {item.name: item.available for item in capabilities()}

    declared = _record(status, lambda: read_mod_name(config.mod_root / "ModInfo.xml"))
    if declared is not None and declared != config.mod_name:
        status.problems.append(
            f"ModInfo.xml Name is {declared!r}, configuration says {config.mod_name!r}"
        )

    game_discovered: tuple[str, Path] | None = None
    if config.game_dir:
        game_dir = config.game_dir
        discovered = _record(status, lambda: game_unity_version(game_dir))
        if discovered is not None:
            game_discovered = discovered
            status.game_unity_version = discovered[0]

    bundle_info = None
    if status.bundle_present and bundle is not None:
        bundle_info = _record(status, lambda: inspect_bundle(bundle))
        if bundle_info is not None:
            status.bundle_unity_version = bundle_info.unity_version
            status.bundle_has_assetbundle_object = bundle_info.has_assetbundle_object
            if status.game_unity_version:
                status.version_matches_game = bundle_info.unity_version == status.game_unity_version

    assets_read: list[str] | None = None
    if status.manifest_present and manifest is not None:
        read = _record(status, lambda: manifest_assets(manifest))
        if read is not None:
            assets_read = read
            status.assets = read
            status.asset_count = len(read)

    references_read: list[AssetReference] | None = None
    discovered_references = _record(status, lambda: discover_references(config.config_dir))
    if discovered_references is not None:
        references_read = discovered_references
        status.reference_count = len(references_read)
        status.references = [
            {
                "source": str(reference.source),
                "uri": reference.uri,
                "mod_name": reference.mod_name,
                "bundle_path": reference.bundle_path,
                "asset_stem": reference.asset_stem,
            }
            for reference in references_read
        ]

    # The full validator is the authority on correctness; run it last so the
    # descriptive fields above are populated even when it rejects the mod. It
    # reuses the reads above rather than paying for them a second time; a read
    # that failed stays None, so the validator fails on the same read instead
    # of inventing a different answer.
    try:
        validate_mod(
            config,
            game_version=game_discovered,
            bundle_info=bundle_info,
            assets=assets_read,
            references=references_read,
        )
        status.valid = True
    except PipelineError as exc:
        status.valid = False
        status.problems.append(str(exc))
    return status
