#!/usr/bin/env bash
# Install the exact Unity editor a modlet's asset bundle requires.
#
# Deliberately separate from install-tools.sh: Unity Hub sign-in is a
# user-owned account action, while the editor archive and its Windows module
# are project prerequisites that can be automated once a license is active.
#
# The revision, changeset, download URLs, and MD5 checksums are resolved from
# Unity's official release service for whatever version the project needs, so
# nothing here goes stale when the game updates its engine.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HUB_APP_ID="com.unity.UnityHub"
VERSION=""
PROJECT=""
SKIP_HUB=0

usage() {
	cat <<'HELP'
Install a game-matched Unity editor and its Windows Build Support (Mono).

USAGE
  scripts/install-unity-editor.sh [--version VERSION] [--project DIR] [--skip-hub]

OPTIONS
  --version VERSION  Unity revision to install. Defaults to the revision in
                     --project's ProjectSettings/ProjectVersion.txt.
  --project DIR      Unity project whose revision and license are verified.
                     Defaults to $PWD/tools/shamway/UnityProject.
  --skip-hub         Do not install or open Unity Hub. Use when a license is
                     already active in Unity's native Linux location.
  -h, --help         Show this help

STEPS
  1. Resolve the official download for the revision (Unity release service).
  2. Install Unity Hub from Flathub when it is not already present.
  3. Open Hub and wait for you to sign in and activate a license.
  4. Copy Hub's active license from its Flatpak sandbox to Unity's native
     Linux location, readable only by the current user.
  5. Download and verify the editor archive, then install it.
  6. Download, verify, and install Windows Build Support (Mono).
  7. Prove the editor can open the project in batch mode with that license.

Hub sign-in needs an interactive terminal and a graphical desktop. Sign-in and
license activation are deliberately never automated: never put Unity account
credentials in a shell script, an environment variable, or a config file.

ENVIRONMENT
  UNITY_EDITOR               Use this exact editor executable if it exists.
  UNITY_EDITOR_INSTALL_DIR   Install here instead of ~/Unity/Hub/Editor/VERSION.
HELP
}

while (($#)); do
	case "$1" in
		--version) VERSION="${2:?--version needs a value}"; shift 2 ;;
		--project) PROJECT="${2:?--project needs a value}"; shift 2 ;;
		--skip-hub) SKIP_HUB=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "ERROR: unknown option $1" >&2; usage >&2; exit 1 ;;
	esac
done

PROJECT="${PROJECT:-$PWD/tools/shamway/UnityProject}"
if [[ -z "$VERSION" ]]; then
	if [[ ! -f "$PROJECT/ProjectSettings/ProjectVersion.txt" ]]; then
		echo "ERROR: no Unity project at $PROJECT and no --version given." >&2
		echo "       Run 'shamway init' first, or pass --version explicitly." >&2
		exit 1
	fi
	VERSION="$(sed -n 's/^m_EditorVersion: *//p' \
		"$PROJECT/ProjectSettings/ProjectVersion.txt" | head -n1)"
fi
if [[ -z "$VERSION" ]]; then
	echo "ERROR: could not determine the required Unity revision." >&2
	exit 1
fi

for required in curl python3; do
	if ! command -v "$required" >/dev/null 2>&1; then
		echo "ERROR: $required is required. Run scripts/install-tools.sh --with-unity-prereqs." >&2
		exit 1
	fi
done

echo "Resolving the official Unity $VERSION download"
# From a checkout, run the module in place; from the installed package
# (`shamway script install-unity-editor`), the command is already on PATH.
if [[ -d "$ROOT/src/sevendtd_asset_pipeline" ]]; then
	RELEASE_JSON="$(PYTHONPATH="$ROOT/src" python3 -m sevendtd_asset_pipeline \
		unity-release --version "$VERSION" --json)"
else
	RELEASE_JSON="$(shamway unity-release --version "$VERSION" --json)"
fi
read_field() {
	printf '%s' "$RELEASE_JSON" | python3 -c \
		'import json,sys; print(json.load(sys.stdin)[sys.argv[1]] or "")' "$1"
}
EDITOR_URL="$(read_field editor_url)"
EDITOR_MD5="$(read_field editor_md5)"
MODULE_URL="$(read_field windows_mono_url)"
MODULE_MD5="$(read_field windows_mono_md5)"
CHANGESET="$(read_field changeset)"
echo "OK: Unity $VERSION is changeset $CHANGESET"
if [[ -z "$EDITOR_URL" || -z "$MODULE_URL" ]]; then
	echo "ERROR: Unity's release service did not list a Linux editor and windows-mono module." >&2
	exit 1
fi

