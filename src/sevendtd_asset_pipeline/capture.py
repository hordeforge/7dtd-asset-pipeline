"""Capture what a person saw, so a visual sign-off leaves an artefact.

Every gate in this pipeline is offline, and every one of them is explicitly
*not sufficient*: acceptance ends with a fresh client and a human look or
listen at the changed asset. That last step is the only one with no output. A
suite can prove a sprite resolves, a prefab loaded, a sound group exists; only
a person can say the icon reads as the thing it is at inventory scale, the
held mesh sits right in the hand, or the paint is not wet plastic.

This does not make that judgement and must never appear to. It records the
frame the judgement was made on, alongside the observable the reviewer was
asked to check, so "looks right" stops being an unciteable claim in a chat log
and becomes a file some later session can reopen and disagree with.

    shamway client capture held-nuke --observable "held upright, not sunk into the hand"
    shamway client capture --list

The manifest accumulates across a run: one entry per capture, each with the
observable, the backend that took it, and the image's own hash and mtime. The
verdict field is deliberately left `null` — nothing here writes a pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .errors import PipelineError

MANIFEST_NAME = "manifest.json"
DEFAULT_ROOT = Path(".local/acceptance")


@dataclass(frozen=True)
class Backend:
    """One screenshot tool, and the session type it can actually serve.

    A Wayland session cannot be captured by an X11 tool, and the failure is not
    an error — `import` under Wayland returns a black or garbage frame with a
    zero exit code. So the session type selects the candidates rather than
    merely ordering them.
    """

    name: str
    sessions: tuple[str, ...]
    """"wayland", "x11", or both."""

    def command(self, output: Path) -> list[str]:
        raise NotImplementedError


@dataclass(frozen=True)
class _Simple(Backend):
    """A backend whose whole invocation is a fixed argv plus the output path.

    Full screen only, deliberately. The client under acceptance is fullscreen,
    and every per-window variant needs a compositor-specific way to name the
    window; one that picked the wrong window would capture a terminal and file
    it as evidence.
    """

    argv: tuple[str, ...] = ()

    def command(self, output: Path) -> list[str]:
        return [*self.argv, str(output)]


# Ordered by preference within a session type. `import` is last on X11 because
# ImageMagick's delegate can be slower than a purpose-built grabber, but it is
# the one most likely to already be installed for the icon lane.
BACKENDS: tuple[_Simple, ...] = (
    _Simple("grim", ("wayland",), argv=("grim",)),
    _Simple("spectacle", ("wayland", "x11"), argv=("spectacle", "-b", "-n", "-f", "-o")),
    _Simple("gnome-screenshot", ("wayland", "x11"), argv=("gnome-screenshot", "-f")),
    _Simple("maim", ("x11",), argv=("maim",)),
    _Simple("scrot", ("x11",), argv=("scrot", "-o")),
    _Simple("import", ("x11",), argv=("import", "-window", "root")),
)


def session_type(env: dict[str, str] | None = None) -> str:
    """"wayland", "x11", or "none" — which decides the usable backends."""
    environment = os.environ if env is None else env
    declared = (environment.get("XDG_SESSION_TYPE") or "").strip().lower()
    if declared in ("wayland", "x11"):
        return declared
    if environment.get("WAYLAND_DISPLAY"):
        return "wayland"
    if environment.get("DISPLAY"):
        return "x11"
    return "none"


def available_backends(env: dict[str, str] | None = None) -> list[_Simple]:
    """The installed backends that can serve the current session, in order."""
    session = session_type(env)
    if session == "none":
        return []
    return [
        backend
        for backend in BACKENDS
        if session in backend.sessions and shutil.which(backend.name)
    ]


def _require_backend(env: dict[str, str] | None = None) -> _Simple:
    session = session_type(env)
    if session == "none":
        raise PipelineError(
            "no desktop session to capture: neither WAYLAND_DISPLAY nor DISPLAY is "
            "set. A visual sign-off needs the display a person is actually looking "
            "at; Xvfb renders icons but proves nothing about what a player sees."
        )
    usable = available_backends(env)
    if usable:
        return usable[0]
    names = ", ".join(
        backend.name for backend in BACKENDS if session in backend.sessions
    )
    raise PipelineError(
        f"no screenshot tool for this {session} session; expected one of: {names}. "
        "Install one with: shamway script install-tools --with-desktop-capture"
    )


@dataclass
class Capture:
    """One recorded frame, and what the reviewer was asked to look for."""

    label: str
    observable: str
    file: str
    backend: str
    session: str
    bytes: int
    sha256: str
    captured_at: str
    """The image file's own mtime, in UTC. Not a claim about when a person looked."""

    verdict: str | None = None
    """Always null when written. A sign-off is a person's, added by hand."""

    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(root: Path) -> list[dict[str, object]]:
    """Every capture recorded under `root`, oldest first. Missing is empty."""
    path = Path(root) / MANIFEST_NAME
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot read the capture manifest {path}: {exc}") from exc
    if not isinstance(data, list):
        raise PipelineError(f"{path} is not a list of captures; move it aside")
    return data


