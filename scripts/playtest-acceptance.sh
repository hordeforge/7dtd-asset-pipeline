#!/usr/bin/env bash
# Run this mod's bundle-acceptance suite in a live 7 Days to Die client.
#
# The offline gates in this repository end at "the bytes are right". This is
# the step that ends at "the game read them": it generates the scenario
# provider from the mod's own manifest, deploys the modlet and the provider,
# and hands the run to hordeforge/7dtd-playtest, which owns the orchestrator,
# the dedicated server and the exclusivity lock. Nothing here launches a client
# itself; a second launcher would be a second thing to keep correct.
#
# What the orchestrator needs that is easy to miss, and what a raw
# playtest_run.py call gets wrong:
#
#   * --client-log must name the log the *client launcher* writes, which is
#     hordeforge/7dtd-fastconnect's output_log_client_7dtd_connect.txt under
#     the Proton prefix, not the client's own dated log. Point it at the wrong
#     file and the orchestrator waits out its timeout on a client that started
#     perfectly well.
#   * GAME and COMPAT are read by that launcher, not by the orchestrator, so
#     they have to be exported rather than passed.
#   * 7dtd-playtest and 7dtd-fastconnect must both be deployed into the
#     client's Mods folder: the first runs the cases, the second starts and
#     connects the client.
#
# Disclosure, because this repository's own rule is that it never writes into a
# game install: with CLIENT_PLATFORM=local (the default, and the only mode that
# joins a local dedicated server without Steam auth) fastconnect's launcher
# swaps `platform.cfg` inside the install and restores it when the client
# exits. That write belongs to fastconnect and is announced on every run;
# --client-platform steam avoids it entirely.
set -euo pipefail

die() {
	echo "ERROR: $*" >&2
	exit 1
}

MOD_ROOT="${PWD}"
PLAYTEST_ROOT="${PLAYTEST_ROOT:-$HOME/code/hordeforge/7dtd-playtest}"
CONNECT_ROOT="${CONNECT_ROOT:-$HOME/code/hordeforge/7dtd-fastconnect}"
SUITE=""
TIMEOUT="${PLAYTEST_TIMEOUT:-900}"
PORT="${PLAYTEST_PORT:-26900}"
ADMIN_PORT="${PLAYTEST_ADMIN_PORT:-8081}"
WORLD_NAME="${PLAYTEST_WORLD_NAME:-Navezgane}"
GAME_NAME="${PLAYTEST_GAME_NAME:-PlaytestNav}"
CLIENT_PLATFORM="${PLAYTEST_CLIENT_PLATFORM:-local}"
# Fresh by default. A reused world is a reused set of registered blocks, item
# ids and chunk state, and the whole point of this run is that nothing carried
# over from the last one - the same reason `client launch` refuses a running
# client. Opting out is a deliberate act with a flag, not the thing you get by
# forgetting one.
FRESH=1
LISTEN=0
SHAMWAY="${SHAMWAY:-shamway}"

usage() {
	cat <<-'EOF'
		usage: playtest-acceptance.sh [OPTIONS]

		Run the mod in the current directory through its bundle-acceptance
		suite in a live client. Generates the provider, deploys everything,
		and hands off to hordeforge/7dtd-playtest.

		OPTIONS
		  --mod-root DIR           the modlet to accept        (default: cwd)
		  --suite ID               suite to run                (default: the generated one)
		  --playtest-root DIR      hordeforge/7dtd-playtest checkout
		  --connect-root DIR       hordeforge/7dtd-fastconnect checkout
		  --world-name NAME        stock GameWorld             (default: Navezgane)
		  --game-name NAME         save name under userdata    (default: PlaytestNav)
		  --port N                 server port                 (default: 26900)
		  --admin-port N           telnet port                 (default: 8081)
		  --timeout SECONDS        orchestrator budget         (default: 900)
		  --client-platform MODE   local or steam              (default: local)
		  --fresh-save             regenerate the save first (the default)
		  --reuse-save             keep the existing save; faster, and weaker
		                           evidence - say so in any report that used it
		  --listen                 do not mute the client, for an audio sign-off
		  -h, --help               this text

		ENVIRONMENT
		  SEVEN_DAYS_TO_DIE_DIR         the client install (required)
		  SEVEN_DAYS_TO_DIE_SERVER_DIR  the dedicated server install (required)
		  PLAYTEST_SESSION_ID           lock holder id (generated when unset)
		  SHAMWAY                       the shamway entry point (default: shamway)

		EXAMPLES
		  playtest-acceptance.sh                        # accept the mod in this directory
		  playtest-acceptance.sh --listen               # same, audible, for a sound check
		  playtest-acceptance.sh --reuse-save            # keep the world, for a quick loop
		  playtest-acceptance.sh --client-platform steam  # never touch platform.cfg
	EOF
}

