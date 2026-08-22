"""Unity batch-mode orchestration and safe artifact staging."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import PipelineConfig
from .errors import PipelineError
from .game import game_unity_version, project_unity_version
from .references import manifest_assets
from .validation import reject_ambiguous_stems, validate_bundle

DISABLED_MODULE_TEXT = "is not supported because the module"
DISABLED_MODULE_SUFFIX = "is disabled in the build"


def disabled_module_lines(log: Path) -> list[str]:
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise PipelineError(f"cannot read Unity log {log}: {exc}") from exc
    return [line for line in lines if DISABLED_MODULE_TEXT in line and DISABLED_MODULE_SUFFIX in line]


def reject_disabled_modules(log: Path) -> None:
    hits = disabled_module_lines(log)
    if hits:
        raise PipelineError(
            "Unity stripped engine-module classes while reporting build success:\n"
            + "\n".join(hits)
            + "\nAdd the matching com.unity.modules.* packages and rebuild."
        )


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        shutil.copy2(source, temporary_path)
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def run_build(config: PipelineConfig, probe: bool = False) -> Path:
    if config.unity_editor is None:
        raise PipelineError("UNITY_EDITOR is not configured; run '7dtd-assets doctor'")
    if not config.unity_editor.is_file() or not os.access(config.unity_editor, os.X_OK):
        raise PipelineError(f"Unity editor is not executable: {config.unity_editor}")
    project_version = project_unity_version(config.unity_project)
    expected_version = game_unity_version(config.game_dir)[0] if config.game_dir else project_version
    if project_version != expected_version:
        raise PipelineError(
            f"Unity project is {project_version}; installed game uses {expected_version}. "
            "Upgrade the project and editor before building."
        )
    windows_module = (
        config.unity_editor.parent / "Data/PlaybackEngines/WindowsStandaloneSupport/UnityEditor.WindowsStandalone.Extensions.dll"
    )
    if config.target == "StandaloneWindows64" and not windows_module.is_file():
        raise PipelineError(f"Unity Windows Build Support (Mono) is missing: {windows_module}")

    output = config.build_dir / ("probe" if probe else "bundle")
    output.mkdir(parents=True, exist_ok=True)
    log = output / "unity-build.log"
    probe_name = "seven-days-to-die-pipeline-probe.unity3d"
    built_name = probe_name if probe else config.bundle_name
    command = [
        str(config.unity_editor),
        "-batchmode",
        "-nographics",
        "-projectPath",
        str(config.unity_project),
        "-executeMethod",
        "SevenDaysToDie.AssetPipeline.BundleBuilder.BuildFromCommandLine",
        "-logFile",
        str(log),
        "-sapOutput",
        str(output),
        "-sapTarget",
        config.target,
        "-sapBundleName",
        config.bundle_name,
        "-sapSourceRoot",
        config.source_root,
    ]
    if probe:
        command.append("-sapProbe")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise PipelineError(f"Unity exited {result.returncode}; inspect {log}")
    built = output / built_name
    if not built.is_file():
        raise PipelineError(f"Unity exited successfully but did not write {built}; inspect {log}")
    reject_disabled_modules(log)
    validate_bundle(built, expected_version)
    if probe:
        return built
    generated_manifest = output / f"{config.bundle_name}.manifest"
    if not generated_manifest.is_file():
        raise PipelineError(f"Unity did not write {generated_manifest}")
    reject_ambiguous_stems(manifest_assets(generated_manifest))
    # The manifest is authoring evidence and the bundle is the runtime artifact.
    # Stage evidence first and make the runtime artifact the final commit point.
    # If the last copy fails, the prior deployable bundle remains in place and
    # validation reports the manifest mismatch instead of shipping new bytes
    # whose evidence was never staged.
    _atomic_copy(generated_manifest, config.tracked_manifest)
    _atomic_copy(built, config.bundle_output)
    return config.bundle_output
