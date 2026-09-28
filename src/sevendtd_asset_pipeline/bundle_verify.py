"""Load a bundle in a real Unity runtime and report what came back.

The editorless writer inverts this project's relationship with Unity: the
editor stops being what *produces* the artifact and becomes one of the things
that can *check* it. That check is worth having whenever an editor exists,
because it is the only offline evidence that is not this repository grading its
own homework — `AssetBundle.LoadFromFile` is the engine's own loader, the same
call the game makes, and `LoadAsset` deserializes each object with the engine's
own class definitions rather than with a parser we wrote.

It is optional in the strict sense: nothing needs it to build, validate or
ship, and its absence is reported rather than assumed away.

It is still not acceptance. It proves the container and the objects survive a
runtime of the same revision; it says nothing about whether the asset is
right, and nothing about 7 Days to Die's own loading path. That remains a
fresh client and a person, as everywhere else in this pipeline.

A host runs several agent sessions at once, and two of them can reach this
command on the same mod. The throwaway project they share is written atomically
for that reason, and each run's editor writes and reads its own log (see
:func:`run_log_name`), so no run classifies another run's evidence.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from . import atomic
from .errors import PipelineError
from .unity_process import run_unity

VERIFIER_SCRIPT = "BundleVerifier.cs"
EDITOR_FOLDER = "Assets/SevenDaysToDieAssetPipeline/Editor"
# The verifier prints one line per asset; anything else in a Unity log is noise
# from a batch-mode editor starting up.
ASSET_LINE = re.compile(r"^VERIFY-ASSET: (?P<key>\S+) -> (?P<type>\w+) named '(?P<name>[^']*)'")
DETAIL_LINE = re.compile(r"^VERIFY-(?:TEX|CLIP|TEXT|MESH|PREFAB): (?P<detail>.*)$")


def run_log_name() -> str:
    """A log file name no other invocation of this command is writing.

    Every run of ``verify-bundle`` shares one work directory, because the
    throwaway project under it is expensive to re-import and holds no assets
    worth keeping. The log cannot be shared with it: the editor truncates the
    ``-logFile`` it was given, so two runs pointing at the same name interleave
    one file, and each run then classifies whatever lines happen to be in it.
    That is the worst failure this command has, because it does not look like
    one — a session can read a PASS, or a FAIL, that belongs to another
    session's bundle and has no way to tell. The name carries this process's
    pid plus a random suffix, so two runs of the same pid over its lifetime
    still cannot collide.
    """
    return f"verify-{os.getpid()}-{secrets.token_hex(4)}.log"


@dataclass
class LoadedAsset:
    key: str
    """The name the bundle answers to, as the runtime reported it."""
    type: str
    name: str
    detail: str = ""


@dataclass
class VerifyReport:
    bundle: str
    log: str
    ok: bool
    assets: list[LoadedAsset] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "bundle": self.bundle,
            "log": self.log,
            "ok": self.ok,
            "assets": [asset.__dict__ for asset in self.assets],
            "problems": self.problems,
        }


def _scratch_project(directory: Path, unity_version: str) -> Path:
    """A throwaway project that exists only to host the verifier script.

    A synthesized-bundle mod has no Unity project — that is the point of it —
    so the check brings its own. It lives under the ignored build directory and
    holds no assets, so re-creating it costs one import of a single script.

    Its files are published, not written in place. The directory is shared by
    every run of this command on this mod, and the editor of a run already in
    progress is reading these three files: a plain ``write_text`` truncates
    first, so a concurrent run's import can read a half-written
    ``BundleVerifier.cs`` or a truncated ``ProjectVersion.txt`` and fail on the
    other run's evidence. A rename is atomic, so the editor sees the previous
    complete file or the new one.
    """
    project = directory / "verify-project"
    (project / EDITOR_FOLDER).mkdir(parents=True, exist_ok=True)
    (project / "ProjectSettings").mkdir(parents=True, exist_ok=True)
    (project / "Packages").mkdir(parents=True, exist_ok=True)
    atomic.write(
        project / "ProjectSettings" / "ProjectVersion.txt",
        f"m_EditorVersion: {unity_version}\n",
    )
    # The AssetBundle module must be present here for the same reason it must
    # be present in a build: without it the runtime has no loader to call.
    atomic.write(
        project / "Packages" / "manifest.json",
        json.dumps(
            {
                "dependencies": {
                    "com.unity.modules.assetbundle": "1.0.0",
                    "com.unity.modules.audio": "1.0.0",
                    "com.unity.modules.imageconversion": "1.0.0",
                }
            },
            indent=2,
        )
        + "\n",
    )
    source = files("sevendtd_asset_pipeline").joinpath(
        f"templates/UnityProject/{EDITOR_FOLDER}/{VERIFIER_SCRIPT}"
    )
    atomic.write(project / EDITOR_FOLDER / VERIFIER_SCRIPT, source.read_text(encoding="utf-8"))
    return project


def verify_with_editor(
    bundle: Path,
    editor: Path | None,
    unity_version: str,
    work_dir: Path,
    timeout: int = 900,
    draw: bool = False,
) -> VerifyReport:
    """Run a batch-mode editor that loads `bundle` and reads every asset in it.

    `draw` additionally photographs each prefab and reports how much of the
    frame it filled, which is the only offline answer to "does it rasterize" —
    a prefab whose shader reads its matrices from the wrong offsets loads
    perfectly and draws somewhere the camera is not. It needs a real graphics
    device (so no `-nographics`, and `xvfb-run -a` on a headless host), which
    is why it is opt-in rather than the default.

    `work_dir` is shared by every run of this command on this mod, because the
    throwaway project under it is expensive to re-import and holds no assets.
    The log does not follow it: each run names its own (see
    :func:`run_log_name`) and classifies only that one, so a concurrent run
    cannot report this bundle's verdict from the other bundle's editor.
    """
    if editor is None:
        raise PipelineError(
            "verifying a bundle in a real runtime needs an editor: set UNITY_EDITOR. "
            "It is optional — nothing needs it to build or ship — but it is the only "
            "offline check this repository does not also author."
        )
    if not editor.is_file():
        raise PipelineError(f"Unity editor is not executable: {editor}")
    bundle = bundle.resolve()
    if not bundle.is_file():
        raise PipelineError(f"no bundle to verify at {bundle}")
    work_dir.mkdir(parents=True, exist_ok=True)
    project = _scratch_project(work_dir, unity_version)
    log = work_dir / run_log_name()
    # `-nographics` makes Camera.Render() draw nothing rather than fail, so a
    # run that wants to know whether the prefab *rasterizes* must not pass it.
    # Everything else this verifier does is a load, which needs no device, so
    # the fast headless path stays the default and drawing is opted into.
    graphics = [] if draw else ["-nographics"]
    command = [
        str(editor),
        "-batchmode",
        *graphics,
        *(["-shamwayDraw"] if draw else []),
        "-projectPath",
        str(project),
        "-executeMethod",
        "SevenDaysToDie.AssetPipeline.BundleVerifier.Verify",
        "-logFile",
        str(log),
        "-bundle",
        str(bundle),
        "-quit",
    ]
    try:
        result = run_unity(command, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # TimeoutExpired is not a TimeoutError, so without this it escapes
        # cli.main's handler as a raw traceback. run() has killed the editor.
        raise PipelineError(
            f"the editor did not finish verifying within {timeout}s and was killed; "
            f"its partial log is {log}. Rule out a hang before raising the limit."
        ) from exc
    return _classify(bundle, log, result.returncode)


def _classify(bundle: Path, log: Path, exit_code: int) -> VerifyReport:
    report = VerifyReport(bundle=str(bundle), log=str(log), ok=False)
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise PipelineError(f"cannot read the verifier log {log}: {exc}") from exc
    for raw_line in lines:
        line = raw_line.strip()
        match = ASSET_LINE.match(line)
        if match:
            report.assets.append(LoadedAsset(match["key"], match["type"], match["name"]))
            continue
        detail = DETAIL_LINE.match(line)
        if detail and report.assets:
            report.assets[-1].detail = detail["detail"]
        if line.startswith("VERIFY-FAIL"):
            report.problems.append(line)
    if exit_code != 0 and not report.problems:
        report.problems.append(
            f"the editor exited {exit_code} without loading the bundle; read {log}"
        )
    if not report.assets and not report.problems:
        report.problems.append("the runtime loaded the bundle but it contains no assets to read")
    report.ok = not report.problems
    return report
