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


def executable() -> str:
    """The pinned unityz on PATH, after the capability probe agreed it is usable."""
    require_capability("unityz")
    found = shutil.which("unityz")
    if found is None:  # The capability probe and execution share one answer.
        raise PipelineError("unityz disappeared from PATH after its capability check")
    return found


def invoke(command: str, *arguments: str, subject: str) -> subprocess.CompletedProcess[str]:
    """Run one bounded unityz process; `subject` names the input in errors."""
    try:
        return subprocess.run(
            [executable(), command, *arguments],
            capture_output=True,
            text=True,
            timeout=UNITYZ_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(
            f"unityz {command} timed out after {UNITYZ_TIMEOUT_SECONDS}s for {subject}"
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise PipelineError(f"cannot run unityz {command} for {subject}: {exc}") from exc


def failure(command: str, result: subprocess.CompletedProcess[str], subject: str) -> PipelineError:
    raw_detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
    detail = " | ".join(line.strip() for line in raw_detail.splitlines() if line.strip())
    return PipelineError(
        f"unityz {command} failed for {subject} (exit {result.returncode}): {detail}"
    )


class Unityz:
    """One resolved unityz executable applied repeatedly to one input file."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        if not self.path.is_file():
            raise PipelineError(f"cannot read unityz input {self.path}: no such file")
        self.executable = executable()

    def _invoke(self, command: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return invoke(command, str(self.path), *arguments, subject=str(self.path))

    def _failure(self, command: str, result: subprocess.CompletedProcess[str]) -> PipelineError:
        return failure(command, result, subject=str(self.path))

    def json(self, command: str, *arguments: str) -> JsonObject:
        """Run a command whose successful stdout is one JSON object."""
        result = self._invoke(command, *arguments)
        if result.returncode != 0:
            raise self._failure(command, result)
        return self._decode_object(command, result.stdout)

    def text(self, command: str, *arguments: str) -> str:
        """Run a command whose successful stdout is human-readable text."""
        result = self._invoke(command, *arguments)
        if result.returncode != 0:
            raise self._failure(command, result)
        return result.stdout

    def json_report(self, command: str, *arguments: str) -> JsonObject:
        """Decode a JSON verdict even when findings make the command non-zero.

        Verification commands use exit 1 to report failed objects while still
        returning their complete machine-readable report. A process failure
        with no valid report remains an error.
        """
        result = self._invoke(command, *arguments)
        try:
            return self._decode_object(command, result.stdout)
        except PipelineError:
            if result.returncode != 0:
                raise self._failure(command, result) from None
            raise

    def json_lines(self, command: str, *arguments: str) -> list[JsonObject]:
        """Run a command that emits one JSON object per SerializedFile."""
        result = self._invoke(command, *arguments)
        if result.returncode != 0:
            raise self._failure(command, result)
        documents: list[JsonObject] = []
        for line_number, line in enumerate(result.stdout.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PipelineError(
                    f"unityz {command} returned invalid JSON on line {line_number} "
                    f"for {self.path}: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise PipelineError(
                    f"unityz {command} returned a non-object on line {line_number} for {self.path}"
                )
            documents.append(value)
        return documents

    def _decode_object(self, command: str, output: str) -> JsonObject:
        try:
            value = json.loads(output)
        except json.JSONDecodeError as exc:
            raise PipelineError(
                f"unityz {command} returned invalid JSON for {self.path}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise PipelineError(
                f"unityz {command} returned JSON that is not an object for {self.path}"
            )
        return value


def run_json(command: str, path: Path, *arguments: str) -> JsonObject:
    """Run one unityz JSON command through a newly resolved reader."""
    return Unityz(path).json(command, *arguments)


def run_json_lines(command: str, path: Path, *arguments: str) -> list[JsonObject]:
    """Run one unityz JSON-lines command through a newly resolved reader."""
    return Unityz(path).json_lines(command, *arguments)
