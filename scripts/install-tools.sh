#!/usr/bin/env bash
# Install the host tooling this pipeline builds and inspects assets with.
#
# Only Python 3.11+ and a game-matched Unity editor are pipeline requirements.
# Everything else here supports the authoring lanes in docs/authoring-tools.md
# and is opt-in, so a build host never installs desktop art packages it has no
# use for.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

WITH_AUTHORING=0
WITH_UNITY_PREREQS=0
CHECK_ONLY=0

usage() {
	cat <<'HELP'
Install host tooling for the 7DTD asset pipeline.

USAGE
  scripts/install-tools.sh [options]

OPTIONS
  --with-authoring       Also install the optional asset-authoring tools
                         (Blender, OpenSCAD, ImageMagick, FFmpeg)
  --with-unity-prereqs   Also install what scripts/install-unity-editor.sh
                         needs (curl, tar, libarchive, flatpak, libxml2.so.2)
  --check                Report what is present or missing and install nothing
  -h, --help             Show this help

BASE TOOLS
  python3 (>=3.11)   The pipeline CLI and its TOML configuration parser
  git, make          Version control and the consumer Makefile targets

WITH --with-authoring
  blender            Headless mesh authoring, conversion, and turntables
  openscad           Parametric hard-surface geometry
  imagemagick        Icons, masks, channel packing, contact sheets
  ffmpeg             Audio conversion, normalization, and synthesis

WITH --with-unity-prereqs
  curl, tar, xz      Downloading and unpacking the official editor archive
  libarchive         bsdtar, which extracts Unity's .pkg module wrapper
  flatpak            Unity Hub, for user-owned sign-in and license activation
  libxml2.so.2       The Unity 2022 editor links the old libxml2 soname;
                     distributions shipping 2.14+ provide only libxml2.so.16

This script never handles Unity credentials or licenses. See docs/setup.md.
HELP
}

while (($#)); do
	case "$1" in
		--with-authoring) WITH_AUTHORING=1; shift ;;
		--with-unity-prereqs) WITH_UNITY_PREREQS=1; shift ;;
		--check) CHECK_ONLY=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "ERROR: unknown option $1" >&2; usage >&2; exit 1 ;;
	esac
done

has_python_311() {
	command -v python3 >/dev/null 2>&1 &&
		python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'
}

has_libxml2_so2() {
	if command -v ldconfig >/dev/null 2>&1 && ldconfig -p 2>/dev/null | grep -q 'libxml2\.so\.2 '; then
		return 0
	fi
	local candidate
	for candidate in /usr/lib/libxml2.so.2 /usr/lib64/libxml2.so.2 \
		/usr/lib/x86_64-linux-gnu/libxml2.so.2; do
		[[ -e "$candidate" ]] && return 0
	done
	return 1
}

report() {
	local label="$1" purpose="$2"
	shift 2
	if "$@" >/dev/null 2>&1; then
		printf 'OK   %-14s %s\n' "$label" "$purpose"
	else
		printf 'MISS %-14s %s\n' "$label" "$purpose"
	fi
}

have() { command -v "$1" >/dev/null 2>&1; }

run_check() {
	report python3 "pipeline CLI (>=3.11, REQUIRED)" has_python_311
	report git "version control" have git
	report make "consumer Makefile targets" have make
	if ((WITH_AUTHORING)); then
		report blender "mesh authoring" have blender
		report openscad "parametric geometry" have openscad
		report magick "icons and textures" have magick
		report ffmpeg "audio" have ffmpeg
		report gltf_validator "glTF conformance" have gltf_validator
		report UnityPy "deep bundle inspection" python3 -c "import UnityPy"
		report Pillow "icon and texture lanes" python3 -c "import PIL"
		report NumPy "texture lane" python3 -c "import numpy"
		report trimesh "mesh checks" python3 -c "import trimesh"
	fi
	if ((WITH_UNITY_PREREQS)); then
		local tool
		for tool in curl tar xz bsdtar flatpak; do
			report "$tool" "Unity editor install" have "$tool"
		done
		report libxml2.so.2 "Unity editor runtime" has_libxml2_so2
	fi
}

if ((CHECK_ONLY)); then
	run_check
	exit 0
fi

SUDO=""
if [[ "$(id -u)" != "0" ]]; then
	if ! command -v sudo >/dev/null 2>&1; then
		echo "ERROR: installing system packages requires root or sudo." >&2
		exit 1
	fi
	SUDO="sudo"
fi

# Package names differ per distribution, so each branch names its own and the
# script refuses to guess on an unknown manager rather than installing wrongly.
declare -a PACKAGES=()

collect_pacman() {
	has_python_311 || PACKAGES+=(python)
	have git || PACKAGES+=(git)
	have make || PACKAGES+=(make)
	if ((WITH_AUTHORING)); then
		have blender || PACKAGES+=(blender)
		have openscad || PACKAGES+=(openscad)
		have magick || PACKAGES+=(imagemagick)
		have ffmpeg || PACKAGES+=(ffmpeg)
	fi
	if ((WITH_UNITY_PREREQS)); then
		have curl || PACKAGES+=(curl)
		have tar || PACKAGES+=(tar)
		have xz || PACKAGES+=(xz)
		have bsdtar || PACKAGES+=(libarchive)
		have flatpak || PACKAGES+=(flatpak)
		has_libxml2_so2 || PACKAGES+=(libxml2-legacy)
	fi
}