download_verified() {
	local url="$1" expected="$2" destination="$3" actual
	echo "Downloading $(basename "$url")"
	curl --fail --location --silent --show-error --retry 3 "$url" -o "$destination"
	if [[ -z "$expected" ]]; then
		# Unity normally publishes an MD5 for every download. Refusing here is
		# better than installing several gigabytes of unverified editor.
		echo "ERROR: Unity published no checksum for $url; refusing to install it." >&2
		exit 1
	fi
	actual="$(md5sum "$destination" | awk '{print $1}')"
	if [[ "$actual" != "$expected" ]]; then
		echo "ERROR: checksum mismatch for $url (got $actual, expected $expected)." >&2
		exit 1
	fi
	echo "OK: checksum verified"
}

ensure_hub() {
	if ! command -v flatpak >/dev/null 2>&1; then
		echo "ERROR: Flatpak is required to install Unity Hub." >&2
		echo "       Run scripts/install-tools.sh --with-unity-prereqs first." >&2
		exit 1
	fi
	if flatpak info "$HUB_APP_ID" >/dev/null 2>&1; then
		echo "OK: Unity Hub is already installed"
		return
	fi
	if ! flatpak remotes --columns=name | grep -qx 'flathub'; then
		flatpak remote-add --if-not-exists --user flathub \
			https://dl.flathub.org/repo/flathub.flatpakrepo
	fi
	echo "Installing Unity Hub from Flathub"
	flatpak install --user --noninteractive flathub "$HUB_APP_ID"
}

activate_license_in_hub() {
	if ! [[ -t 0 ]]; then
		echo "ERROR: Unity Hub activation needs an interactive terminal." >&2
		echo "       Run this from a terminal on the graphical desktop, or use --skip-hub" >&2
		echo "       when a license is already active." >&2
		exit 1
	fi
	local hub_log
	hub_log="$(mktemp)"
	echo "Opening Unity Hub"
	flatpak run "$HUB_APP_ID" >"$hub_log" 2>&1 &
	cat <<'PROMPT'

UNITY HUB ACTION REQUIRED

In the Hub window:
  1. Sign in with your Unity account.
  2. Open Preferences -> Licenses.
  3. Add or activate your Unity license (Unity Personal is sufficient).

Return here only after Hub shows the license as active, then press Enter.
PROMPT
	read -r
	rm -f "$hub_log"
}

sync_flatpak_license() {
	local sandbox_data sandbox_config native_data native_config
	sandbox_data="$HOME/.var/app/$HUB_APP_ID/data/unity3d/Unity/Unity_lic.ulf"
	sandbox_config="$HOME/.var/app/$HUB_APP_ID/config/unity3d/Unity/licenses/UnityEntitlementLicense.xml"
	native_data="$HOME/.local/share/unity3d/Unity/Unity_lic.ulf"
	native_config="$HOME/.config/unity3d/Unity/licenses/UnityEntitlementLicense.xml"

	if [[ ! -s "$sandbox_data" ]]; then
		echo "ERROR: Unity Hub did not create its active license file." >&2
		echo "       Confirm the license appears in Hub, then rerun this script." >&2
		exit 1
	fi
	mkdir -p "$(dirname "$native_data")"
	install -m 600 "$sandbox_data" "$native_data"
	if [[ -s "$sandbox_config" ]]; then
		mkdir -p "$(dirname "$native_config")"
		install -m 600 "$sandbox_config" "$native_config"
	fi
	echo "OK: copied the active Hub license to Unity's native Linux location"
}

install_editor() {
	local editor="$1" install_dir archive staging candidate
	install_dir="$(dirname "$(dirname "$editor")")"
	if [[ -e "$install_dir" ]]; then
		echo "ERROR: Unity destination exists but has no Editor/Unity: $install_dir" >&2
		exit 1
	fi
	if ! command -v tar >/dev/null 2>&1; then
		echo "ERROR: tar is required to unpack the Unity editor." >&2
		exit 1
	fi
	archive="$(mktemp)"
	staging="$(mktemp -d)"
	trap 'rm -f "$archive"; rm -rf "$staging"' RETURN
	download_verified "$EDITOR_URL" "$EDITOR_MD5" "$archive"
	echo "Unpacking Unity $VERSION (this takes a while)"
	tar -xf "$archive" -C "$staging"
	candidate="$staging"
	if [[ ! -x "$candidate/Editor/Unity" ]]; then
		candidate="$(find "$staging" -type f -path '*/Editor/Unity' -print -quit |
			sed 's#/Editor/Unity$##')"
	fi
	if [[ -z "$candidate" || ! -x "$candidate/Editor/Unity" ]]; then
		echo "ERROR: Unity archive did not contain Editor/Unity." >&2
		exit 1
	fi
	mkdir -p "$(dirname "$install_dir")"
	mv "$candidate" "$install_dir"
	trap - RETURN
	rm -f "$archive"
	rm -rf "$staging"
	[[ -x "$editor" ]] || { echo "ERROR: install did not produce $editor." >&2; exit 1; }
	echo "OK: Unity $VERSION installed at $editor"
}

