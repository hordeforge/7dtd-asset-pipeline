#!/usr/bin/env bash
# Prove, in a live 7 Days to Die client, that this pipeline's editorless writer
# produces a bundle the game can actually read.
#
# This is the regression behind the claim `bundle_source = "synthesized"` makes.
# `make check test` proves the bytes parse; CI's scaffold job proves the object
# graph is complete; neither runs the game. The failure this catches is the one
# both of those miss and only the engine can report: a bundle that is
# structurally perfect and that `DataLoader.LoadAsset<T>` answers null for.
#
# It happened. On 2026-08-24 the first run of this suite failed because the
# provider asked for `LoadAsset<Mesh>` at a stem the prefab had taken over, and
# nothing offline could have said so. That is why this exists as a script
# instead of as a procedure someone remembers.
#
# The modlet is `examples/SelfTestMod/`, committed in this repository. It is a
# fixture, not scratch: a mod that exists only inside one script run cannot be
# iterated on, inspected after a failure, diffed against a previous build, or
# used to diagnose anything - which is exactly what a failing run needs. Its
# sources, its XML and its icon are reviewable in git, so a change to the prop
# is a reviewable change rather than a line of shell nobody reads.
#
# It is built **in place**, and its outputs - Resources/<bundle>.unity3d and the
# tracked manifest - are committed with it, exactly as a consuming mod commits
# its own. That is the point: after a failure the bundle is still there to
# inspect, a change to the prop shows up as a diff of real artifacts, and the
# fixture doubles as this repository's worked example of a synthesized modlet.
set -euo pipefail

die() {
	echo "ERROR: $*" >&2
	exit 1
}

STEM="shamwaySelfTestProp"
MOD_NAME="ShamwaySelfTest"
FIXTURE=""
EXTRA=()

usage() {
	cat <<-'EOF'
		usage: playtest-synthesized.sh [OPTIONS] [-- PLAYTEST_ARGS...]

		Build a throwaway modlet whose bundle is written with no Unity editor,
		run it through hordeforge/7dtd-playtest in a live client, and assert
		the game loaded every object the writer emitted.

		OPTIONS
		  --fixture DIR     the modlet to build   (default: examples/SelfTestMod)
		  --stem NAME       asset stem it carries (default: shamwaySelfTestProp)
		  -h, --help        this text

		Anything after -- is passed to playtest-acceptance.sh, so --listen and
		--reuse-save reach the orchestrator unchanged.

		ENVIRONMENT
		  SEVEN_DAYS_TO_DIE_DIR         the client install (required)
		  SEVEN_DAYS_TO_DIE_SERVER_DIR  the dedicated server install (required)

		EXIT
		  0  the game loaded the prefab, its mesh, its material and its texture
		  1  a case failed, or an assertion below did

		This proves the engine READ the bundle. It says nothing about whether
		the prop draws upright, at the right scale, or at all: every assertion
		here passes on a prop rendered mirrored or face-down. That judgement is
		a person's, and `shamway client capture` is where it gets filed.
	EOF
}

while (($#)); do
	case "$1" in
		--fixture) FIXTURE="${2:-}"; shift 2 ;;
		--stem) STEM="${2:-}"; shift 2 ;;
		-h|--help) usage; exit 0 ;;
		--) shift; EXTRA=("$@"); break ;;
		*) die "unknown option: $1 (try --help)" ;;
	esac
done

SHAMWAY="${SHAMWAY:-shamway}"
command -v "$SHAMWAY" >/dev/null 2>&1 || die "$SHAMWAY is not on PATH"
[[ -n "${SEVEN_DAYS_TO_DIE_DIR:-}" ]] || die "SEVEN_DAYS_TO_DIE_DIR is not set"
[[ -n "${SEVEN_DAYS_TO_DIE_SERVER_DIR:-}" ]] ||
	die "SEVEN_DAYS_TO_DIE_SERVER_DIR is not set; the orchestrator starts a dedicated server"

HERE="$(cd "$(dirname "$0")" && pwd)"
ACCEPT="$HERE/playtest-acceptance.sh"
[[ -x "$ACCEPT" ]] || die "no playtest-acceptance.sh beside this script ($ACCEPT)"