collect_apt() {
	has_python_311 || PACKAGES+=(python3)
	have git || PACKAGES+=(git)
	have make || PACKAGES+=(make)
	if ((WITH_AUTHORING)); then
		have blender || PACKAGES+=(blender)
		have openscad || PACKAGES+=(openscad)
		have magick || PACKAGES+=(imagemagick)
		have ffmpeg || PACKAGES+=(ffmpeg)
	fi
	if ((WITH_UNITY_PREREQS)); then
		have curl || PACKAGES+=(curl)
		have tar || PACKAGES+=(tar)
		have xz || PACKAGES+=(xz-utils)
		have bsdtar || PACKAGES+=(libarchive-tools)
		have flatpak || PACKAGES+=(flatpak)
		has_libxml2_so2 || PACKAGES+=(libxml2)
	fi
}

collect_dnf() {
	has_python_311 || PACKAGES+=(python3)
	have git || PACKAGES+=(git)
	have make || PACKAGES+=(make)
	if ((WITH_AUTHORING)); then
		have blender || PACKAGES+=(blender)
		have openscad || PACKAGES+=(openscad)
		have magick || PACKAGES+=(ImageMagick)
		have ffmpeg || PACKAGES+=(ffmpeg)
	fi
	if ((WITH_UNITY_PREREQS)); then
		have curl || PACKAGES+=(curl)
		have tar || PACKAGES+=(tar)
		have xz || PACKAGES+=(xz)
		have bsdtar || PACKAGES+=(bsdtar)
		have flatpak || PACKAGES+=(flatpak)
		has_libxml2_so2 || PACKAGES+=(libxml2)
	fi
}

if command -v pacman >/dev/null 2>&1; then
	collect_pacman
	((${#PACKAGES[@]})) && $SUDO pacman -S --needed --noconfirm "${PACKAGES[@]}"
elif command -v apt-get >/dev/null 2>&1; then
	collect_apt
	if ((${#PACKAGES[@]})); then
		$SUDO apt-get update
		$SUDO apt-get install -y "${PACKAGES[@]}"
	fi
elif command -v dnf >/dev/null 2>&1; then
	collect_dnf
	((${#PACKAGES[@]})) && $SUDO dnf install -y "${PACKAGES[@]}"
else
	echo "ERROR: no supported package manager (pacman, apt-get, dnf) was found." >&2
	echo "       Install the tools listed by 'scripts/install-tools.sh --check' by hand." >&2
	exit 1
fi

install_gltf_validator() {
	local url archive staging destination
	destination="${HOME}/.local/bin"
	if have gltf_validator || have gltf-validator; then
		echo "OK: gltf_validator is already installed"
		return
	fi
	if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
		echo "note: automatic gltf_validator setup supports Linux x86_64 only; see"
		echo "      https://github.com/KhronosGroup/glTF-Validator/releases"
		return
	fi
	for required in curl tar python3; do
		have "$required" || { echo "note: $required missing; skipped gltf_validator"; return; }
	done
	# Khronos publishes no 'latest' release, so resolve the newest tag rather
	# than pinning a version that goes stale.
	url="$(curl --fail --location --silent --show-error --max-time 30 \
		https://api.github.com/repos/KhronosGroup/glTF-Validator/releases 2>/dev/null |
		python3 -c 'import json,sys
try:
    releases = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
for release in releases if isinstance(releases, list) else []:
    for asset in release.get("assets", []):
        if asset.get("name", "").endswith("-linux64.tar.xz"):
            print(asset["browser_download_url"]); raise SystemExit(0)' || true)"
	if [[ -z "$url" ]]; then
		echo "note: could not resolve a gltf_validator release; skipped"
		return
	fi
	archive="$(mktemp)"
	staging="$(mktemp -d)"
	echo "Installing gltf_validator from $url"
	if curl --fail --location --silent --show-error --max-time 120 "$url" -o "$archive" &&
		tar -xJf "$archive" -C "$staging" 2>/dev/null &&
		[[ -f "$staging/gltf_validator" ]]; then
		mkdir -p "$destination"
		install -m 755 "$staging/gltf_validator" "$destination/gltf_validator"
		echo "OK: installed $destination/gltf_validator (ensure it is on PATH)"
	else
		echo "note: gltf_validator download or extraction failed; skipped"
	fi
	rm -f "$archive"
	rm -rf "$staging"
}

install_python_extras() {
	# Capabilities, not requirements: the pipeline core stays dependency-free
	# and each command says what to install when a capability is missing.
	local target="$ROOT"
	echo "Installing optional Python capabilities (UnityPy, Pillow, NumPy, trimesh)"
	if [[ -x "$ROOT/.venv/bin/pip" ]]; then
		"$ROOT/.venv/bin/pip" install --quiet --upgrade "${target}[all]" && {
			echo "OK: installed into $ROOT/.venv"; return; }
	fi
	if python3 -m pip install --quiet --user --upgrade "${target}[all]" 2>/dev/null; then
		echo "OK: installed for the current user"
		return
	fi
	echo "note: could not install the Python extras automatically. Run:"
	echo "      pip install '$target"'[all]'"'"
}

if ((WITH_AUTHORING)); then
	install_gltf_validator
	install_python_extras
fi

echo
echo "Installed base tooling. Current state:"
run_check
cat <<'EOF'

Next:
  scripts/bootstrap                    install the pipeline CLI
  7dtd-assets init MOD --game-dir ...  scaffold a modlet
  scripts/install-unity-editor.sh      install the game-matched Unity editor
EOF
