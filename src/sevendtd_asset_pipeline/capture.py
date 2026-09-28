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

The manifest holds one entry per label: re-capturing a label replaces its
earlier entry, each carrying the observable, the backend that took it, and the
image's own hash and mtime. The verdict field is deliberately left `null` —
nothing here writes a pass.

Recording is a read-modify-write of one shared file, and this host runs several
agent sessions at once, so both halves of a record are serialized: the frame is
written to a writer-unique staged name and renamed into place, and the manifest
read-modify-write happens under an flock sidecar beside it — the same
serialization discipline as the shared client lock (see `client.py` and
docs/sibling-repos.md). Without that, two captures publishing together lose one
sign-off record silently, which is the worst kind of evidence to lose. Where
flock does not exist (a native Windows client) recording degrades to the
unsynchronized write rather than refusing evidence.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path

from . import atomic, evidence
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

    Every invocation is a fixed argv plus the output path, and full screen only,
    deliberately. The client under acceptance is fullscreen, and every
    per-window variant needs a compositor-specific way to name the window; one
    that picked the wrong window would capture a terminal and file it as
    evidence.
    """

    name: str
    sessions: tuple[str, ...]
    """"wayland", "x11", or both."""
    argv: tuple[str, ...]

    def command(self, output: Path) -> list[str]:
        return [*self.argv, str(output)]


# Ordered by preference within a session type. `import` is last on X11 because
# ImageMagick's delegate can be slower than a purpose-built grabber, but it is
# the one most likely to already be installed for the icon lane.
BACKENDS: tuple[Backend, ...] = (
    Backend("grim", ("wayland",), argv=("grim",)),
    Backend("spectacle", ("wayland", "x11"), argv=("spectacle", "-b", "-n", "-f", "-o")),
    Backend("gnome-screenshot", ("wayland", "x11"), argv=("gnome-screenshot", "-f")),
    Backend("maim", ("x11",), argv=("maim",)),
    Backend("scrot", ("x11",), argv=("scrot", "-o")),
    Backend("import", ("x11",), argv=("import", "-window", "root")),
)


def session_type(env: dict[str, str] | None = None) -> str:
    """ "wayland", "x11", or "none" — which decides the usable backends."""
    environment = os.environ if env is None else env
    declared = (environment.get("XDG_SESSION_TYPE") or "").strip().lower()
    if declared in ("wayland", "x11"):
        return declared
    if environment.get("WAYLAND_DISPLAY"):
        return "wayland"
    if environment.get("DISPLAY"):
        return "x11"
    return "none"


def available_backends(env: dict[str, str] | None = None) -> list[Backend]:
    """The installed backends that can serve the current session, in order."""
    session = session_type(env)
    if session == "none":
        return []
    return [
        backend
        for backend in BACKENDS
        if session in backend.sessions and shutil.which(backend.name)
    ]


def _require_backend(env: dict[str, str] | None = None) -> Backend:
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
    names = ", ".join(backend.name for backend in BACKENDS if session in backend.sessions)
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


def _utc_mtime(mtime: float) -> str:
    """A file mtime as `<UTC ISO8601 Z>`, independent of the host timezone.

    Built from an aware UTC datetime, not `time.gmtime` + a literal `Z`. The
    stamp is the file's own modification instant; a host in `America/New_York`
    during EDT must not emit `12:00Z` for a file written at 16:00 UTC.
    """
    return datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _captured_instant(record: Mapping[str, object]) -> datetime | None:
    """A record's `captured_at` as an aware datetime, or None when unreadable.

    The stamp is a wall-clock-independent UTC instant (`_utc_mtime`), so it
    orders captures across a host that changed timezone or a machine whose
    clock moved. An offset-less stamp is UTC, as everywhere else in this
    repository's protocol; anything else is not ordered rather than guessed.
    """
    value = record.get("captured_at")
    if not isinstance(value, str) or not value:
        return None
    stamp = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def read_manifest(root: Path) -> list[dict[str, object]]:
    """Every capture recorded under `root`, oldest first. Missing is empty.

    Oldest first is the `captured_at` order, not the order the file happens to
    hold: adoption records the instant the frame was taken, so a clip captured
    yesterday and adopted today belongs ahead of one captured an hour ago, and
    a manifest that listed it last would contradict the stamp printed beside
    it. Entries sharing a second (the stamp's resolution) keep their recorded
    order, and a record whose stamp cannot be read is left where it is rather
    than sorted on a guess.
    """
    path = Path(root) / MANIFEST_NAME
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot read the capture manifest {path}: {exc}") from exc
    if not isinstance(data, list):
        raise PipelineError(f"{path} is not a list of captures; move it aside")
    ordered: list[tuple[datetime, dict[str, object]]] = []
    for item in data:
        if not isinstance(item, dict):
            return data
        moment = _captured_instant(item)
        if moment is None:
            return data
        ordered.append((moment, item))
    return [item for _, item in sorted(ordered, key=lambda pair: pair[0])]


def _write_manifest(root: Path, entries: list[dict[str, object]]) -> Path:
    """Replace the manifest atomically, so an interrupted run cannot truncate it.

    The temporary name carries this process's pid plus a random suffix and is
    unlinked on every exit path (`atomic.staged_write`): a fixed `<name>.tmp`
    is shared by two concurrent writers truncating one file, and a body
    half-written when a run dies must never survive as state.
    """
    path = Path(root) / MANIFEST_NAME
    body = json.dumps(entries, indent=2, sort_keys=True) + "\n"
    with atomic.staged_write(path) as staged:
        staged.write_text(body, encoding="utf-8", newline="\n")
    return path


@contextmanager
def _manifest_lock(root: Path) -> Iterator[None]:
    """Serialize one read-modify-write of the manifest across processes.

    `_record` reads every entry, drops the label being replaced, appends, and
    publishes. Two captures running that sequence together lose one entry:
    each writes from its own snapshot, and the second publish erases the
    first's append. This host runs several agent sessions at once — the shared
    client lock exists for exactly that reason — so the whole sequence holds an
    exclusive flock on a sidecar beside the manifest. Function scope keeps the
    Unix-only module out of every import; a host without flock has no protocol
    to join, so recording degrades to today's unsynchronized write instead of
    refusing evidence.
    """
    if find_spec("fcntl") is None:
        yield
        return
    import fcntl

    sidecar = Path(root) / f"{MANIFEST_NAME}.flock"
    with open(sidecar, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _staged_path(destination: Path) -> Path:
    """A writer-unique temporary name beside `destination`, like atomic.staged_write."""
    return destination.with_name(f".{destination.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")


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

    # The grabber aims at a writer-unique staged name, not the cited path: two
    # captures of one label then cannot interleave writes into one image, and
    # an interrupted grab strands a dot-temp instead of a half frame where the
    # manifest would cite it.
    staged = _staged_path(output)
    try:
        argv = backend.command(staged)
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
        if not staged.is_file() or staged.stat().st_size == 0:
            raise PipelineError(
                f"{backend.name} exited zero but wrote no image to {output}. A screenshot "
                "tool that cannot reach the compositor often reports success; try another "
                "backend, or capture by hand and record it with --file."
            )
        return _record(
            staged,
            output,
            label.strip(),
            observable.strip(),
            backend.name,
            session_type(env),
            directory,
        )
    finally:
        staged.unlink(missing_ok=True)


@dataclass
class ClipFile:
    """One file inside an adopted clip directory, hashed and addressed."""

    name: str
    sha256: str
    bytes: int


@dataclass
class ClipCapture:
    """One adopted clip directory, and what it was adopted to show.

    The clip is the `7dtd-playtest` multi-frame capture shape: a directory of
    `frame-XXXX.png` frames and optionally a muxed video. Adoption records the
    clip's media under the label and hashes every file it copied, so a later
    `review-video` reads a stable, hash-addressed input instead of re-deriving
    it from wherever the clip was captured. Non-media files that share the
    capture directory, `client.log` above all, are not adopted: the evidence
    tree deploys with the modlet and is handed to an external review.
    """

    label: str
    observable: str
    directory: str
    """The directory name under the evidence root."""
    files: list[ClipFile] = field(default_factory=list)
    backend: str = "adopted-clip"
    captured_at: str = ""
    verdict: str | None = None
    """Always null when written. A sign-off is a person's, added by hand."""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


_CLIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mov")


def _reject_symlinks(path: Path, *, role: str) -> None:
    """Refuse a tree `copytree`/`copy2` would follow out of the source.

    Adoption copies an untrusted directory into the evidence tree. A symlink
    inside it would publish whatever that link currently points at, hashed
    and cited as if it had been captured.
    """
    if path.is_symlink():
        raise PipelineError(
            f"refusing to adopt {role}: it is a symlink, and adoption copies "
            "the captured files, not whatever the link currently points at"
        )
    if path.is_dir():
        for child in path.iterdir():
            _reject_symlinks(child, role=str(child))


def record_existing_clip(
    source_dir: Path | str,
    label: str,
    observable: str = "",
    root: Path | str = DEFAULT_ROOT,
) -> ClipCapture:
    """Adopt an already-captured clip directory into the evidence tree.

    The one-level-up form of `record_existing`: instead of one screenshot,
    adopt the `7dtd-playtest` clip directory (frames and the muxed video) into
    `<root>/<safe-label>/`, hashed and labeled the same way a single adopted
    screenshot already is. Everything else in the capture directory, the
    `client.log` above all, stays behind (see `_skip_non_media`): the evidence
    tree is what deploys and what an external review is handed. Re-adopting a
    label replaces its earlier entry, exactly like a re-captured single frame.
    Nothing here re-captures, muxes, or reviews anything — adoption only.
    """
    source = Path(source_dir)
    if not label.strip():
        raise PipelineError("a clip adoption needs a label; it is how the clip is cited later")
    if not source.is_dir():
        raise PipelineError(f"no such clip directory: {source}")
    _reject_symlinks(source, role=str(source))
    if not _looks_like_a_clip(source):
        raise PipelineError(
            f"{source} does not look like a clip: it holds neither frame images "
            "(frame-*.png) nor a muxed video. Adopt a `7dtd-playtest` clip directory, "
            "e.g. `.local/capture/<suite>-<stamp>/<case>/`."
        )
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    safe = _safe_stem(label.strip())
    destination = directory / safe
    in_place = source.resolve() == destination.resolve()
    staged: Path | None = None
    if not in_place:
        staged = directory / f".{safe}.clip.tmp.{os.getpid()}.{secrets.token_hex(4)}"
        try:
            shutil.copytree(source, staged, dirs_exist_ok=False, ignore=_skip_non_media)
        except (OSError, shutil.Error) as exc:
            shutil.rmtree(staged, ignore_errors=True)
            raise PipelineError(f"cannot copy clip {source} into evidence: {exc}") from exc
        except BaseException:
            # A Ctrl+C between two copied frames is the one this module's other
            # staged writes all survive, and an `except (OSError, ...)` alone
            # lets it strand a half-copied `.clip.tmp` directory under the
            # evidence root, which deploys with the modlet.
            shutil.rmtree(staged, ignore_errors=True)
            raise

    # Hash the tree that is about to become the destination, and take its
    # stamp, before the lock and before the earlier recording is removed. Read
    # them afterwards and a single unreadable frame would destroy the previous
    # sign-off, leave the new tree on disk, and put a traceback on the terminal
    # in place of the ERROR line every other failure here produces.
    files = _clip_files(staged if staged is not None else destination)
    try:
        captured_at = _utc_mtime(
            max(source.stat().st_mtime, destination.stat().st_mtime if in_place else 0)
        )
    except OSError as exc:
        raise PipelineError(f"cannot read the timestamps of the clip being adopted: {exc}") from exc
    try:
        with _manifest_lock(directory):
            if not in_place:
                if destination.exists():
                    if not destination.is_dir():
                        raise PipelineError(
                            f"{destination} exists and is not a directory; move it aside before "
                            "adopting this clip"
                        )
                    shutil.rmtree(destination)
                if staged is None:  # unreachable: staged is set whenever not in_place
                    raise PipelineError("internal error: no staged copy for the adopted clip")
                staged.replace(destination)
            entry = ClipCapture(
                label=label.strip(),
                observable=observable.strip(),
                directory=safe,
                files=files,
                backend="adopted-clip",
                captured_at=captured_at,
                notes=(
                    []
                    if observable
                    else ["no observable recorded; a clip without one proves nothing"]
                ),
            )
            entries = [item for item in read_manifest(directory) if item.get("label") != label]
            entries.append(entry.as_dict())
            _write_manifest(directory, entries)
    finally:
        if staged is not None and staged.exists():
            shutil.rmtree(staged, ignore_errors=True)
    return entry


def _looks_like_a_clip(directory: Path) -> bool:
    """Whether this directory holds clip media, at the top level or nested.

    A harness nests its frames one level down (`<case>/cam/frame-0000.png`),
    and `_skip_non_media` descends to copy them, so the check that admits the
    directory has to look where the copy looks.
    """
    try:
        entries = list(directory.iterdir())
    except OSError:
        return False
    for entry in entries:
        if entry.is_file() and entry.suffix.lower() in _CLIP_SUFFIXES:
            return True
        if entry.is_dir() and not entry.is_symlink():
            try:
                if any(
                    nested.is_file() and nested.suffix.lower() in _CLIP_SUFFIXES
                    for nested in entry.iterdir()
                ):
                    return True
            except OSError:
                continue
    return False


def _skip_non_media(directory: str, names: list[str]) -> set[str]:
    """`copytree` ignore hook: adopt the clip, leave everything else where it is.

    A `7dtd-playtest` capture directory sits next to the `client.log` the run
    wrote. That log carries the whole host: absolute paths under the operator's
    account, the game install, every mod name loaded, the session's timestamps.
    Nothing about a visual sign-off needs it, and adoption is the step that
    moves the directory into the modlet where `client deploy` ships it and
    `review-video` hands it to an external gateway. So only frames and the muxed
    video are copied, and the log stays in the live log directory it belongs to.

    Directories are always descended: a clip nests its frames one level down in
    some harnesses, and a name is not a role.
    """
    base = Path(directory)
    return {
        name
        for name in names
        if not (base / name).is_dir() and (base / name).suffix.lower() not in _CLIP_SUFFIXES
    }


def _clip_files(root: Path) -> list[ClipFile]:
    """Every file in an adopted clip, digested, in a stable order.

    A read error names the file it was reading: without one, a frame that
    cannot be hashed is a bare `OSError` escaping to a traceback, and the
    operator is left guessing which of several thousand frames failed.
    """
    entries = sorted(root.rglob("*"))
    files: list[ClipFile] = []
    for entry in entries:
        if not entry.is_file():
            continue
        try:
            files.append(_clip_file(entry, root))
        except OSError as exc:
            raise PipelineError(f"cannot read the adopted clip file {entry}: {exc}") from exc
    return files


def _clip_file(path: Path, root: Path) -> ClipFile:
    """One adopted file, addressed by its path inside the clip directory.

    A bare basename is not an address: `_skip_non_media` descends into
    subdirectories because a clip nests its frames one level down in some
    harnesses, and two harnesses can both contribute `frame-0001.png`. The
    relative POSIX path is what locates the file in the adopted tree, and it is
    what a later `review-video` reads back.
    """
    return ClipFile(
        name=path.relative_to(root).as_posix(),
        sha256=evidence.sha256_file(path)[0],
        bytes=path.stat().st_size,
    )


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
    if source.is_symlink():
        raise PipelineError(
            f"refusing to adopt {source}: it is a symlink, and adoption copies "
            "the captured file, not whatever the link currently points at"
        )
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{_safe_stem(label.strip())}{source.suffix or '.png'}"
    # Copied to a staged name rather than straight onto the destination, so a
    # copy that dies midway leaves the previous frame at the cited path.
    staged = None
    if source.resolve() != destination.resolve():
        staged = _staged_path(destination)
        try:
            shutil.copy2(source, staged)
        except OSError as exc:
            staged.unlink(missing_ok=True)
            raise PipelineError(
                f"cannot copy the supplied frame {source} into {destination}: {exc}"
            ) from exc
    try:
        return _record(
            destination if staged is None else staged,
            destination,
            label.strip(),
            observable.strip(),
            "provided",
            session_type(),
            directory,
        )
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def _record(
    staged: Path,
    final: Path,
    label: str,
    observable: str,
    backend: str,
    session: str,
    directory: Path,
) -> Capture:
    """Publish one frame and enter it into the manifest as one serialized step.

    The rename and the manifest read-modify-write hold the same sidecar flock:
    published separately, another capture's record could slip between them, or
    ours between theirs — either way one recorded sign-off disappears. The
    digest is taken from `staged` before the lock, because those bytes are this
    run's own; when `staged` is already `final` (a provided image recorded in
    place) there is nothing to move. On any failure the staged name is unlinked
    and the previous frame and manifest stand.
    """
    source_is_final = staged == final
    stat = staged.stat()
    entry = Capture(
        label=label,
        observable=observable,
        file=final.name,
        backend=backend,
        session=session,
        bytes=stat.st_size,
        sha256=evidence.sha256_file(staged)[0],
        captured_at=_utc_mtime(stat.st_mtime),
        notes=[] if observable else ["no observable recorded; a frame without one proves nothing"],
    )
    try:
        with _manifest_lock(directory):
            if not source_is_final:
                staged.replace(final)
            entries = [item for item in read_manifest(directory) if item.get("label") != label]
            entries.append(entry.as_dict())
            _write_manifest(directory, entries)
    finally:
        # Only a staged name may be unlinked: when it already was `final`,
        # this frame is the caller's own file and the record cites it.
        if not source_is_final:
            staged.unlink(missing_ok=True)
    return entry
