#!/usr/bin/env bash
# Compile the pipeline-owned Unity editor scripts against a real editor's
# assemblies, without starting the editor.
#
# The Python suite cannot see a C# mistake, and Unity reports one only as
# "Scripts have compiler errors" with the real CS line buried in its log. This
# is the cheap middle ground: Mono's mcs against the editor's own
# UnityEngine/UnityEditor module assemblies and its netstandard 2.1 reference.
# It proves the scripts compile for that revision; it does not prove they do
# the right thing when run. State that difference when reporting.
#
# Needs: mcs (Mono), and an installed editor — UNITY_EDITOR, or the Hub layout
# (~/Unity/Hub/Editor on Linux, /Applications/Unity/Hub/Editor on macOS) for
# the revision in the template's ProjectVersion.txt.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# mktemp follows TMPDIR, and its default /tmp is tmpfs on most Linux hosts,
# so the compiler output below would be written to RAM. Keep it on disk unless
# the caller already chose somewhere.
: "${TMPDIR:=${XDG_CACHE_HOME:-$HOME/.cache}/shamway/tmp}"
mkdir -p "$TMPDIR"
export TMPDIR

# From a checkout the template is under src/; from the installed package
# (`shamway script compile-editor-scripts`) it sits beside this script's parent.
TEMPLATE="$ROOT/src/sevendtd_asset_pipeline/templates/UnityProject"
[[ -d "$TEMPLATE" ]] || TEMPLATE="$ROOT/templates/UnityProject"
SCRIPTS="$TEMPLATE/Assets/SevenDaysToDieAssetPipeline/Editor"

usage() {
	cat <<'HELP'
Compile the Unity editor scripts this pipeline ships, against a real editor.

USAGE
  scripts/compile-editor-scripts.sh [--editor-data DIR] [--quiet-missing]

OPTIONS
  --scripts DIR       The folder of .cs files to compile. Defaults to this
                      pipeline's template; in a mod, point it at the vendored
                      Assets/SevenDaysToDieAssetPipeline/Editor — or at the
                      mod's own Editor folder, together with --with DIR
  --with DIR          A second folder of .cs files compiled in the same unit
                      (a mod's generators need the vendored scripts)
  --editor-data DIR   The editor's Data/ directory (…/Editor/Data). Defaults
                      to UNITY_EDITOR's, then the newest 2022.3 editor under
                      Hub's install root (~/Unity/Hub/Editor, or
                      /Applications/Unity/Hub/Editor on macOS) for the
                      template's ProjectVersion.txt revision
  --quiet-missing     Exit 0 with a note when mcs or the editor is absent,
                      so `make check` can run this opportunistically
  -h, --help          Show this help

EXAMPLES
  scripts/compile-editor-scripts.sh                       # find the editor
  UNITY_EDITOR=~/Unity/Hub/Editor/2022.3.62f2/Editor/Unity scripts/compile-editor-scripts.sh
HELP
}

EDITOR_DATA=""
QUIET_MISSING=0
WITH_DIRS=()
while (($#)); do
	case "$1" in
		--scripts) SCRIPTS="$2"; shift 2 ;;
		--with) WITH_DIRS+=("$2"); shift 2 ;;
		--editor-data) EDITOR_DATA="$2"; shift 2 ;;
		--quiet-missing) QUIET_MISSING=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "ERROR: unknown option $1" >&2; usage >&2; exit 1 ;;
	esac
done

skip() {
	if ((QUIET_MISSING)); then
		echo "note: $1; skipped editor-script compile"
		exit 0
	fi
	echo "ERROR: $1" >&2
	exit 1
}

command -v mcs >/dev/null 2>&1 || skip "mcs (Mono) is not installed"

