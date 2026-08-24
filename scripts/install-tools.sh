#!/usr/bin/env bash
# Install the host tooling this pipeline builds and inspects assets with.
#
# Only Python 3.11+ and a game-matched Unity editor are pipeline requirements.
# Everything else here supports the authoring lanes in docs/authoring/authoring-tools.md
# and is opt-in, so a build host never installs desktop art packages it has no
# use for.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

WITH_AUTHORING=0
WITH_UNITY_PREREQS=0
WITH_RESEARCH=0
WITH_DESKTOP_CAPTURE=0
CHECK_ONLY=0

usage() {
	cat <<'HELP'
Install host tooling for the 7DTD asset pipeline.

USAGE
  scripts/install-tools.sh [options]

OPTIONS
  --with-authoring       Also install the optional asset-authoring tools
                         (Blender, OpenSCAD, ImageMagick, FFmpeg, Xvfb)
  --with-unity-prereqs   Also install what scripts/install-unity-editor.sh
                         needs (curl, tar, libarchive, flatpak, libxml2.so.2)
  --with-research        Also install the decompilers that engine facts must
                         cite (.NET 8 SDK + ilspycmd, Mono's monodis)
  --with-desktop-capture Also install a screenshot tool, so the human visual
                         sign-off leaves a citable frame (grim, maim)
  --check                Report what is present or missing and install nothing
  -h, --help             Show this help

BASE TOOLS
  python3 (>=3.11)   The pipeline CLI and its TOML configuration parser
  uv                 The Python toolchain: environments, installs, and runs
  git, make          Version control and the consumer Makefile targets
  shellcheck         Lints this repository's scripts in 'make check'
  pactl              Mutes and unmutes a test client (shamway client mute)

WITH --with-authoring
  blender            Headless mesh authoring, conversion, and turntables
  openscad           Parametric hard-surface geometry
  imagemagick        Icons, masks, channel packing, contact sheets
  ffmpeg             Audio conversion, normalization, and synthesis
  xvfb               A virtual display for shamway render-icon, which
                     needs a real graphics device and silently renders a
                     blank image without one

WITH --with-unity-prereqs
  curl, tar, xz      Downloading and unpacking the official editor archive
  libarchive         bsdtar, which extracts Unity's .pkg module wrapper
  flatpak            Unity Hub, for user-owned sign-in and license activation
  libxml2.so.2       The Unity 2022 editor links the old libxml2 soname;
                     distributions shipping 2.14+ provide only libxml2.so.16

WITH --with-desktop-capture
  grim               Screenshots on a Wayland session
  maim               Screenshots on an X11 session
                     Either one satisfies 'shamway client capture'. An X11
                     host that already ran --with-authoring has ImageMagick's
                     'import' and needs neither.

WITH --with-research
  dotnet (8 SDK)     Hosts ilspycmd; installed as a global dotnet tool into
                     ~/.dotnet/tools, which must be on PATH
  ilspycmd           Decompiles Assembly-CSharp.dll: the named source every
                     new engine fact in docs/research/research-provenance.md cites
  monodis            Mono's IL disassembler, the second opinion on a method
                     body (and mcs, for compiling a throwaway check)

SUPPORTED PACKAGE MANAGERS
  pacman, apt-get, dnf, zypper. On anything else the script refuses to guess
  package names; install what --check lists by hand.

This script never handles Unity credentials or licenses. See docs/getting-started/setup.md.
HELP
}

while (($#)); do
	case "$1" in
		--with-authoring) WITH_AUTHORING=1; shift ;;
		--with-unity-prereqs) WITH_UNITY_PREREQS=1; shift ;;
		--with-research) WITH_RESEARCH=1; shift ;;
		--with-desktop-capture) WITH_DESKTOP_CAPTURE=1; shift ;;
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

# Any one of these satisfies 'shamway client capture'; the capability registry
# in capabilities.py probes the same list.
has_screenshot_tool() {
	local tool
	for tool in grim spectacle gnome-screenshot maim scrot import; do
		have "$tool" && return 0
	done
	return 1
}

has_dotnet_8_sdk() {
	have dotnet && dotnet --list-sdks 2>/dev/null | grep -q '^8\.'
}

