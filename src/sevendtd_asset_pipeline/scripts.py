"""The host scripts, reachable from an installed `shamway` without a checkout.

`install-tools.sh`, `install-unity-editor.sh`, `compile-editor-scripts.sh`,
`playtest-acceptance.sh` and `playtest-synthesized.sh` are host-setup and
acceptance steps a mod needs once per machine. A mod is told never to keep
a path into a checkout of this repository, so the scripts ship inside the
package (staged by setup.py, the way docs/ is) and run as

    shamway script install-tools --with-authoring
    shamway script install-unity-editor --project tools/shamway/UnityProject
    shamway script compile-editor-scripts --scripts tools/shamway/UnityProject/Assets/SevenDaysToDieAssetPipeline/Editor

`shamway script --list` names them; `shamway script NAME --path` prints the
file so a person can read it before running it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

from .errors import PipelineError

SCRIPTS: dict[str, tuple[str, str]] = {
    "install-tools": (
        "install-tools.sh",
        "host packages: base, --with-authoring, --with-unity-prereqs, --with-desktop-capture, --with-research",
    ),
    "install-unity-editor": (
        "install-unity-editor.sh",
        "the game-matched Unity editor and Windows Build Support, checksum-verified",
    ),
    "compile-editor-scripts": (
        "compile-editor-scripts.sh",
        "compile editor C# against a real editor's assemblies, no editor started",
    ),
    "playtest-acceptance": (
        "playtest-acceptance.sh",
        "run the mod's bundle-acceptance suite in a live client, via hordeforge/7dtd-playtest",
    ),
    "playtest-synthesized": (
        "playtest-synthesized.sh",
        "self test: build a bundle with no editor and prove a live client loads every object",
    ),
}


def _root() -> Path:
    packaged = files("sevendtd_asset_pipeline").joinpath("scripts")
    if packaged.is_dir():
        return Path(str(packaged))
    source = Path(__file__).resolve().parents[2] / "scripts"
    if source.is_dir():
        return source
    raise PipelineError("the packaged scripts are missing; reinstall the pipeline")


def path(name: str) -> Path:
    try:
        filename = SCRIPTS[name][0]
    except KeyError:
        raise PipelineError(
            f"unknown script {name!r}; expected one of: {', '.join(SCRIPTS)}"
        ) from None
    script = _root() / filename
    if not script.is_file():
        raise PipelineError(f"packaged script is missing: {script}")
    return script


def describe() -> list[dict[str, str]]:
    return [
        {"name": name, "file": filename, "summary": summary}
        for name, (filename, summary) in SCRIPTS.items()
    ]


def run(name: str, argv: list[str]) -> int:
    script = path(name)
    if argv[:1] == ["--path"]:
        print(script)
        return 0
    env = dict(os.environ)
    env.setdefault("SHAMWAY_SCRIPT_ROOT", str(script.parent))
    # bash resolves over PATH by design; the scripts are shipped host tooling.
    try:
        result = subprocess.run(["bash", str(script), *argv], check=False, env=env)  # noqa: S607
    except OSError as exc:
        raise PipelineError(f"cannot run {script} through bash: {exc}") from exc
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in ("--list", "-h", "--help"):
        for entry in describe():
            print(f"{entry['name']:24} {entry['summary']}")
        print()
        print("Run one with: shamway script NAME [ARGS...]   (--path prints the file)")
        return 0
    return run(arguments[0], arguments[1:])
