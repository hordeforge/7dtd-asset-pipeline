"""Fresh-client acceptance: the half of validation that runs in the real game.

Every offline gate in this package ends with the same sentence: acceptance is
a fresh client that loads the changed asset, plus a human look or listen. This
module is the plumbing for the first half of that sentence, so "fresh client"
is a mechanical definition rather than a hope:

* **where the client puts things** on a Proton host — its user data, its
  `Mods/` folder, and its log — derived from the game directory the pipeline
  already knows;
* **deploying** the modlet there, through an allow-list, so authoring files
  never ship by accident;
* **launching** through Steam with the test-friendly startup arguments, and
  refusing to launch over a client that is already running, because a bundle
  is cached for the session under its path and a reused process proves
  nothing;
* **muting** the client at the OS audio layer for runs that are not listening
  runs, and unmuting it again — including the saved WirePlumber state that
  otherwise keeps the game silent for normal play;
* **finding the log this launch wrote** (the client rewrites it every start)
  and **scanning it** for the positive lines that prove a mod, its atlas, and
  its localization loaded, and the negative lines that name each silent
  failure this pipeline knows;
* **capturing** the frame a person made a visual judgement on, paired with the
  observable they were asked to check, because that judgement is otherwise the
  one acceptance step that leaves no artefact at all (see `capture.py`).

Everything here reads the installed game and writes only below the client's
per-user data directory and the mod's `.local/acceptance/`, both outside the
install. Nothing in this module can prove an asset *looks* or *sounds* right;
it proves the client is fresh, the mod loaded, and the log is clean, records
what was on screen, and then hands the verdict to a person.

The facts it encodes come from the source project's playtest harness and
`docs/environment.md`, confirmed on a Proton client of V 3.1.0 b14; see
docs/validation.md and docs/research-provenance.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .errors import PipelineError

STEAM_APP_ID = 251570
# Proton launches the Windows client; the EAC wrapper is a second executable.
# Match the executables, not the bare substring: `7DaysToDie` also matches
# `7DaysToDie_Data` paths in tooling and the Linux dedicated server binary.
CLIENT_PROCESS_NAMES = ("7DaysToDie.exe", "7DaysToDie_EAC.exe")
# Arguments the client accepts on its command line; neither has a mute.
STARTUP_ARGS = ("-skipintro", "-skipnewsscreen=true")
LOG_GLOB = "output_log_client__*.txt"
# The deployable modlet. Anything not listed stays behind: authoring sources,
# the Unity project, the pipeline configuration, build state, documentation.
DEPLOY_ALLOWLIST = (
    "ModInfo.xml",
    "Config",
    "Resources",
    "UIAtlases",
    "Prefabs",
    "UI",
    "README.txt",
    "LICENSE",
    "LICENSE.txt",
)


# ----------------------------------------------------------------- locations


def steamapps_dir(game_dir: Path) -> Path | None:
    """The `steamapps/` directory that contains a Steam-installed game, or None."""
    for parent in Path(game_dir).resolve().parents:
        if parent.name == "steamapps":
            return parent
    return None


def compatdata_dir(game_dir: Path, app_id: int = STEAM_APP_ID) -> Path | None:
    """The Proton prefix for the game: `steamapps/compatdata/<app>/`."""
    steamapps = steamapps_dir(game_dir)
    if steamapps is None:
        return None
    return steamapps / "compatdata" / str(app_id)


def proton_user_data_dir(game_dir: Path, app_id: int = STEAM_APP_ID) -> Path | None:
    """Where the Proton client keeps its per-user data.

    `<prefix>/pfx/drive_c/users/steamuser/AppData/Roaming/7DaysToDie/` — the
    Windows `%APPDATA%` of the wine user. Its `Mods/` is where the client
    actually loads mods from on a Proton host, and its `logs/` is where the
    client log lands.
    """
    prefix = compatdata_dir(game_dir, app_id)
    if prefix is None:
        return None
    return prefix / "pfx/drive_c/users/steamuser/AppData/Roaming/7DaysToDie"


def client_log_dir(game_dir: Path | None, env: dict[str, str] | None = None) -> Path:
    """The directory the client writes `output_log_client__*.txt` into.

    `SEVEN_DAYS_TO_DIE_LOG_DIR` overrides the derivation, for a native Windows
    client or a non-standard prefix.
    """
    env = os.environ if env is None else env
    explicit = env.get("SEVEN_DAYS_TO_DIE_LOG_DIR")
    if explicit:
        return Path(explicit)
    user_data = proton_user_data_dir(game_dir) if game_dir else None
    if user_data is None:
        raise PipelineError(
            "cannot derive the client log directory: the game directory is not below a Steam "
            "library (steamapps/common/...). Set SEVEN_DAYS_TO_DIE_LOG_DIR explicitly."
        )
    return user_data / "logs"


def user_mods_dir(game_dir: Path | None, env: dict[str, str] | None = None) -> Path:
    """The per-user `Mods/` folder a Proton client loads from.

    The game also scans `<install>/Mods/`, but a mod present in both places is
    loaded from the per-user copy and the install copy is ignored with a
    duplicate warning — and the install is read-only evidence for this
    pipeline anyway. `SEVEN_DAYS_TO_DIE_MODS_DIR` overrides the derivation.
    """
    env = os.environ if env is None else env
    explicit = env.get("SEVEN_DAYS_TO_DIE_MODS_DIR")
    if explicit:
        return Path(explicit)
    user_data = proton_user_data_dir(game_dir) if game_dir else None
    if user_data is None:
        raise PipelineError(
            "cannot derive the client Mods directory: the game directory is not below a Steam "
            "library (steamapps/common/...). Set SEVEN_DAYS_TO_DIE_MODS_DIR explicitly."
        )
    return user_data / "Mods"


# ------------------------------------------------------------------- deploy


def deploy_mod(mod_root: Path, mods_dir: Path, mod_name: str, replace: bool = True) -> list[str]:
    """Copy the deployable part of a modlet into `<mods_dir>/<mod_name>/`.

    Only `DEPLOY_ALLOWLIST` entries and root-level `.dll` files are copied,
    so `assets-src/`, `tools/`, `.shamway.toml`, build state and the Unity
    project can never reach a client by accident. With `replace`, an existing
    deployment is removed first, so a stale bundle cannot survive next to a
    new one. Returns the relative paths copied.
    """
    mod_root = Path(mod_root).resolve()
    if not (mod_root / "ModInfo.xml").is_file():
        raise PipelineError(f"{mod_root} has no ModInfo.xml; nothing deployable here")
    destination = Path(mods_dir) / mod_name
    if destination.exists():
        if not replace:
            raise PipelineError(f"{destination} already exists; pass replace=True to refresh it")
        if destination.resolve() == mod_root:
            raise PipelineError(f"{destination} is the mod root itself; refusing to delete it")
        if destination.is_symlink():
            destination.unlink()
        else:
            shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    candidates = [mod_root / name for name in DEPLOY_ALLOWLIST]
    candidates += sorted(path for path in mod_root.glob("*.dll") if path.is_file())
    for source in candidates:
        if not source.exists():
            continue
        target = destination / source.name
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git*", "*.meta"))
        else:
            shutil.copy2(source, target)
        copied.append(source.name)
    return copied


# ------------------------------------------------------------------ process


def running_client_pids(proc: Path = Path("/proc")) -> list[int]:
    """PIDs of running game clients, found by executable name in `/proc`."""
    pids: list[int] = []
    if not proc.is_dir():
        return pids
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        argv0 = cmdline.split(b"\0", 1)[0].decode("utf-8", "replace")
        if any(argv0.endswith(name) for name in CLIENT_PROCESS_NAMES):
            pids.append(int(entry.name))
    return sorted(pids)


def stop_client(pids: list[int], grace_seconds: float = 5.0) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.2)
    for pid in pids:
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def launch_command(steam_bin: str = "steam", extra_args: tuple[str, ...] = ()) -> list[str]:
    """The Steam launch line for a test client.

    `steam -applaunch` hands the request to the already-running Steam client,
    so the game inherits **Steam's** environment, not this shell's. Anything a
    mod or harness reads from the environment must go into the game's Steam
    launch options (`VAR=value %command%`) instead; confirm with
    `tr '\\0' '\\n' < /proc/<pid>/environ`.
    """
    return [steam_bin, "-applaunch", str(STEAM_APP_ID), *STARTUP_ARGS, *extra_args]


def disable_discord_integration(user_reg: Path) -> bool:
    """Set the persisted `DiscordDisabled` player pref in a Proton `user.reg`.

    The client re-enables its Discord integration per launch from this pref,
    and an unattended test run does not want a rich-presence handshake. The
    edit touches the Proton prefix only, never the game install. Returns
    whether an entry was found and rewritten.
    """
    try:
        text = user_reg.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PipelineError(f"cannot read {user_reg}: {exc}") from exc
    pattern = re.compile(r'^("DiscordDisabled_h\d+"=dword:)[0-9a-fA-F]+$', re.MULTILINE)
    rewritten, count = pattern.subn(r"\g<1>00000001", text)
    if count:
        user_reg.write_text(rewritten, encoding="utf-8")
    return bool(count)


# -------------------------------------------------------------------- audio


def _sink_inputs() -> list[dict[str, object]]:
    if shutil.which("pactl") is None:
        raise PipelineError("pactl is not installed; cannot reach the PipeWire/Pulse sink inputs")
    result = subprocess.run(
        ["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise PipelineError(f"pactl failed: {result.stderr.strip() or result.returncode}")
    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise PipelineError(f"pactl produced unparseable JSON: {exc}") from exc


def client_sink_inputs(inputs: list[dict[str, object]] | None = None) -> list[int]:
    """Sink-input indexes that belong to the game, by application name or binary."""
    inputs = _sink_inputs() if inputs is None else inputs
    indexes: list[int] = []
    for entry in inputs:
        properties = entry.get("properties") or {}
        if not isinstance(properties, dict):
            continue
        haystack = " ".join(
            str(properties.get(key, ""))
            for key in ("application.name", "application.process.binary")
        )
        if "7daystodie" in haystack.lower():
            indexes.append(int(entry["index"]))
    return indexes


def set_client_mute(muted: bool, wait_seconds: int = 60) -> list[int]:
    """Mute or unmute the running client's audio stream at the OS layer.

    The stream only exists once the game has initialised audio, so this polls.
    It never touches game settings: no GamePrefs, no in-game sliders, no
    registry audio prefs. WirePlumber persists per-application stream mute,
    which is why an unmute is needed after a muted run, not only a mute
    before it. Returns the sink-input indexes changed.
    """
    deadline = time.monotonic() + max(1, wait_seconds)
    while True:
        indexes = client_sink_inputs()
        if indexes:
            for index in indexes:
                subprocess.run(
                    ["pactl", "set-sink-input-mute", str(index), "1" if muted else "0"],
                    check=False,
                )
            return indexes
        if time.monotonic() >= deadline:
            return []
        time.sleep(1)


def wireplumber_state_file(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    state_home = env.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(state_home) / "wireplumber/stream-properties"


def saved_mute_state(state_file: Path) -> bool | None:
    """Whether WirePlumber's saved state still mutes the game; None when unknown."""
    try:
        text = state_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("Output/Audio:application.name:") and "7daystodie" in line.lower():
            return '"mute":true' in line.replace(" ", "")
    return None


