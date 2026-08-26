#!/usr/bin/env bash
# Collect the in-game frames a staged acceptance case photographs.
#
# The acceptance suite answers "did the game read it". It cannot answer "does it
# look right", and every case in it passes on a prop that renders magenta or
# nothing at all. A staged case closes that: it puts the scene on screen, holds
# it, and - since hordeforge/7dtd-playtest#48 - photographs *its own
# framebuffer* through Unity, supersized, writing the path to the client log.
#
# This waits for those lines and copies the files somewhere the mod keeps them.
#
# It does not take the picture. It used to, with a desktop screen grab, and that
# was unsound: a desktop capture photographs whatever is in front of it, so on a
# host running more than one client it repeatedly captured *another session's*
# game and produced frames that looked like evidence. The game takes its own
# picture now, and this only fetches it.
#
# Run it beside `playtest-acceptance.sh`, while this host's playtest lock is
# yours - `playtest-acceptance.sh` takes that lock:
#
#     scripts/playtest-capture.sh --case look_myProp --label vulkan &
#     scripts/playtest-acceptance.sh --mod-root .
#
# It exits when the suite writes DONE, or at --timeout.
set -euo pipefail

# Resolves the sibling helpers in both layouts: from a checkout this is the
# repository root, and from the installed package (`shamway script
# playtest-capture`) it is the package directory, whose scripts/ holds the
# same files.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

LABEL="staged"
TIMEOUT=900
MARKER="scene staged"
OUT_DIR=".local/acceptance"
# Which staged case this loop is waiting for. Required, and the reason is a
# scar: the client log lives at a fixed path shared by every session on this
# host, and a screenshot photographs the whole screen. Without a case filter
# this loop fired on *another* session's staged marker and photographed *their*
# client - five times - producing frames that looked like evidence and were
# somebody else's run.
CASE=""

while (($#)); do
    case "$1" in
    --label) LABEL="${2:-}"; shift 2 ;;
    --case) CASE="${2:-}"; shift 2 ;;
    --timeout) TIMEOUT="${2:-}"; shift 2 ;;
    --marker) MARKER="${2:-}"; shift 2 ;;
    --out-dir) OUT_DIR="${2:-}"; shift 2 ;;
    -h | --help)
        sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    *)
        echo "playtest-capture.sh: unknown argument '$1'" >&2
        exit 2
        ;;
    esac
done

if [[ -z "$CASE" ]]; then
    echo "playtest-capture.sh: --case is required (the staged case id to wait for, e.g." >&2
    echo "  look_myProp). Without it this loop photographs whatever any session stages." >&2
    exit 2
fi

# The field selection is a sibling script, so this file stays one language.
where="$(shamway client where --json)"
logs="$(printf '%s' "$where" | python3 "$ROOT/scripts/json_field.py" log_dir)"
shots_dir="$(printf '%s' "$where" | python3 "$ROOT/scripts/json_field.py" user_data)/playtest-shots"
started="$(date +%s)"
seen=""
# The orchestrator writes this when its poll loop ends (done / timeout /
# client_exit) - the deterministic end of the run. Its directory mirrors the
# orchestrator's --logdir default: $LOGDIR or ~/.cache/7dtd-playtest.
run_ended="${LOGDIR:-$HOME/.cache/7dtd-playtest}/run-ended"

# The newest log, but only if this run wrote it. A client log lives at a fixed
# path and a finished run leaves its own behind, so without this the first poll
# photographs whatever the *previous* run staged - a mistake this project has
# already made once, reading numbers off a stale log and believing them.
newest_log() {
    local candidate
    candidate="$(find "$logs" -maxdepth 1 -name 'output_log_client_*.txt' -printf '%T@ %p\n' 2>/dev/null |
        sort -rn | head -n 1 | cut -d' ' -f2-)" || return 1
    [[ -n "$candidate" ]] || return 1
    [[ "$(stat -c %Y "$candidate")" -ge "$started" ]] || return 1
    printf '%s\n' "$candidate"
}

while true; do
    now="$(date +%s)"
    if ((now - started > TIMEOUT)); then
        echo "playtest-capture.sh: no staged frame within ${TIMEOUT}s" >&2
        exit 1
    fi
    log="$(newest_log)" || true
    if [[ -n "${log:-}" && -f "$log" ]]; then
        # One capture per staged case, keyed on the case id in the marker line.
        while read -r case_id; do
            [[ -z "$case_id" ]] && continue
            [[ "$case_id" == "$CASE" ]] || continue
            case " $seen " in *" $case_id "*) continue ;; esac
            seen="$seen $case_id"
            # The game wrote it. It logs a *Windows* path under Proton
            # ("C:\users\steamuser\..."), which does not exist on this side of
            # the prefix, so the directory is derived from the client's own
            # user-data path and the file named by the case.
            if ! grep -q "\[7dtd-playtest\] shot ${case_id} " "$log"; then
                echo "playtest-capture.sh: $case_id staged but logged no shot" >&2
                continue
            fi
            shot="$shots_dir/${case_id}.png"
            # Unity writes at end of frame, so the path is logged before the
            # file exists. Wait briefly rather than reporting a missing frame.
            for _ in $(seq 1 20); do
                [[ -s "$shot" ]] && break
                sleep 0.5
            done
            if [[ ! -s "$shot" ]]; then
                echo "playtest-capture.sh: $shot never appeared" >&2
                continue
            fi
            mkdir -p "$OUT_DIR"
            cp -f "$shot" "$OUT_DIR/${LABEL}-${case_id}.png"
            echo "playtest-capture.sh: kept $OUT_DIR/${LABEL}-${case_id}.png"
        done < <(grep -oE "${MARKER}[^ ]* [a-zA-Z0-9_/.-]+" "$log" 2>/dev/null | awk '{print $2}' || true)
        if grep -q "\[7dtd-playtest\] DONE" "$log" 2>/dev/null; then
            exit 0
        fi
        # The run is decided before DONE when the client is gone: a crash
        # mid-draw leaves the staged marker in the log and no shot, and
        # waiting out --timeout turns a five-second failure into a
        # fifteen-minute stall. Only declare it when this run actually staged
        # its case, so a client that never started is not misread as a crash.
        if [[ -n "$seen" ]] && ! pgrep -f "7DaysToDie.exe" >/dev/null 2>&1; then
            echo "playtest-capture.sh: client exited after staging ${seen}; no shot, no DONE" >&2
            exit 1
        fi
        # The orchestrator's run-ended marker is the deterministic end of the
        # run (done / timeout / client_exit). React only to a marker written
        # after this loop started, so a previous run's marker cannot end us.
        if [[ -f "$run_ended" && "$(stat -c %Y "$run_ended" 2>/dev/null)" -ge "$started" ]]; then
            reason="$(cat "$run_ended" 2>/dev/null)"
            if [[ -n "$seen" && "$reason" != "done" ]]; then
                echo "playtest-capture.sh: run ended ($reason) after staging ${seen}; no shot" >&2
                exit 1
            fi
            exit 0
        fi
    fi
    sleep 1
done