MOD="${FIXTURE:-$HERE/../examples/SelfTestMod}"
[[ -d "$MOD" ]] || die "no self-test modlet at $MOD (--fixture DIR)"
[[ -f "$MOD/ModInfo.xml" ]] || die "$MOD has no ModInfo.xml; is that a modlet?"
[[ -f "$MOD/.shamway.toml" ]] || die "$MOD is not scaffolded; run: shamway init $MOD --game-dir ..."
MOD="$(cd "$MOD" && pwd)"
MOD_NAME="$(sed -n 's/.*<Name value="\([^"]*\)".*/\1/p' "$MOD/ModInfo.xml" | head -1)"
BUNDLE="$(sed -n 's/^bundle_name = "\(.*\)"$/\1/p' "$MOD/.shamway.toml" | head -1)"
[[ -n "$MOD_NAME" && -n "$BUNDLE" ]] || die "cannot read the mod name or bundle name from $MOD"
[[ -f "$MOD/assets-src/bundle/$STEM.glb" ]] ||
	die "$MOD has no assets-src/bundle/$STEM.glb (--stem names the wrong asset?)"

echo "SYNTHESIZED-BUNDLE SELF TEST"
echo "  modlet         $MOD"
echo "  mod            $MOD_NAME"
echo "  bundle         $BUNDLE"
echo "  stem           $STEM"
echo

echo "BUILD (no editor)"
(cd "$MOD" && "$SHAMWAY" build)
(cd "$MOD" && "$SHAMWAY" validate)
echo

# The prefab lane is what this test is for. Without a usable shader compiler
# the writer packs a bare Mesh by design, and asserting the prefab then would
# report a missing capability as a broken bundle.
if ! (cd "$MOD" && "$SHAMWAY" inspect --deep "Resources/$BUNDLE" | grep -q "GameObject="); then
	die "the bundle carries no prefab; the shader lane did not run. Check
       'shamway capabilities --missing' — without vkd3d >= 1.3 the writer packs
       a bare Mesh, which this test cannot tell apart from a regression."
fi

echo "LIVE CLIENT (hordeforge/7dtd-playtest)"
LOG="$MOD/.selftest-acceptance.log"
# The client launcher writes the same log path every run, so an assertion that
# matched a *previous* run's lines would pass without this run proving
# anything - the same "an unrun gate reads like a passed one" failure the
# `not run:` lines exist for. Everything asserted below has to post-date this.
STARTED_AT="$(date +%s)"
set +e
"$ACCEPT" --mod-root "$MOD" "${EXTRA[@]}" 2>&1 | tee "$LOG"
STATUS="${PIPESTATUS[0]}"
set -e
echo

echo "ASSERTIONS"
# shellcheck disable=SC2329  # invoked by the assertion lines below
fail() {
	echo "  FAIL $*"
	FAILED=1
}
FAILED=0

# The per-asset detail lines live in the CLIENT log, not in the acceptance
# script's stdout, which reprints only PASS/FAIL/SUMMARY. Asserting against
# stdout made all four value checks fail on a run whose suite passed 5/5 — a
# false alarm that reads exactly like a broken bundle.
CLIENT_LOG="$(sed -n 's/^  client log *//p' "$LOG" | head -1)"
[[ -n "$CLIENT_LOG" ]] || die "could not find the client log path in the acceptance output"
[[ -f "$CLIENT_LOG" ]] || die "the acceptance run named a client log that is not there: $CLIENT_LOG"
CLIENT_LOG_AT="$(stat -c %Y "$CLIENT_LOG" 2>/dev/null || echo 0)"
((CLIENT_LOG_AT >= STARTED_AT)) ||
	die "$CLIENT_LOG predates this run ($(date -d "@$CLIENT_LOG_AT" '+%H:%M:%S') <
       $(date -d "@$STARTED_AT" '+%H:%M:%S')): the client never wrote one, and
       asserting against it would grade a previous run"

grep -qE "SUMMARY pass=[0-9]+ fail=0 " "$LOG" || fail "a case failed (see the summary above)"

# Each of these is a distinct way the writer could be wrong while every offline
# gate still passed, so they are asserted by value rather than by case name.
grep -qE "$STEM: $STEM .*renderers=1" "$CLIENT_LOG" ||
	fail "the prefab did not come back with its renderer: an empty GameObject draws nothing"
grep -qE "${STEM}_mesh: .*bounds=\(0\.30, 0\.50, 0\.20\)" "$CLIENT_LOG" ||
	fail "the mesh bounds are not what was authored: the vertex stream or the Y-up conversion moved"
grep -qE "${STEM}_mat: .*shader=Shamway/Unlit" "$CLIENT_LOG" ||
	fail "the material does not name the synthesized shader: the PPtr chain broke"
grep -qE "${STEM}_albedo: .*256x256" "$CLIENT_LOG" ||
	fail "the texture did not come back at its authored size"

if ((FAILED)); then
	echo
	die "the live client did not read this bundle the way the writer wrote it"
fi

cat <<EOF
  OK   the prefab loaded, with its renderer
  OK   the mesh bounds are what was authored
  OK   the material names the synthesized shader
  OK   the texture loaded at its authored size

The game READ the bundle. Nobody has LOOKED at it: every assertion above
passes on a prop drawn mirrored, face-down, or nowhere. Place ${STEM}Block in a
client and judge it, then file the frame:

  shamway client capture ${STEM} --observable "upright, R not mirrored, arrow up"
EOF
exit "$STATUS"