# ---------------------------------------------------------------------- log


@dataclass(frozen=True)
class Marker:
    key: str
    pattern: str
    meaning: str
    positive: bool
    """True when the line proves something loaded; False when it names a failure."""
    warning: bool = False
    """A negative marker that is reported but does not fail the run: it may be vanilla's."""


def markers_for(mod_name: str | None) -> tuple[Marker, ...]:
    name = re.escape(mod_name) if mod_name else r"[^\s]+"
    return (
        Marker("mod_loaded", rf"Loaded Mod: {name}", "the mod folder was discovered and loaded", True),
        Marker(
            "localization_loaded",
            rf"\[MODS\] Loading localization from mod: {name}",
            "Config/Localization.csv was found; absent means the file is in the wrong place",
            True,
        ),
        Marker(
            "atlas_packed",
            r"UIAtlas ItemIconAtlas: Pack took",
            "the mod's UIAtlases/ItemIconAtlas cells were packed at runtime",
            True,
        ),
        Marker(
            "mod_reference_not_loaded",
            r"\[MODS\] Mod reference for a mod that is not loaded",
            "an @modfolder(Name) URI names a mod that is not loaded — wrong ModInfo Name",
            False,
        ),
        Marker(
            "bundle_load_failed",
            r"Loading AssetBundle .* failed|not compatible with this newer version of the Unity runtime",
            "the bundle did not open: revision mismatch, missing class 142, or a wrong path",
            False,
        ),
        Marker(
            "model_wrong_name",
            r"Model has a wrong name|ERR Model '",
            "a Model/Meshfile stem did not match the loaded object — case, stem, or membership",
            False,
        ),
        Marker(
            "duplicate_mod",
            r"(?i)duplicate mod|mod .* already loaded",
            "the mod exists in both the per-user Mods/ and the install Mods/; the second copy is ignored",
            False,
        ),
        Marker(
            "steam_api_failed",
            r"SteamAPI_Init\(\) failed",
            "Steam was not running when the client started; the menu never builds",
            False,
        ),
        Marker(
            "particle_curve_mode",
            r"curves must all be in the same mode",
            "a particle module mixes MinMaxCurve modes; this logs on every frame the system updates",
            False,
        ),
        Marker(
            "unfocused_start",
            r"Awake IsFocused: False",
            "the window started unfocused; under Proton async loading can starve and hang",
            False,
        ),
        Marker(
            "falling_block",
            r"EntityFallingBlock.*fell off the world",
            "a placed ModelEntity block had no support and the stability pass dropped it",
            False,
        ),
        Marker(
            "exception",
            r"Exception|NullReferenceException|MissingMethodException",
            "an exception — vanilla throws some; read the first and decide whether it is yours",
            False,
            warning=True,
        ),
    )