while (($#)); do
	case "$1" in
		--mod-root) MOD_ROOT="${2:-}"; shift 2 ;;
		--suite) SUITE="${2:-}"; shift 2 ;;
		--playtest-root) PLAYTEST_ROOT="${2:-}"; shift 2 ;;
		--connect-root) CONNECT_ROOT="${2:-}"; shift 2 ;;
		--world-name) WORLD_NAME="${2:-}"; shift 2 ;;
		--game-name) GAME_NAME="${2:-}"; shift 2 ;;
		--port) PORT="${2:-}"; shift 2 ;;
		--admin-port) ADMIN_PORT="${2:-}"; shift 2 ;;
		--timeout) TIMEOUT="${2:-}"; shift 2 ;;
		--client-platform) CLIENT_PLATFORM="${2:-}"; shift 2 ;;
		--fresh-save) FRESH=1; shift ;;
		--reuse-save) FRESH=0; shift ;;
		--listen) LISTEN=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) die "unknown option: $1 (try --help)" ;;
	esac
done

MOD_ROOT="$(cd "$MOD_ROOT" && pwd)"
[[ -f "$MOD_ROOT/ModInfo.xml" ]] || die "$MOD_ROOT has no ModInfo.xml; is that a modlet?"
[[ -n "${SEVEN_DAYS_TO_DIE_DIR:-}" ]] || die "SEVEN_DAYS_TO_DIE_DIR is not set"
[[ -n "${SEVEN_DAYS_TO_DIE_SERVER_DIR:-}" ]] || die "SEVEN_DAYS_TO_DIE_SERVER_DIR is not set; the orchestrator starts a dedicated server"
[[ -d "$PLAYTEST_ROOT" ]] || die "no hordeforge/7dtd-playtest checkout at $PLAYTEST_ROOT (--playtest-root)"
[[ -d "$CONNECT_ROOT" ]] || die "no hordeforge/7dtd-fastconnect checkout at $CONNECT_ROOT (--connect-root)"
[[ -f "$PLAYTEST_ROOT/scripts/playtest_run.py" ]] || die "no scripts/playtest_run.py under $PLAYTEST_ROOT"
command -v uv >/dev/null 2>&1 || die "uv is not on PATH; the orchestrator runs under it"

case "$CLIENT_PLATFORM" in
	local|steam) ;;
	*) die "--client-platform must be local or steam, not $CLIENT_PLATFORM" ;;
esac

