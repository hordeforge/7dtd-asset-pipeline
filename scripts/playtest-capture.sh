#!/usr/bin/env bash
# Photograph the frame a `CaseDef.Staged` case holds, without a person watching.
#
# The acceptance suite answers "did the game read it". It cannot answer "does it
# look right", and every case in it passes on a prop that renders magenta or
# nothing at all. A staged case exists to close that: it puts the scene on
# screen, holds it, and announces itself in the client log. This waits for that
# announcement and takes the picture.
#
# Run it beside `playtest-acceptance.sh`, not instead of it, and only while
# this host's playtest lock is yours - `playtest-acceptance.sh` takes that lock,
# and it is what stops another session's client being the one on screen:
#
#     python3 ../7dtd-playtest/scripts/playtest_lock.py wait --timeout 600
#     scripts/playtest-capture.sh --case look_myProp --label vulkan &
#     scripts/playtest-acceptance.sh --mod-root .
#
# It exits when the suite writes DONE, or at --timeout.
set -euo pipefail

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

logs="$(shamway client where --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["log_dir"])')"
started="$(date +%s)"
seen=""

# The newest log, but only if this run wrote it. A client log lives at a fixed
# path and a finished run leaves its own behind, so without this the first poll
# photographs whatever the *previous* run staged - a mistake this project has
# already made once, reading numbers off a stale log and believing them.
newest_log() {
    local candidate
    candidate="$(ls -t "$logs"/output_log_client_*.txt 2>/dev/null | head -1)" || return 1
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
            shamway client capture "${LABEL}-${case_id}" \
                --out "$OUT_DIR" \
                --observable "staged frame for ${case_id}: is the prop drawn, and drawn correctly" ||
                echo "playtest-capture.sh: capture failed for $case_id" >&2
        done < <(grep -oE "${MARKER}[^ ]* [a-zA-Z0-9_/.-]+" "$log" 2>/dev/null | awk '{print $2}' || true)
        if grep -q "\[7dtd-playtest\] DONE" "$log" 2>/dev/null; then
            exit 0
        fi
    fi
    sleep 1
done