@dataclass(frozen=True)
class LogReport:
    log: str
    mod_name: str | None
    found: dict[str, str] = field(default_factory=dict)
    """marker key -> first matching line, for markers that matched."""
    missing_positive: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()
    """Lines matching a negative marker, prefixed by the marker key."""
    warnings: tuple[str, ...] = ()
    """Negative lines that may be vanilla's; reported, never failed."""

    @property
    def ok(self) -> bool:
        return not self.problems and not self.missing_positive

    def as_dict(self) -> dict[str, object]:
        return {
            "log": self.log,
            "mod_name": self.mod_name,
            "found": dict(self.found),
            "missing_positive": list(self.missing_positive),
            "problems": list(self.problems),
            "warnings": list(self.warnings),
            "ok": self.ok,
        }


def scan_log_text(text: str, mod_name: str | None, log_path: str = "-") -> LogReport:
    """Classify a client log by the markers this pipeline knows about.

    `atlas_packed` and `localization_loaded` are only required when the mod
    ships an atlas or a localization file; callers pass `mod_name=None` to
    treat every positive marker as informational.
    """
    found: dict[str, str] = {}
    problems: list[str] = []
    warnings: list[str] = []
    markers = markers_for(mod_name)
    compiled = [(marker, re.compile(marker.pattern)) for marker in markers]
    for line in text.splitlines():
        for marker, pattern in compiled:
            if pattern.search(line):
                found.setdefault(marker.key, line.strip())
                if marker.positive:
                    continue
                (warnings if marker.warning else problems).append(f"{marker.key}: {line.strip()}")
    missing = tuple(
        marker.key for marker in markers if marker.positive and marker.key not in found
    ) if mod_name else ()
    return LogReport(
        log=log_path,
        mod_name=mod_name,
        found=found,
        missing_positive=missing,
        problems=tuple(problems[:50]),
        warnings=tuple(warnings[:20]),
    )


