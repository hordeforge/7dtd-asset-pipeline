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
LOOK=0
LOOK_STEM=""
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
		  --look [STEM]     run that prefab's look suite (<mod>_<stem>_look) alone:
		                    one camera-staged instance, one invocation. Without
		                    STEM, runs shamwayselftest_burst_look (the looping VFX
		                    prefab). The generated rigs each get their own look
		                    suite — shamwayselftest_shamwaySelfTestCreature_look,
		                    _Bird_look, _Arachnid_look, _Dino_look.
		  -h, --help        this text

		Anything after -- is passed to playtest-acceptance.sh, so --listen (and
		any other accepted flag) reaches the orchestrator unchanged. There is no
		--reuse-save: every run starts from a fresh save, a hard rule.

		ENVIRONMENT
		  SEVEN_DAYS_TO_DIE_DIR         the client install (required)
		  SEVEN_DAYS_TO_DIE_SERVER_DIR  the dedicated server install (required)

		EXIT
		  0  the game loaded the prefab and placed the block on a voxel
		     (--look: the look suite held the floating prefabs)
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
		--look) LOOK=1; shift
			if (($#)) && [[ "$1" != -* ]]; then
				LOOK_STEM="$1"; shift
			fi ;;
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
# The generated bundle suite proves DataLoader.LoadAsset. The block-model
# suite is how the prop is supposed to be seen: SetBlockRpc onto a grounded
# voxel, wait for the ModelEntity, LookAt the voxel — the same pattern as
# AtomicDoomsday's placed bomb/detonator. Never add *_look to this default
# list: that suite instantiates the prefab in front of the camera, and
# mixing it with a block suite is how a texture floated mid-air in the same
# session as a placed block. --look is a separate invocation. Do not smuggle
# a camera-staged instantiate into _editorless so it can ride with the block.
SUITE_ARGS=()
has_suite=0
for arg in "${EXTRA[@]+"${EXTRA[@]}"}"; do
	if [[ "$arg" == "--suite" ]]; then
		has_suite=1
		break
	fi
done
if (( LOOK )); then
	if (( has_suite )); then
		die "--look already selects a <mod>_<stem>_look suite; do not also pass --suite"
	fi
	if [[ -n "$LOOK_STEM" ]]; then
		SUITE_ARGS=(--suite "${MOD_NAME,,}_${LOOK_STEM}_look")
	else
		SUITE_ARGS=(--suite "shamwayselftest_burst_look")
	fi
elif (( ! has_suite )); then
	SUITE_ARGS=(--suite "shamwayselftest_bundle,shamwayselftest_block_model,shamwayselftest_editorless")
	# One concern: the synthesized bundle loads and the block sits on a
	# voxel. Not a floating-prefab look; that is --look, a second invocation.
	export PLAYTEST_CONCERN_SUITES="shamwayselftest_bundle,shamwayselftest_block_model,shamwayselftest_editorless"
fi
LOG="$MOD/.selftest-acceptance.log"
# The client launcher writes the same log path every run, so an assertion that
# matched a *previous* run's lines would pass without this run proving
# anything - the same "an unrun gate reads like a passed one" failure the
# `not run:` lines exist for. Everything asserted below has to post-date this.
STARTED_AT="$(date +%s)"
set +e
"$ACCEPT" --mod-root "$MOD" "${SUITE_ARGS[@]}" "${EXTRA[@]}" 2>&1 | tee "$LOG"
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

CREATURE="shamwaySelfTestCreature"
if (( LOOK )); then
	if [[ -n "$LOOK_STEM" ]]; then
		grep -qE "$LOOK_STEM: staged at .*with [1-9][0-9]* renderer" "$CLIENT_LOG" ||
			fail "the $LOOK_STEM prefab was not staged in front of the camera with a renderer"
	else
		grep -qE "scene staged look_burst" "$CLIENT_LOG" ||
			fail "look_burst was not staged in front of the camera"
		grep -qE "burst: staged at" "$CLIENT_LOG" ||
			fail "the looping VFX prefab was not held in front of the camera"
	fi
else
	# Each of these is a distinct way the writer could be wrong while every
	# offline gate still passed, so they are asserted by value rather than
	# by case name.
	grep -qE "$STEM: $STEM .*renderers=1" "$CLIENT_LOG" ||
		fail "the prefab did not come back with its renderer: an empty GameObject draws nothing"
	grep -qE "${STEM}_mesh: .*bounds=\(1\.00, 1\.00, 1\.00\)" "$CLIENT_LOG" ||
		fail "the mesh bounds are not what was authored: the vertex stream or the Y-up conversion moved"
	grep -qE "${STEM}_mat: .*shader=Shamway/Unlit" "$CLIENT_LOG" ||
		fail "the material does not name the synthesized shader: the PPtr chain broke"
	grep -qE "${STEM}_albedo: .*256x256" "$CLIENT_LOG" ||
		fail "the texture did not come back at its authored size"
	# The entity lane: a generated creature rides the same bundle. Its prefab
	# must come back with its SkinnedMeshRenderer (renderers=1) and its weighted
	# mesh with the authored vertex count. Spawning it as an entity class is
	# deliberately NOT asserted here: a custom entity class on a dedicated
	# server gets a negative id and renders nothing on clients
	# (docs/authoring/entities.md), and this run always uses one. The prefab
	# load is the engine reading the bundle; the class wiring is the offline
	# `validate` gate's job.
	grep -qE "$CREATURE: $CREATURE .*renderers=1" "$CLIENT_LOG" ||
		fail "the entity prefab did not come back with its skinned renderer: an empty GameObject draws nothing"
	grep -qE "${CREATURE}_mesh: .*vertices=[0-9]+ submeshes=1" "$CLIENT_LOG" ||
		fail "the entity mesh did not load with its vertex stream: the skin was flattened or dropped"
	grep -qE "${CREATURE}_albedo: .*256x256" "$CLIENT_LOG" ||
		fail "the entity texture did not come back at its authored size"
	grep -qE "PASS shamwayselftest_block_model/place_${STEM}Block" "$CLIENT_LOG" ||
		fail "the block was not placed on a voxel (SetBlockRpc + ModelEntity spawn)"
	grep -qE "${STEM}Block: .*looking at voxel" "$CLIENT_LOG" ||
		fail "the look case did not aim at the placed voxel; the model was not left in the world"
	grep -qE "timedNuke: armedLamp" "$CLIENT_LOG" ||
		fail "the hierarchy prefab has no child named armedLamp"
	grep -qE "gear: bones=2 nulls=0 root=Hips" "$CLIENT_LOG" ||
		fail "the skinned prefab did not resolve both bones and a Hips root"
	grep -qE "burst: systems=[0-9]+ renderers=[0-9]+ instantiated=True" "$CLIENT_LOG" ||
		fail "the vfx prefab did not instantiate ParticleSystem graphs"
fi

if ((FAILED)); then
	echo
	die "the live client did not read this bundle the way the writer wrote it"
fi

if (( LOOK )); then
	if [[ -n "$LOOK_STEM" ]]; then
		cat <<EOF
  OK   the $LOOK_STEM prefab staged in front of the camera, with a renderer

The game instantiated the generated rig. What it looked like is in the
captured frames — judge them, then file the sign-off:

  shamway client capture $LOOK_STEM --observable "reads as its rig: proportions, facing, not mirrored"
EOF
	else
		cat <<EOF
  OK   look_burst was held in front of the camera

The game STAGED the looping VFX prefab (gold flash, grey haze, falling
sparks — cards from shamway generate particle-card). Judge that picture,
then file a frame. This is not a placed block:

  shamway client capture burst --observable "looping gold flash, grey haze, falling streaks"
EOF
	fi
else
	cat <<EOF
  OK   the prefab loaded, with its renderer
  OK   the mesh bounds are what was authored
  OK   the material names the synthesized shader
  OK   the texture loaded at its authored size
  OK   the entity prefab loaded with its skinned renderer
  OK   the entity mesh loaded with its vertex stream
  OK   the entity texture loaded at its authored size
  OK   the block sits on a voxel and the camera looks at it
  OK   armedLamp is findable by name
  OK   the skinned renderer resolved both bones
  OK   the particle prefab instantiated without a load error

The game READ the bundle and placed ${STEM}Block. Nobody has LOOKED at the
floating prefabs in this run: that is a different picture
(\`playtest-synthesized.sh --look\`). Judge the placed block, then file
the frame:

  shamway client capture ${STEM} --observable "upright, R not mirrored, arrow up"
EOF
fi
exit "$STATUS"
