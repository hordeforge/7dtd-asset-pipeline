"""Reusable asset-bundle tooling for 7 Days to Die mods.

The names re-exported here are the supported Python API for consumers who want
to script the pipeline instead of shelling out to `7dtd-assets`. Everything
else in this package is an implementation detail and may change without notice.

    from sevendtd_asset_pipeline import collect_status, load_config

    config = load_config()            # finds .7dtd-assets.toml upward from cwd
    status = collect_status(config)   # never raises for a mod-state problem
    if not status.valid:
        print(status.problems)

Every other entry point raises `PipelineError` with a single user-actionable
message when a gate fails.
"""

from .build import reject_disabled_modules, run_build
from .config import PipelineConfig, load_config
from .doctor import Check, failed, run_doctor
from .errors import PipelineError
from .game import game_unity_version, project_unity_version
from .references import AssetReference, discover_references, manifest_assets
from .scaffold import initialize
from .status import Status, collect_status
from .unity_release import Release, fetch_release
from .unityfs import BundleInfo, inspect_bundle
from .validation import ValidationReport, validate_bundle, validate_mod

__version__ = "0.1.0"

__all__ = [
    "AssetReference",
    "BundleInfo",
    "Check",
    "PipelineConfig",
    "PipelineError",
    "Release",
    "Status",
    "ValidationReport",
    "collect_status",
    "discover_references",
    "failed",
    "fetch_release",
    "game_unity_version",
    "initialize",
    "inspect_bundle",
    "load_config",
    "manifest_assets",
    "project_unity_version",
    "reject_disabled_modules",
    "run_build",
    "run_doctor",
    "validate_bundle",
    "validate_mod",
    "__version__",
]