def scan_log(path: Path, mod_name: str | None) -> LogReport:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PipelineError(f"cannot read client log {path}: {exc}") from exc
    return scan_log_text(text, mod_name, str(path))


def latest_client_log(log_dir: Path, written_after: float | None = None) -> Path:
    """The newest client log, optionally required to post-date a launch.

    The client rewrites its log on every start, so a log older than the launch
    means this launch never got as far as logging — and a report quoting line
    numbers from a live log is only meaningful for the run that produced it.
    """
    if not log_dir.is_dir():
        raise PipelineError(f"client log directory does not exist: {log_dir}")
    logs = sorted(log_dir.glob(LOG_GLOB), key=lambda path: path.stat().st_mtime)
    if not logs:
        raise PipelineError(f"no {LOG_GLOB} in {log_dir}")
    newest = logs[-1]
    if written_after is not None and newest.stat().st_mtime < written_after:
        raise PipelineError(
            f"{newest} predates this launch; the client did not start or did not log. "
            "Is Steam running? Grep the previous log for SteamAPI_Init."
        )
    return newest


# --------------------------------------------------------------- acceptance


@dataclass(frozen=True)
class AcceptanceRun:
    log: LogReport
    launched: list[str]
    run_seconds: int | None
    muted: bool
    unmuted_again: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "log": self.log.as_dict(),
            "launched": list(self.launched),
            "run_seconds": self.run_seconds,
            "muted": self.muted,
            "unmuted_again": self.unmuted_again,
            "ok": self.log.ok,
        }


