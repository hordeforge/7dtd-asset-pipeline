"""The bounded subprocess boundary to the pinned ``unityz`` reader.

Unity data parsing belongs to unityz. This module owns only process failure,
JSON decoding, and the actionable errors the Python API promises its callers.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .capabilities import require_capability
from .errors import PipelineError

UNITYZ_TIMEOUT_SECONDS = 120
JsonObject = dict[str, object]


def _run(command: str, path: Path, *arguments: str) -> str:
    path = path.resolve()
    if not path.is_file():
        raise PipelineError(f"cannot read Unity asset {path}: no such file")
    require_capability("unityz")
    executable = shutil.which("unityz")
    if executable is None:  # The capability probe and execution share one answer.
        raise PipelineError("unityz disappeared from PATH after its capability check")
    try:
        result = subprocess.run(
            [executable, command, str(path), *arguments],
            capture_output=True,
            text=True,
            timeout=UNITYZ_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(
            f"unityz {command} timed out after {UNITYZ_TIMEOUT_SECONDS}s for {path}"
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise PipelineError(f"cannot run unityz {command} for {path}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
        raise PipelineError(
            f"unityz {command} could not read {path} (exit {result.returncode}): {detail}"
        )
    return result.stdout


def run_json(command: str, path: Path, *arguments: str) -> JsonObject:
    """Run one unityz command whose successful stdout is one JSON object."""
    output = _run(command, path, *arguments)
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise PipelineError(f"unityz {command} returned invalid JSON for {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"unityz {command} returned JSON that is not an object for {path}")
    return value


def run_json_lines(command: str, path: Path, *arguments: str) -> list[JsonObject]:
    """Run one unityz command that emits one JSON object per SerializedFile."""
    output = _run(command, path, *arguments)
    documents: list[JsonObject] = []
    for line_number, line in enumerate(output.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PipelineError(
                f"unityz {command} returned invalid JSON on line {line_number} for {path}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise PipelineError(
                f"unityz {command} returned a non-object on line {line_number} for {path}"
            )
        documents.append(value)
    return documents
