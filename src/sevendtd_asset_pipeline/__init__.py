"""Reusable asset-bundle tooling for 7 Days to Die mods.

The names re-exported here are the supported Python API for consumers who want
to script the pipeline instead of shelling out to `7dtd-assets`. Everything
else in this package is an implementation detail and may change without notice.

    from sevendtd_asset_pipeline import Pipeline

    pipeline = Pipeline.discover()     # finds .7dtd-assets.toml upward from cwd
    status = pipeline.status()         # never raises for a mod-state problem
    if not status.valid:
        print(status.problems)

`Pipeline` is the recommended entry point; the individual functions remain
available for callers that want one piece. Out-of-process consumers should use
`7dtd-assets schema`, `call`, and `serve`, which dispatch through the same
operation registry — see docs/consumer-api.md.

Every entry point raises `PipelineError` with a single user-actionable message
when a gate fails.
"""

from .api import Pipeline, call_json
from .build import reject_disabled_modules, run_build
from .capabilities import Capability, capabilities, has_capability, require_capability
from .config import PipelineConfig, load_config
from .deep_inspect import DeepReport, deep_inspect
from .doctor import Check, failed, run_doctor
from .mesh_check import MeshReport, check_mesh
from .errors import PipelineError
from .game import game_unity_version, project_unity_version
from .references import AssetReference, discover_references, manifest_assets
from .operations import OPERATIONS, Operation, manifest
from .scaffold import initialize
from .status import Status, collect_status
from .unity_release import Release, fetch_release
from .unityfs import BundleInfo, inspect_bundle
from .validation import ValidationReport, validate_bundle, validate_mod

__version__ = "0.1.0"

__all__ = [
    "AssetReference",
    "BundleInfo",
    "Capability",
    "Check",
    "DeepReport",
    "MeshReport",
    "OPERATIONS",
    "Operation",
    "Pipeline",
    "PipelineConfig",
    "PipelineError",
    "Release",
    "Status",
    "ValidationReport",
    "__version__",
    "call_json",
    "capabilities",
    "check_mesh",
    "collect_status",
    "deep_inspect",
    "discover_references",
    "failed",
    "fetch_release",
    "game_unity_version",
    "has_capability",
    "initialize",
    "inspect_bundle",
    "load_config",
    "manifest",
    "manifest_assets",
    "project_unity_version",
    "reject_disabled_modules",
    "require_capability",
    "run_build",
    "run_doctor",
    "validate_bundle",
    "validate_mod",
]