def fresh_client_run(
    game_dir: Path | None,
    mod_name: str | None,
    run_seconds: int | None = None,
    mute: bool = False,
    steam_bin: str = "steam",
    extra_args: tuple[str, ...] = (),
    log_dir: Path | None = None,
) -> AcceptanceRun:
    """Launch a genuinely fresh client and classify the log it writes.

    Refuses to start while a client is running: a bundle stays cached for the
    life of the process, so a reused client cannot prove a rebuilt bundle. A
    `mute` run is muted at the OS layer and unmuted again before returning;
    a *listening* run must not be muted, and says so in its report.
    """
    if running_client_pids():
        raise PipelineError(
            "a 7 Days to Die client is already running; close it first. A reused client "
            "keeps the old bundle cached and proves nothing about a rebuild."
        )
    if shutil.which(steam_bin) is None:
        raise PipelineError(f"{steam_bin!r} is not on PATH; set --steam-bin to the Steam launcher")
    logs = log_dir or client_log_dir(game_dir)
    started_at = time.time()
    command = launch_command(steam_bin, extra_args)
    subprocess.run(command, check=False)
    muted_indexes: list[int] = []
    if mute:
        muted_indexes = set_client_mute(True)
    unmuted = False
    if run_seconds:
        time.sleep(run_seconds)
        if mute and muted_indexes:
            set_client_mute(False, wait_seconds=5)
            unmuted = True
        stop_client(running_client_pids())
    newest = latest_client_log(logs, written_after=started_at)
    return AcceptanceRun(
        log=scan_log(newest, mod_name),
        launched=command,
        run_seconds=run_seconds,
        muted=bool(muted_indexes),
        unmuted_again=unmuted,
    )


# ---------------------------------------------------------------------- CLI