has_ilspycmd() {
	have ilspycmd || [[ -x "$HOME/.dotnet/tools/ilspycmd" ]]
}

run_check() {
	report python3 "pipeline CLI (>=3.11, REQUIRED)" has_python_311
	report uv "Python toolchain (REQUIRED)" have uv
	report git "version control" have git
	report make "consumer Makefile targets" have make
	report shellcheck "script linting in make check" have shellcheck
	report pactl "client mute/unmute (shamway client)" have pactl
	if ((WITH_AUTHORING)); then
		report blender "mesh authoring" have blender
		report openscad "parametric geometry" have openscad
		report magick "icons and textures" have magick
		report ffmpeg "audio" have ffmpeg
		report xvfb-run "icon rendering on a headless host" have xvfb-run
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
	if ((WITH_DESKTOP_CAPTURE)); then
		report screenshot "visual sign-off (shamway client capture)" has_screenshot_tool
	fi
	if ((WITH_RESEARCH)); then
		report dotnet "8.x SDK, hosts ilspycmd" has_dotnet_8_sdk
		report ilspycmd "decompile Assembly-CSharp.dll" has_ilspycmd
		report monodis "Mono IL disassembler" have monodis
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
	have uv || PACKAGES+=(uv)
	have git || PACKAGES+=(git)
	have make || PACKAGES+=(make)
	have shellcheck || PACKAGES+=(shellcheck)
	have pactl || PACKAGES+=(libpulse)
	if ((WITH_AUTHORING)); then
		have blender || PACKAGES+=(blender)
		have openscad || PACKAGES+=(openscad)
		have magick || PACKAGES+=(imagemagick)
		have ffmpeg || PACKAGES+=(ffmpeg)
		have xvfb-run || PACKAGES+=(xorg-server-xvfb)
	fi
	if ((WITH_UNITY_PREREQS)); then
		have curl || PACKAGES+=(curl)
		have tar || PACKAGES+=(tar)
		have xz || PACKAGES+=(xz)
		have bsdtar || PACKAGES+=(libarchive)
		have flatpak || PACKAGES+=(flatpak)
		has_libxml2_so2 || PACKAGES+=(libxml2-legacy)
	fi
	if ((WITH_DESKTOP_CAPTURE)); then
		have grim || PACKAGES+=(grim)
		have maim || PACKAGES+=(maim)
	fi
	if ((WITH_RESEARCH)); then
		has_dotnet_8_sdk || PACKAGES+=(dotnet-sdk-8.0 dotnet-runtime-8.0)
		have monodis || PACKAGES+=(mono)
	fi
}

collect_apt() {
	has_python_311 || PACKAGES+=(python3)
	have git || PACKAGES+=(git)
	have make || PACKAGES+=(make)
	have shellcheck || PACKAGES+=(shellcheck)
	have pactl || PACKAGES+=(pulseaudio-utils)
	if ((WITH_AUTHORING)); then
		have blender || PACKAGES+=(blender)
		have openscad || PACKAGES+=(openscad)
		have magick || PACKAGES+=(imagemagick)
		have ffmpeg || PACKAGES+=(ffmpeg)
		have xvfb-run || PACKAGES+=(xvfb)
	fi
	if ((WITH_UNITY_PREREQS)); then
		have curl || PACKAGES+=(curl)
		have tar || PACKAGES+=(tar)
		have xz || PACKAGES+=(xz-utils)
		have bsdtar || PACKAGES+=(libarchive-tools)
		have flatpak || PACKAGES+=(flatpak)
		has_libxml2_so2 || PACKAGES+=(libxml2)
	fi
	if ((WITH_DESKTOP_CAPTURE)); then
		have grim || PACKAGES+=(grim)
		have maim || PACKAGES+=(maim)
	fi
	if ((WITH_RESEARCH)); then
		has_dotnet_8_sdk || PACKAGES+=(dotnet-sdk-8.0)
		have monodis || PACKAGES+=(mono-devel mono-utils)
	fi
}