GAME="$SEVEN_DAYS_TO_DIE_DIR"
[[ "$GAME" == */steamapps/common/* ]] || die "cannot derive the Proton prefix from $GAME"
COMPAT="${GAME%/common/*}/compatdata/251570"
MODS_DIR="${MODS_DIR:-$COMPAT/pfx/drive_c/users/steamuser/AppData/Roaming/7DaysToDie/Mods}"
# The launcher's own LOGFILE line is the source of truth for the log name, and
# the orchestrator has to watch that exact file.
CONNECT_LOG_STEM="$(sed -n 's/.*\(output_log_client_[A-Za-z0-9_]*\.txt\).*/\1/p' \
	"$CONNECT_ROOT/scripts/launch_client.sh" 2>/dev/null | head -1)"
CONNECT_LOG_STEM="${CONNECT_LOG_STEM:-output_log_client_7dtd_connect.txt}"
CLIENT_LOG="${PLAYTEST_CLIENT_LOG:-$COMPAT/pfx/drive_c/users/steamuser/AppData/Roaming/7DaysToDie/logs/$CONNECT_LOG_STEM}"
SESSION="${PLAYTEST_SESSION_ID:-shamway-$(date -u +%Y%m%d-%H%M%S)-$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')}"

if ((LISTEN)); then
	CLIENT_MUTE=0
	AUDIO="on (--listen: a sound sign-off run)"
else
	CLIENT_MUTE="${CLIENT_MUTE:-1}"
	AUDIO="muted (--listen to hear it)"
fi

echo "PLAYTEST ACCEPTANCE"
echo "  mod            $MOD_ROOT"
echo "  game           $GAME"
echo "  server         $SEVEN_DAYS_TO_DIE_SERVER_DIR"
echo "  mods           $MODS_DIR"
echo "  playtest       $PLAYTEST_ROOT"
echo "  connect        $CONNECT_ROOT"
echo "  client log     $CLIENT_LOG"
echo "  client mode    $CLIENT_PLATFORM"
echo "  client audio   $AUDIO"
if ((FRESH)); then
	echo "  save           regenerated for this run"
else
	echo "  save           REUSED (--reuse-save): weaker evidence, say so in the report"
fi
echo "  session        $SESSION"
if [[ "$CLIENT_PLATFORM" == "local" ]]; then
	echo "  note           fastconnect swaps $GAME/platform.cfg for the run and restores it on exit"
fi
echo

echo "PROVIDER (generated from the mod's manifest)"
HARNESS_DLL="$PLAYTEST_ROOT/dist/7dtd-playtest/7dtd-playtest.dll"
if [[ ! -f "$HARNESS_DLL" ]]; then
	echo "  building the harness first ($PLAYTEST_ROOT)"
	make -C "$PLAYTEST_ROOT" build GAME="$GAME"
fi
PROVIDER_JSON="$(cd "$MOD_ROOT" && "$SHAMWAY" acceptance-provider --harness-dll "$HARNESS_DLL" --install --json)"
GENERATED_SUITE="$(printf '%s' "$PROVIDER_JSON" | sed -n 's/.*"suite": *"\([^"]*\)".*/\1/p' | head -1)"
[[ -n "$GENERATED_SUITE" ]] || die "shamway acceptance-provider reported no suite id"
SUITE="${SUITE:-$GENERATED_SUITE}"
echo "  suite          $SUITE"
echo

echo "DEPLOY (client Proton Mods)"
mkdir -p "$MODS_DIR"
(cd "$MOD_ROOT" && "$SHAMWAY" client deploy .)
# `client deploy` holds the shared lock across its write. These two do not go
# through it — they are plain directory copies — so without the same guard they
# rewrite the Mods folder of whatever run currently holds the client. That has
# happened: a session cleared 7dtd-playtest and 7dtd-fastconnect out of this
# folder while another session's client was live, and the only reason it was
# noticed is that a human saw it. `client hold` puts the copies behind the same
# flock every other writer serializes through.
for pair in "$PLAYTEST_ROOT/dist/7dtd-playtest:7dtd-playtest" "$CONNECT_ROOT/dist/7dtd-fastconnect:7dtd-fastconnect"; do
	src="${pair%%:*}"
	name="${pair##*:}"
	[[ -d "$src" ]] || die "missing deploy source: $src (build it in its own checkout)"
	# shellcheck disable=SC2016  # $0/$1/$2 are the inner shell's positionals, by design
	"$SHAMWAY" client hold --action "replace $name in the shared Mods folder" -- \
		bash -c 'rm -rf "${2:?}/$1" && cp -a "$0" "$2/$1"' "$src" "$name" "$MODS_DIR"
	echo "  deployed $name"
done
echo

FRESH_ARGS=()
((FRESH)) && FRESH_ARGS=(--fresh-save)

echo "ORCH (7dtd-playtest playtest_run.py suite=$SUITE)"
export GAME COMPAT CLIENT_PLATFORM CLIENT_MUTE
export PLAYTEST_SESSION_ID="$SESSION"
set +e
uv run --project "$PLAYTEST_ROOT" python "$PLAYTEST_ROOT/scripts/playtest_run.py" \
	--server stock \
	--suite "$SUITE" \
	--world-name "$WORLD_NAME" \
	--game-name "$GAME_NAME" \
	--game-srv "$SEVEN_DAYS_TO_DIE_SERVER_DIR" \
	--port "$PORT" \
	--admin-port "$ADMIN_PORT" \
	--client-log "$CLIENT_LOG" \
	--session "$SESSION" \
	--timeout "$TIMEOUT" \
	"${FRESH_ARGS[@]}"
STATUS=$?
set -e

echo
echo "RESULT (from $CLIENT_LOG)"
if [[ -f "$CLIENT_LOG" ]]; then
	grep -E "\[7dtd-playtest\] +(PASS|FAIL|SKIP|SUMMARY)" "$CLIENT_LOG" | tail -20 || true
else
	echo "  no client log at $CLIENT_LOG: the client never wrote one"
fi
echo
echo "Offline gates say the bytes are right; this says the game read them."
echo "Whether the asset looks and sounds right is still a person's call:"
echo "  shamway client capture <label> --observable '...'"
exit "$STATUS"