def _game_dir_from_env() -> Path | None:
    value = os.environ.get("SEVEN_DAYS_TO_DIE_DIR")
    return Path(value) if value else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="shamway client",
        description="fresh-client acceptance: deploy, launch, mute, scan the client log, and capture what a person saw",
    )
    parser.add_argument("--game-dir", type=Path, default=None, help="defaults to SEVEN_DAYS_TO_DIE_DIR")
    sub = parser.add_subparsers(dest="command", required=True)

    where = sub.add_parser("where", help="print the per-user Mods/ and logs/ paths the client uses")
    where.add_argument("--json", action="store_true")

    deploy = sub.add_parser("deploy", help="copy the deployable modlet into the client's Mods/ folder")
    deploy.add_argument("mod_root", type=Path)
    deploy.add_argument("--name", default=None, help="folder name; defaults to the ModInfo.xml Name")
    deploy.add_argument("--mods-dir", type=Path, default=None)
    deploy.add_argument("--keep-existing", action="store_true", help="fail instead of replacing")

    launch = sub.add_parser("launch", help="start a fresh client through Steam (refuses if one runs)")
    launch.add_argument("--mute", action="store_true", help="mute at the OS audio layer; never for a listening run")
    launch.add_argument("--run-seconds", type=int, default=None, help="stop the client after this long")
    launch.add_argument("--mod-name", default=None, help="require 'Loaded Mod: NAME' in the log")
    launch.add_argument("--steam-bin", default="steam")
    launch.add_argument("--log-dir", type=Path, default=None)
    launch.add_argument("--json", action="store_true")
    launch.add_argument("extra", nargs="*", help="additional client arguments")

    log = sub.add_parser("log", help="find the newest client log and classify it")
    log.add_argument("--path", type=Path, default=None, help="a specific log instead of the newest")
    log.add_argument("--mod-name", default=None)
    log.add_argument("--log-dir", type=Path, default=None)
    log.add_argument("--json", action="store_true")

    mute = sub.add_parser("mute", help="mute the running client's audio stream")
    mute.add_argument("--wait", type=int, default=60)
    unmute = sub.add_parser("unmute", help="unmute it, and report saved WirePlumber state")
    unmute.add_argument("--wait", type=int, default=5)

    shot = sub.add_parser(
        "capture",
        help="record one screenshot and its observable, for the human visual sign-off",
    )
    shot.add_argument("label", nargs="?", help="how this frame is cited later, e.g. held-nuke")
    shot.add_argument(
        "--observable", default="", help="what the reviewer is being asked to check"
    )
    shot.add_argument(
        "--wait", type=float, default=0.0, metavar="SECONDS",
        help="setup time before the shutter, to frame the shot in the client",
    )
    shot.add_argument("--out", type=Path, default=None, help="evidence directory (default .local/acceptance)")
    shot.add_argument("--file", type=Path, default=None, help="record an image already taken instead of capturing")
    shot.add_argument("--list", action="store_true", help="print the manifest recorded so far")
    shot.add_argument(
        "--allow-no-client", action="store_true",
        help="capture even though no client is running; a frame of a menu proves nothing about an asset",
    )
    shot.add_argument("--json", action="store_true")

    discord = sub.add_parser("disable-discord", help="set DiscordDisabled in the Proton user.reg")
    discord.add_argument("--user-reg", type=Path, default=None)

    args = parser.parse_args(argv)
    game_dir = args.game_dir or _game_dir_from_env()
    try:
        return _dispatch(args, game_dir)
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace, game_dir: Path | None) -> int:
    if args.command == "where":
        info = {
            "game_dir": str(game_dir) if game_dir else None,
            "compatdata": _maybe(compatdata_dir, game_dir),
            "user_data": _maybe(proton_user_data_dir, game_dir),
            "mods_dir": _maybe(lambda g: user_mods_dir(g), game_dir),
            "log_dir": _maybe(lambda g: client_log_dir(g), game_dir),
            "launch": launch_command(),
        }
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            for key, value in info.items():
                print(f"{key:12} {value if not isinstance(value, list) else ' '.join(value)}")
        return 0
    if args.command == "deploy":
        from .config import read_mod_name  # noqa: PLC0415

        name = args.name or read_mod_name(args.mod_root / "ModInfo.xml")
        mods_dir = args.mods_dir or user_mods_dir(game_dir)
        copied = deploy_mod(args.mod_root, mods_dir, name, replace=not args.keep_existing)
        print(f"deployed {name} to {mods_dir / name}: {', '.join(copied)}")
        return 0
    if args.command == "launch":
        run = fresh_client_run(
            game_dir,
            args.mod_name,
            run_seconds=args.run_seconds,
            mute=args.mute,
            steam_bin=args.steam_bin,
            extra_args=tuple(args.extra),
            log_dir=args.log_dir,
        )
        if args.json:
            print(json.dumps(run.as_dict(), indent=2))
        else:
            _print_log_report(run.log)
            print(f"AUDIO {'muted at the OS layer (not a listening run)' if run.muted else 'unmuted'}")
        return 0 if run.log.ok else 1
    if args.command == "log":
        path = args.path or latest_client_log(args.log_dir or client_log_dir(game_dir))
        report = scan_log(path, args.mod_name)
        if args.json:
            print(json.dumps(report.as_dict(), indent=2))
        else:
            _print_log_report(report)
        return 0 if report.ok else 1
    if args.command == "mute":
        changed = set_client_mute(True, args.wait)
        print(f"muted sink inputs: {changed or 'none found'}")
        return 0 if changed else 1
    if args.command == "unmute":
        changed = set_client_mute(False, args.wait)
        print(f"unmuted sink inputs: {changed or 'none found (the game must be running)'}")
        state = wireplumber_state_file()
        saved = saved_mute_state(state)
        if saved:
            print(
                f"WirePlumber still saves the game as muted in {state}; start the game and run "
                "unmute again, or edit that file and `systemctl --user restart wireplumber`",
                file=sys.stderr,
            )
            return 1
        return 0
    if args.command == "capture":
        return _capture(args)
    if args.command == "disable-discord":
        user_reg = args.user_reg
        if user_reg is None:
            prefix = compatdata_dir(game_dir) if game_dir else None
            if prefix is None:
                raise PipelineError("pass --user-reg or a Steam-library game dir")
            user_reg = prefix / "pfx/user.reg"
        if disable_discord_integration(user_reg):
            print(f"DiscordDisabled set in {user_reg}")
            return 0
        print(f"no DiscordDisabled entry in {user_reg}; launch the game once first", file=sys.stderr)
        return 1
    raise PipelineError(f"unknown command {args.command}")