collect_dnf() {
	has_python_311 || PACKAGES+=(python3)
	have git || PACKAGES+=(git)
	have make || PACKAGES+=(make)
	have shellcheck || PACKAGES+=(ShellCheck)
	have pactl || PACKAGES+=(pulseaudio-utils)
	if ((WITH_AUTHORING)); then
		have blender || PACKAGES+=(blender)
		have openscad || PACKAGES+=(openscad)
		have magick || PACKAGES+=(ImageMagick)
		have ffmpeg || PACKAGES+=(ffmpeg)
		have xvfb-run || PACKAGES+=(xorg-x11-server-Xvfb)
	fi
	if ((WITH_UNITY_PREREQS)); then
		have curl || PACKAGES+=(curl)
		have tar || PACKAGES+=(tar)
		have xz || PACKAGES+=(xz)
		have bsdtar || PACKAGES+=(bsdtar)
		have flatpak || PACKAGES+=(flatpak)
		has_libxml2_so2 || PACKAGES+=(libxml2)
	fi
	if ((WITH_DESKTOP_CAPTURE)); then
		have grim || PACKAGES+=(grim)
		have maim || PACKAGES+=(maim)
	fi
	if ((WITH_RESEARCH)); then
		has_dotnet_8_sdk || PACKAGES+=(dotnet-sdk-8.0)
		have monodis || PACKAGES+=(mono-devel)
	fi
}

collect_zypper() {
	has_python_311 || PACKAGES+=(python311)
	have git || PACKAGES+=(git)
	have make || PACKAGES+=(make)
	have shellcheck || PACKAGES+=(ShellCheck)
	have pactl || PACKAGES+=(pulseaudio-utils)
	if ((WITH_AUTHORING)); then
		have blender || PACKAGES+=(blender)
		have openscad || PACKAGES+=(openscad)
		have magick || PACKAGES+=(ImageMagick)
		have ffmpeg || PACKAGES+=(ffmpeg)
		have xvfb-run || PACKAGES+=(xvfb-run)
	fi
	if ((WITH_UNITY_PREREQS)); then
		have curl || PACKAGES+=(curl)
		have tar || PACKAGES+=(tar)
		have xz || PACKAGES+=(xz)
		have bsdtar || PACKAGES+=(bsdtar)
		have flatpak || PACKAGES+=(flatpak)
		has_libxml2_so2 || PACKAGES+=(libxml2-2)
	fi
	if ((WITH_DESKTOP_CAPTURE)); then
		have grim || PACKAGES+=(grim)
		have maim || PACKAGES+=(maim)
	fi
	if ((WITH_RESEARCH)); then
		has_dotnet_8_sdk || PACKAGES+=(dotnet-sdk-8.0)
		have monodis || PACKAGES+=(mono-devel)
	fi
}

install_uv() {
	local url sha_url archive staging expected actual destination
	destination="$HOME/.local/bin"
	if have uv; then
		echo "OK: uv is already installed ($(uv --version 2>/dev/null | head -n1))"
		return
	fi
	if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
		echo "note: automatic uv setup supports Linux x86_64 only; see https://docs.astral.sh/uv/"
		return
	fi
	for required in curl tar python3 sha256sum; do
		have "$required" || { echo "note: $required missing; skipped uv"; return; }
	done

	# Deliberately not 'curl | sh': the release tarball and its published
	# SHA-256 give the same result with something to verify against. The JSON
	# selection is a sibling script, so this file stays one language.
	url="$(curl --fail --location --silent --show-error --max-time 30 \
		https://api.github.com/repos/astral-sh/uv/releases/latest 2>/dev/null |
		python3 "$ROOT/scripts/github_asset_url.py" \
			--name uv-x86_64-unknown-linux-gnu.tar.gz || true)"
	if [[ -z "$url" ]]; then
		echo "note: could not resolve a uv release; skipped"
		return
	fi
	sha_url="$url.sha256"
	expected="$(curl --fail --location --silent --show-error --max-time 30 "$sha_url" 2>/dev/null |
		awk '{print $1}' | head -n1)"
	if [[ -z "$expected" ]]; then
		echo "ERROR: uv published no SHA-256 for $url; refusing to install it." >&2
		return 1
	fi

	archive="$(mktemp)"
	staging="$(mktemp -d)"
	echo "Installing official uv from $url"
	if ! curl --fail --location --silent --show-error --max-time 300 "$url" -o "$archive"; then
		echo "note: uv download failed; skipped"
		rm -f "$archive"; rm -rf "$staging"
		return
	fi
	actual="$(sha256sum "$archive" | awk '{print $1}')"
	if [[ "$actual" != "$expected" ]]; then
		echo "ERROR: uv checksum mismatch (got $actual, expected $expected)." >&2
		rm -f "$archive"; rm -rf "$staging"
		return 1
	fi
	echo "OK: checksum verified"
	tar -xzf "$archive" -C "$staging"
	mkdir -p "$destination"
	find "$staging" -type f -name uv -perm -u+x -exec install -m 755 {} "$destination/uv" \; -quit
	find "$staging" -type f -name uvx -perm -u+x -exec install -m 755 {} "$destination/uvx" \; -quit
	rm -f "$archive"; rm -rf "$staging"
	if [[ -x "$destination/uv" ]]; then
		echo "OK: installed $destination/uv (ensure it is on PATH)"
	else
		echo "note: uv archive did not contain the expected binary; skipped"
	fi
}