resolve_editor() {
	local configured default
	configured="${UNITY_EDITOR:-}"
	default="${UNITY_EDITOR_INSTALL_DIR:-$HOME/Unity/Hub/Editor/$VERSION}/Editor/Unity"
	if [[ -n "$configured" ]]; then
		if [[ ! -x "$configured" ]]; then
			echo "ERROR: UNITY_EDITOR is not executable: $configured" >&2
			exit 1
		fi
		UNITY_EDITOR_PATH="$configured"
		return
	fi
	if [[ -x "$default" ]]; then
		UNITY_EDITOR_PATH="$default"
		echo "OK: reusing the editor already at $default"
		return
	fi
	install_editor "$default"
	UNITY_EDITOR_PATH="$default"
}

ensure_windows_build_support() {
	local editor="$1" support_dir archive staging package_dir extracted_dir
	support_dir="$(dirname "$editor")/Data/PlaybackEngines/WindowsStandaloneSupport"
	if [[ -f "$support_dir/UnityEditor.WindowsStandalone.Extensions.dll" ]]; then
		echo "OK: Windows Build Support (Mono) is installed"
		return
	fi
	if [[ -e "$support_dir" ]]; then
		# An interrupted Hub module install can leave an empty destination. It
		# holds no user assets, so recover it here rather than asking every
		# caller to identify and delete it by hand.
		if [[ -d "$support_dir" && -z "$(find "$support_dir" -mindepth 1 -print -quit)" ]]; then
			rmdir "$support_dir"
		else
			echo "ERROR: Windows Build Support exists but is incomplete: $support_dir" >&2
			echo "       Preserve it for inspection; do not build a Windows bundle until repaired." >&2
			exit 1
		fi
	fi
	for required in bsdtar md5sum; do
		if ! command -v "$required" >/dev/null 2>&1; then
			echo "ERROR: $required is required. Run scripts/install-tools.sh --with-unity-prereqs." >&2
			exit 1
		fi
	done
	archive="$(mktemp)"
	staging="$(mktemp -d)"
	trap 'rm -f "$archive"; rm -rf "$staging"' RETURN
	package_dir="$staging/package"
	extracted_dir="$staging/extracted"
	mkdir -p "$package_dir" "$extracted_dir"
	download_verified "$MODULE_URL" "$MODULE_MD5" "$archive"
	# Unity distributes this cross-platform module in a macOS .pkg wrapper.
	# libarchive extracts its XAR and cpio layers without requiring macOS.
	bsdtar -xf "$archive" -C "$package_dir"
	bsdtar -xf "$package_dir/TargetSupport.pkg.tmp/Payload" -C "$extracted_dir"
	if [[ ! -f "$extracted_dir/UnityEditor.WindowsStandalone.Extensions.dll" ]]; then
		echo "ERROR: Unity's Windows Build Support archive was incomplete." >&2
		exit 1
	fi
	mkdir -p "$(dirname "$support_dir")"
	mv "$extracted_dir" "$support_dir"
	trap - RETURN
	rm -f "$archive"
	rm -rf "$staging"
	echo "OK: Windows Build Support (Mono) is installed"
}

verify_license() {
	local editor="$1" log
	if [[ ! -d "$PROJECT" ]]; then
		echo "WARN: no Unity project at $PROJECT; skipping the batch-mode license proof."
		return
	fi
	log="$(mktemp)"
	if "$editor" -batchmode -nographics -quit -projectPath "$PROJECT" -logFile "$log"; then
		rm -f "$log"
		echo "OK: Unity batch-mode license is active"
		return
	fi
	rm -f "$log"
	echo "ERROR: Unity could not read an active license in batch mode." >&2
	echo "       Confirm the license is active in Hub, then rerun this script so it" >&2
	echo "       refreshes Unity's native license file." >&2
	exit 1
}

if ((SKIP_HUB)); then
	echo "Skipping Unity Hub; assuming an active native license"
else
	ensure_hub
	activate_license_in_hub
	sync_flatpak_license
fi
resolve_editor
ensure_windows_build_support "$UNITY_EDITOR_PATH"
verify_license "$UNITY_EDITOR_PATH"

cat <<EOF

OK: Unity asset-bundle setup is ready.

Export this machine-local path (do not commit it):
  export UNITY_EDITOR="$UNITY_EDITOR_PATH"

Then prove the whole pipeline:
  shamway doctor
  shamway build --probe
EOF