if [[ -z "$EDITOR_DATA" ]]; then
	if [[ -n "${UNITY_EDITOR:-}" && -x "$UNITY_EDITOR" ]]; then
		EDITOR_DATA="$(dirname "$UNITY_EDITOR")/Data"
	else
		# The template carries a placeholder revision that `init` replaces with
		# the installed game's. Without UNITY_EDITOR, take the newest 2022.3
		# editor Hub has installed — the one a developer of this repo builds with.
		revision="$(sed -n 's/^m_EditorVersion: //p' "$TEMPLATE/ProjectSettings/ProjectVersion.txt" | head -n1)"
		# Hub installs under a different root per host OS: ~/Unity/Hub/Editor on
		# Linux, /Applications/Unity/Hub/Editor on macOS. Probe both, so the
		# discovery works wherever this repository claims to run.
		hub_roots=("$HOME/Unity/Hub/Editor" "/Applications/Unity/Hub/Editor")
		hub_root=""
		if [[ -n "$revision" ]]; then
			for candidate_root in "${hub_roots[@]}"; do
				if [[ -d "$candidate_root/$revision" ]]; then
					hub_root="$candidate_root"
					break
				fi
			done
		fi
		if [[ -z "$hub_root" ]]; then
			# Nothing at the template's revision (or no revision): fall through to
			# the newest 2022.3 either Hub root has. An unmatched glob fails the
			# loop once, and pipefail would turn that into a failed assignment
			# under set -e; empty means nothing installed, which is the skip below.
			revision=""
			for candidate_root in "${hub_roots[@]}"; do
				newest="$(for editor in "$candidate_root"/2022.3.*/; do
					[[ -d "$editor" ]] && basename "$editor"
				done | sort -V | tail -n1)" || true
				if [[ -n "$newest" ]]; then
					revision="$newest"
					hub_root="$candidate_root"
					break
				fi
			done
		fi
		[[ -n "$hub_root" ]] || skip "no Unity 2022.3 editor under ${hub_roots[*]} and no UNITY_EDITOR"
		EDITOR_DATA="$hub_root/$revision/Editor/Data"
	fi
fi
[[ -d "$EDITOR_DATA/Managed/UnityEngine" ]] || skip "no editor assemblies at $EDITOR_DATA/Managed/UnityEngine"

netstandard="$EDITOR_DATA/NetStandard/ref/2.1.0/netstandard.dll"
[[ -f "$netstandard" ]] || skip "no netstandard 2.1 reference at $netstandard"

refs=(-r:"$netstandard")
for assembly in "$EDITOR_DATA"/Managed/UnityEngine/*.dll; do
	refs+=(-r:"$assembly")
done

output="$(mktemp -d)"
trap 'rm -rf "$output"' EXIT

[[ -d "$SCRIPTS" ]] || skip "no scripts folder at $SCRIPTS"
sources=("$SCRIPTS"/*.cs)
for extra in "${WITH_DIRS[@]}"; do
	sources+=("$extra"/*.cs)
done
echo "Compiling ${#sources[@]} editor scripts against $EDITOR_DATA"
# -noconfig -nostdlib: reference exactly the editor's assembly set and nothing
# from the host Mono, so a host-only API cannot make a broken script pass.
# -langversion:latest: mcs defaults low and reports CS1738 on named arguments
# Unity's own compiler accepts. Only Managed/UnityEngine/*.dll is referenced —
# UnityEditor.dll lives there too, and adding Managed/UnityEditor.dll as well
# is CS1704 (same assembly imported twice).
# 0618 is a *warning*-level Obsolete; an error-level one still fails, which is
# the whole point — see ImportAudioClip in GeneratedAsset.cs.
if mcs -target:library -langversion:latest -noconfig -nostdlib -nowarn:0618,0219 \
	-out:"$output/ShamwayEditorScripts.dll" "${refs[@]}" "${sources[@]}"; then
	echo "OK: editor scripts compile for $(basename "$(dirname "$(dirname "$EDITOR_DATA")")")"
else
	echo "ERROR: editor scripts do not compile; Unity would report 'Scripts have compiler errors'" >&2
	exit 1
fi