install_uv

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
elif command -v zypper >/dev/null 2>&1; then
	collect_zypper
	((${#PACKAGES[@]})) && $SUDO zypper --non-interactive install "${PACKAGES[@]}"
else
	echo "ERROR: no supported package manager (pacman, apt-get, dnf, zypper) was found." >&2
	echo "       Install the tools listed by 'scripts/install-tools.sh --check' by hand." >&2
	exit 1
fi

install_blender() {
	local series version base url archive staging destination expected actual
	destination="${BLENDER_INSTALL_DIR:-$HOME/.local/share/blender}"
	if have blender; then
		echo "OK: blender is already installed ($(command -v blender))"
		return
	fi
	if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
		echo "note: automatic Blender setup supports Linux x86_64 only; see https://www.blender.org/download/"
		return
	fi
	for required in curl tar xz python3 sha256sum; do
		have "$required" || { echo "note: $required missing; skipped Blender"; return; }
	done

	# Blender's distribution packages lag and some distributions omit them, so
	# fall back to the official build. Track the newest LTS series rather than
	# pinning a version that goes stale, and verify the published SHA-256.
	series="${BLENDER_SERIES:-}"
	if [[ -z "$series" ]]; then
		series="$(curl --fail --location --silent --show-error --max-time 30 \
			https://download.blender.org/release/ 2>/dev/null |
			grep -oE 'Blender[0-9]+\.[0-9]+/' | tr -d '/' | sort -u -V | tail -n1)"
	fi
	if [[ -z "$series" ]]; then
		echo "note: could not resolve a Blender release series; skipped"
		return
	fi
	base="https://download.blender.org/release/$series"
	version="$(curl --fail --location --silent --show-error --max-time 30 "$base/" 2>/dev/null |
		grep -oE 'blender-[0-9]+\.[0-9]+\.[0-9]+-linux-x64\.tar\.xz' |
		sed -E 's/^blender-(.*)-linux-x64\.tar\.xz$/\1/' | sort -u -V | tail -n1)"
	if [[ -z "$version" ]]; then
		echo "note: could not resolve a Blender version in $series; skipped"
		return
	fi

	url="$base/blender-$version-linux-x64.tar.xz"
	expected="$(curl --fail --location --silent --show-error --max-time 30 \
		"$base/blender-$version.sha256" 2>/dev/null |
		awk -v file="blender-$version-linux-x64.tar.xz" '$2 == file {print $1}')"
	if [[ -z "$expected" ]]; then
		echo "ERROR: Blender published no SHA-256 for $version; refusing to install it." >&2
		return 1
	fi

	archive="$(mktemp)"
	staging="$(mktemp -d)"
	echo "Installing official Blender $version (about 400 MB)"
	if ! curl --fail --location --silent --show-error --max-time 900 "$url" -o "$archive"; then
		echo "note: Blender download failed; skipped"
		rm -f "$archive"; rm -rf "$staging"
		return
	fi
	actual="$(sha256sum "$archive" | awk '{print $1}')"
	if [[ "$actual" != "$expected" ]]; then
		echo "ERROR: Blender checksum mismatch (got $actual, expected $expected)." >&2
		rm -f "$archive"; rm -rf "$staging"
		return 1
	fi
	echo "OK: checksum verified"
	tar -xJf "$archive" -C "$staging"
	mkdir -p "$destination" "$HOME/.local/bin"
	rm -rf "${destination:?}/$version"
	mv "$staging/blender-$version-linux-x64" "$destination/$version"
	ln -sf "$destination/$version/blender" "$HOME/.local/bin/blender"
	rm -f "$archive"; rm -rf "$staging"
	echo "OK: installed $destination/$version (linked as ~/.local/bin/blender)"
}

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
		python3 "$ROOT/scripts/github_asset_url.py" --suffix=-linux64.tar.xz || true)"
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
	if [[ ! -f "$ROOT/pyproject.toml" ]]; then
		# Running from the installed package, not a checkout: the extras go
		# into whatever environment owns `shamway`, and the capability
		# registry knows the right command for that environment.
		echo "note: Python capabilities are installed per environment. Run:"
		echo "      shamway capabilities --missing"
		echo "      and use the install command it prints for pillow/numpy/UnityPy/trimesh."
		return
	fi
	if ! have uv; then
		echo "note: uv is unavailable, so the Python capabilities were skipped. Run:"
		echo "      uv sync --project '${target}' --extra all"
		return
	fi
	echo "Installing optional Python capabilities (UnityPy, Pillow, NumPy, trimesh)"
	if [[ -d "$ROOT/.venv" ]]; then
		# The checkout's own venv: resolve from the committed uv.lock so the
		# extras land at the same hash-pinned versions bootstrap installs.
		# --no-dev keeps lint/type tools out of a consumer host.
		if uv sync --project "$ROOT" --no-dev --extra all; then
			echo "OK: installed into $ROOT/.venv"
			return
		fi
	fi
	if uv pip install --quiet --system "${target}[all]" 2>/dev/null; then
		echo "OK: installed into the system environment"
		return
	fi
	echo "note: could not install the Python capabilities automatically. Run:"
	echo "      uv sync --project '${target}' --extra all"
}