def _write_manifest(root: Path, entries: list[dict[str, object]]) -> Path:
    """Replace the manifest atomically, so an interrupted run cannot truncate it.

    The temporary name carries this process's pid plus a random suffix and is
    unlinked on every exit path, like every other atomic writer in this
    package (`client._write_lock`, `build._atomic_copy`, the generators): a
    fixed `<name>.tmp` is shared by two concurrent writers truncating one file,
    and a body half-written when a run dies must never survive as state.
    """
    path = Path(root) / MANIFEST_NAME
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")
    try:
        temporary.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _safe_stem(label: str) -> str:
    """A label as a filename stem, so it cannot escape the evidence directory.

    Both capture paths share this: a label is how a frame is cited later, and
    `../../secrets.png` must never become where that frame is written.
    """
    return "".join(
        character if character.isalnum() or character in "-_" else "-" for character in label
    )


def capture(
    label: str,
    observable: str = "",
    root: Path | str = DEFAULT_ROOT,
    wait_seconds: float = 0.0,
    env: dict[str, str] | None = None,
) -> Capture:
    """Take one screenshot, record it, and append it to the manifest.

    `wait_seconds` is the operator's setup time: select the item, frame the
    shot, and let the countdown fire rather than alt-tabbing to a terminal and
    capturing that instead.
    """
    if not label.strip():
        raise PipelineError("a capture needs a label; it is how the frame is cited later")
    safe = _safe_stem(label.strip())
    backend = _require_backend(env)
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{safe}.png"

    if wait_seconds > 0:
        time.sleep(wait_seconds)

    argv = backend.command(output)
    try:
        result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PipelineError(f"{backend.name} could not run: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise PipelineError(
            f"{backend.name} failed ({result.returncode})"
            + (f": {detail[-1]}" if detail else "")
        )
    if not output.is_file() or output.stat().st_size == 0:
        raise PipelineError(
            f"{backend.name} exited zero but wrote no image to {output}. A screenshot "
            "tool that cannot reach the compositor often reports success; try another "
            "backend, or capture by hand and record it with --file."
        )

    return _record(output, label.strip(), observable.strip(), backend.name, session_type(env), directory)


def record_existing(
    file: Path | str,
    label: str,
    observable: str = "",
    root: Path | str = DEFAULT_ROOT,
) -> Capture:
    """Enter a screenshot somebody already took into the same manifest.

    A capture taken with the desktop's own hotkey is exactly as good as one
    taken here; what matters is that it ends up cited next to its observable.
    """
    source = Path(file)
    if not source.is_file():
        raise PipelineError(f"no such image: {source}")
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{_safe_stem(label.strip())}{source.suffix or '.png'}"
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return _record(destination, label.strip(), observable.strip(), "provided", session_type(), directory)


def _record(
    output: Path, label: str, observable: str, backend: str, session: str, directory: Path
) -> Capture:
    stat = output.stat()
    entry = Capture(
        label=label,
        observable=observable,
        file=output.name,
        backend=backend,
        session=session,
        bytes=stat.st_size,
        sha256=_digest(output),
        captured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
        notes=[] if observable else ["no observable recorded; a frame without one proves nothing"],
    )
    entries = [item for item in read_manifest(directory) if item.get("label") != label]
    entries.append(entry.as_dict())
    _write_manifest(directory, entries)
    return entry
