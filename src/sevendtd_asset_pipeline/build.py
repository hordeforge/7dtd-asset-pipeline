"""Unity batch-mode orchestration and safe artifact staging.

Two ways in. `run_build` starts a local editor and gates what it produced.
`stage_bundle` gates a bundle some *other* editor produced — a CI job, a
teammate's machine, a container — and stages it through exactly the same
checks. That second door is what makes a Unity install optional on this host
without making the artifact less checked: every gate that reads the artifact
still runs, and the one gate that reads the *build* (the disabled-module log
check) runs whenever the log travels with the bundle, which is why `stage`
takes one and says so loudly when it does not.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .bundle_writer import pack_directory
from .config import PipelineConfig
from .errors import PipelineError
from .game import game_unity_version, project_unity_version
from .references import manifest_assets
from .validation import reject_ambiguous_stems, validate_bundle

DISABLED_MODULE_TEXT = "is not supported because the module"
DISABLED_MODULE_SUFFIX = "is disabled in the build"
# A particle module whose X/Y/Z MinMaxCurves are not all in one mode serializes
# cleanly and then logs this on *every frame the system updates* in the client
# — thousands of lines a second. The editor already says it once at authoring
# time, so the build log is where it is cheap to catch.
PARTICLE_CURVE_MODE_TEXT = "curves must all be in the same mode"


def _log_lines(log: Path) -> list[str]:
    try:
        return log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise PipelineError(f"cannot read Unity log {log}: {exc}") from exc


def disabled_module_lines(log: Path) -> list[str]:
    return [
        line for line in _log_lines(log) if DISABLED_MODULE_TEXT in line and DISABLED_MODULE_SUFFIX in line
    ]


def particle_curve_mode_lines(log: Path) -> list[str]:
    return [line for line in _log_lines(log) if PARTICLE_CURVE_MODE_TEXT in line]


def reject_disabled_modules(log: Path) -> None:
    """Reject a log that shows Unity stripping classes or shipping a per-frame error.

    The name is historical; it is the build-log gate, and it now has two
    families. Each one produced a bundle that passed every other check.
    """
    # One read serves both families: a Unity build log reaches tens of
    # megabytes, and reading it twice per gate doubled the cost of every
    # `build`, `stage`, and `check-log`.
    lines = _log_lines(log)
    hits = [
        line for line in lines if DISABLED_MODULE_TEXT in line and DISABLED_MODULE_SUFFIX in line
    ]
    if hits:
        raise PipelineError(
            "Unity stripped engine-module classes while reporting build success:\n"
            + "\n".join(hits)
            + "\nAdd the matching com.unity.modules.* packages and rebuild."
        )
    curves = [line for line in lines if PARTICLE_CURVE_MODE_TEXT in line]
    if curves:
        raise PipelineError(
            "a particle system mixes MinMaxCurve modes; the client logs this on every frame:\n"
            + "\n".join(sorted(set(curves))[:5])
            + "\nExpress a stationary axis as GeneratedAsset.ZeroCurve(), never as 0f (docs/vfx.md)."
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


def expected_unity_version(config: PipelineConfig) -> str:
    """The revision this mod's bundle must be built at.

    The installed game decides it, because the game is what has to load the
    result. Without a game directory the editorless backend falls back to the
    revision recorded at scaffold time, and says so rather than guessing a
    current one: a bundle at the wrong revision loads as "not compatible".
    """
    if config.game_dir:
        return game_unity_version(config.game_dir)[0]
    if config.unity_version:
        return config.unity_version
    raise PipelineError(
        "no Unity revision is known: set SEVEN_DAYS_TO_DIE_DIR so the installed "
        "game can answer, or record the revision as [unity] version in "
        f"{config.config_file.name}"
    )


def run_build(config: PipelineConfig, probe: bool = False) -> Path:
    config.require_bundle()
    if not config.builds_locally:
        raise PipelineError(
            f'{config.config_file.name} sets bundle_source = "{config.bundle_source}", so this '
            "host does not build the bundle. Build it where an editor lives, then gate and "
            "stage it here with 'shamway stage BUNDLE --manifest M --log L'."
        )
    if config.bundle_source == "synthesized":
        return synthesize_bundle(config, probe)
    if config.unity_editor is None:
        raise PipelineError("UNITY_EDITOR is not configured; run 'shamway doctor'")
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


def stage_bundle(
    config: PipelineConfig,
    bundle: Path,
    manifest: Path | None = None,
    log: Path | None = None,
) -> tuple[Path, list[str]]:
    """Gate a bundle built by an editor elsewhere and stage it into the modlet.

    This is `run_build`'s second half, reachable without Unity: the revision
    and class-142 gates, the stem-collision gate over the build manifest, the
    build-log gate when a log came along, and the same manifest-then-bundle
    atomic staging, so a rejected candidate never replaces a working artifact.

    Returns the staged path and the list of gates that did *not* run, because
    an unrun gate that goes unmentioned reads exactly like a passed one.
    """
    config.require_bundle()
    bundle = bundle.resolve()
    if not bundle.is_file():
        raise PipelineError(f"no bundle to stage at {bundle}")
    if manifest is None:
        # Unity writes '<bundle>.manifest' beside the bundle it built; that
        # sibling is the default so the common case is one argument.
        sibling = Path(f"{bundle}.manifest")
        if not sibling.is_file():
            raise PipelineError(
                f"no build manifest beside the bundle ({sibling.name}); pass --manifest. "
                "It is Unity's own output and the only offline record of bundle membership, "
                "so it must travel with the bundle it describes."
            )
        manifest = sibling
    manifest = manifest.resolve()
    if not manifest.is_file():
        raise PipelineError(f"no build manifest at {manifest}")
    if bundle == config.bundle_output.resolve():
        raise PipelineError(
            f"{bundle} is already the staged bundle; stage the build output, not the "
            "artifact it would replace"
        )

    skipped: list[str] = []
    if log is not None:
        reject_disabled_modules(log)
    else:
        skipped.append(
            "the build-log gate: no Unity log was supplied, so a build that reported "
            "success while stripping engine-module classes would not be caught here. "
            "Pass --log with the log that built this bundle."
        )
    expected_version = game_unity_version(config.game_dir)[0] if config.game_dir else None
    if expected_version is None:
        skipped.append(
            "the game-revision gate: no game directory is configured, so the bundle's "
            "Unity revision was not held against the installed game's. Set "
            "SEVEN_DAYS_TO_DIE_DIR."
        )
    validate_bundle(bundle, expected_version)
    reject_ambiguous_stems(manifest_assets(manifest))
    _atomic_copy(manifest, config.tracked_manifest)
    _atomic_copy(bundle, config.bundle_output)
    return config.bundle_output, skipped


# What a synthesized bundle's own gates do and do not prove. `stage` prints the
# gates its evidence could not support; this prints the gates whose *meaning*
# changes when the artifact and its checker have the same author. Both exist so
# that a green report is never read as more than it is.
SYNTHESIZED_CAVEATS = (
    "the class-142 container gate ran against this tool's own output, so here it "
    "is structural, not independent evidence that the engine accepts the container",
    "the stem-collision gate read the membership record this build wrote, for the "
    "same reason",
    "the build-log gate cannot run: there is no editor to report stripping an "
    "engine module while claiming success",
    "a fresh client is therefore the acceptance for a synthesized bundle rather "
    "than a confirmation of it: 'shamway client deploy .' then 'client launch'",
)


def synthesize_bundle(config: PipelineConfig, probe: bool = False) -> Path:
    """Write the bundle with this repository's own writer: no editor, no project.

    The gates still run, and the revision one still means what it always did —
    it rejects a writer aimed at a revision the installed game does not use.
    The other two change character, because a checker and an artifact with the
    same author cannot cross-examine each other; `SYNTHESIZED_CAVEATS` says so
    in the words every caller prints.

    See `bundle_writer.py` for the format and `docs/offline-bundle-builder.md`
    for why a modlet bundle is the tractable case.
    """
    version = expected_unity_version(config)
    output = config.build_dir / ("probe" if probe else "bundle")
    output.mkdir(parents=True, exist_ok=True)
    bundle_bytes, manifest_text = pack_directory(
        config.bundle_source_dir, config.bundle_name, version, _build_target(config)
    )
    built = output / config.bundle_name
    built.write_bytes(bundle_bytes)
    generated_manifest = output / f"{config.bundle_name}.manifest"
    generated_manifest.write_text(manifest_text, encoding="utf-8")

    validate_bundle(built, version)
    reject_ambiguous_stems(manifest_assets(generated_manifest))
    if probe:
        # A probe answers "would this synthesize?" and stages nothing, exactly
        # as the Unity probe does; here it costs milliseconds, not minutes.
        return built
    _atomic_copy(generated_manifest, config.tracked_manifest)
    _atomic_copy(built, config.bundle_output)
    return config.bundle_output


# Unity's BuildTarget values, for the targets this pipeline supports. The
# editorless writer stores the number the editor would have stored.
BUILD_TARGETS = {"StandaloneWindows64": 19, "StandaloneWindows": 5, "StandaloneLinux64": 24}


def _build_target(config: PipelineConfig) -> int:
    try:
        return BUILD_TARGETS[config.target]
    except KeyError:
        known = ", ".join(BUILD_TARGETS)
        raise PipelineError(
            f"the editorless backend does not know target {config.target!r}; it writes "
            f"{known}. The shipped 7DTD client loads a StandaloneWindows64 bundle."
        ) from None