install_ilspycmd() {
	# ilspycmd is a dotnet global tool, not a distribution package. It lands in
	# ~/.dotnet/tools, which the user puts on PATH. Never set a global
	# DOTNET_ROOT for it: a distribution .NET upgrade can strand the tool, and
	# the fallback SDK Unity Hub ships (Editor/Data/DotNetSdk) is per-editor.
	if has_ilspycmd; then
		echo "OK: ilspycmd is already installed"
		return
	fi
	if ! has_dotnet_8_sdk; then
		echo "note: no .NET 8 SDK on PATH; skipped ilspycmd. Install the SDK and rerun."
		return
	fi
	echo "Installing ilspycmd as a dotnet global tool"
	if dotnet tool install --global ilspycmd >/dev/null; then
		echo "OK: installed ~/.dotnet/tools/ilspycmd (add ~/.dotnet/tools to PATH)"
	else
		echo "note: dotnet tool install ilspycmd failed; see https://github.com/icsharpcode/ILSpy"
	fi
}

if ((WITH_AUTHORING)); then
	install_blender
	install_gltf_validator
	install_python_extras
fi
if ((WITH_RESEARCH)); then
	install_ilspycmd
fi

echo
echo "Installed base tooling. Current state:"
run_check

# The two things every later step needs. A table line saying MISS is easy to
# scroll past; a non-zero exit is not.
missing=()
has_python_311 || missing+=("python3 >= 3.11")
have uv || [[ -x "$HOME/.local/bin/uv" ]] || missing+=("uv")
if ((${#missing[@]})); then
	echo "ERROR: still missing after install: ${missing[*]}" >&2
	exit 1
fi
cat <<'EOF'

Next:
  scripts/bootstrap                    install the pipeline CLI
  shamway init MOD --game-dir ...  scaffold a modlet
  scripts/install-unity-editor.sh      install the game-matched Unity editor
EOF