def _capture(args: argparse.Namespace) -> int:
    """`client capture`: record a frame and what it was meant to show.

    The client-running check is not bureaucracy. A screenshot of a main menu,
    or of the terminal the operator alt-tabbed to, files cleanly into the
    manifest and looks exactly like evidence to the next reader.
    """
    from .capture import DEFAULT_ROOT, capture, read_manifest, record_existing  # noqa: PLC0415

    root = args.out or DEFAULT_ROOT

    if args.list:
        entries = read_manifest(root)
        if args.json:
            print(json.dumps(entries, indent=2, sort_keys=True))
            return 0
        if not entries:
            print(f"no captures recorded under {root}")
            return 0
        for entry in entries:
            print(f"{entry.get('label', '?'):24} {entry.get('file', '?')}")
            print(f"{'':24} {entry.get('observable') or '(no observable recorded)'}")
        print()
        print("A recorded frame is not a verdict. Only a person signs these off.")
        return 0

    if not args.label:
        raise PipelineError("capture needs a LABEL, or --list to print the manifest")

    if args.file is not None:
        entry = record_existing(args.file, args.label, args.observable, root)
    else:
        if not args.allow_no_client and not running_client_pids():
            raise PipelineError(
                "no 7DaysToDie.exe is running, so there is nothing to look at. Start "
                "one with 'shamway client launch', or pass --allow-no-client if you "
                "really mean to capture whatever is on screen."
            )
        entry = capture(args.label, args.observable, root, args.wait)

    if args.json:
        print(json.dumps(entry.as_dict(), indent=2, sort_keys=True))
        return 0
    print(f"captured {Path(root) / entry.file} ({entry.bytes} bytes, via {entry.backend})")
    if entry.observable:
        print(f"look for: {entry.observable}")
    for note in entry.notes:
        print(f"note: {note}")
    print("Recorded, not accepted. The verdict is yours to write into the manifest.")
    return 0


def _maybe(fn, game_dir: Path | None) -> str | None:
    if game_dir is None:
        return None
    try:
        value = fn(game_dir)
    except PipelineError:
        return None
    return str(value) if value is not None else None


def _print_log_report(report: LogReport) -> None:
    print("CLIENT LOG")
    print(f"  {report.log}")
    print("FOUND")
    for key, line in report.found.items():
        print(f"  {key:26} {line}")
    if report.missing_positive:
        print("MISSING")
        for key in report.missing_positive:
            meaning = next(m.meaning for m in markers_for(report.mod_name) if m.key == key)
            print(f"  {key:26} {meaning}")
    if report.problems:
        print("PROBLEMS")
        for line in report.problems:
            print(f"  {line}")
    if report.warnings:
        print("WARNINGS (not failed: may be vanilla's)")
        for line in report.warnings:
            print(f"  {line}")
    print("RESULT")
    print(f"  {'PASS: log is clean and the mod loaded' if report.ok else 'FAIL: see above'}")
    print("  This proves loadability. Whether the asset looks or sounds right is a human call.")


if __name__ == "__main__":
    raise SystemExit(main())
