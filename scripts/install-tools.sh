#!/usr/bin/env bash
# Install the host tooling this pipeline builds and inspects assets with.
#
# Python 3.11+ runs the pipeline and unityz reads, verifies, and extracts the
# Unity artifacts it handles. vkd3d-compiler is what the default editorless
# build path needs to write a prefab's shader. A Unity editor is opt-in and is
# installed by scripts/install-unity-editor.sh, not here. Everything else
# supports the authoring lanes in docs/authoring/authoring-tools.md and is
# opt-in too, so a build host never installs desktop art packages it has no use
# for.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Every mktemp below follows TMPDIR, and the default /tmp is tmpfs on most
# Linux hosts: the release tarballs and the vkd3d source build staged here run
# to hundreds of megabytes, which that default charges against RAM. Keep them
# on disk unless the caller already chose somewhere.
: "${TMPDIR:=${XDG_CACHE_HOME:-$HOME/.cache}/shamway/tmp}"
mkdir -p "$TMPDIR"
export TMPDIR

WITH_AUTHORING=0
WITH_UNITY_PREREQS=0
WITH_RESEARCH=0
WITH_DESKTOP_CAPTURE=0
WITH_VKD3D_SOURCE=0
WITH_EXTRAS=0
CHECK_ONLY=0
# Pinned rather than tracking master: this is what the shader lane was measured
# against, and a compiler that changes under a build changes the bytes it emits.
VKD3D_SOURCE_VERSION="${VKD3D_SOURCE_VERSION:-1.19}"
VKD3D_SOURCE_PREFIX="${VKD3D_SOURCE_PREFIX:-/opt/vkd3d}"
# The release tarball, not a git clone: a clone needs Wine's `widl` to generate
# vkd3d_d3dx9shader.h and friends, while the tarball ships them pre-generated
# along with `configure`. Measured - a clone build fails at
# `libs/vkd3d-shader/hlsl.h:25: vkd3d_d3dx9shader.h: No such file or directory`,
# and the tarball builds with a C toolchain and Khronos headers alone.
VKD3D_PINNED_VERSION="1.19"
VKD3D_PINNED_SHA256="034613605baab8ba84674f8d272cf22b5e86bc6bc03fc5728ef9bce07308baa6"
# Pinned rather than tracking master, like vkd3d above: the SMOL-V bytes a
# codec emits are what the live Vulkan client was measured against. The commit
# hash is its own checksum; bump it deliberately, with a re-measured client.
ZMOLV_REPO="${ZMOLV_REPO:-https://github.com/ywy50/zmol-v}"
ZMOLV_PINNED_COMMIT="${ZMOLV_PINNED_COMMIT:-9cf87314bb7ac27c4aaa09ce33e960052e13d857}"

usage() {
	cat <<'HELP'
Install host tooling for the 7DTD asset pipeline.

USAGE
  scripts/install-tools.sh [options]

OPTIONS
  --with-authoring       Also install the optional asset-authoring tools
                         (Blender, OpenSCAD, ImageMagick, FFmpeg, Xvfb)
  --with-unity-prereqs   Also install what the OPTIONAL scripts/install-unity-editor.sh
                         needs (curl, tar, libarchive, flatpak, libxml2.so.2).
                         Only a mod that sets bundle_source = "unity" needs it
  --with-research        Also install the decompilers that engine facts must
                         cite (.NET 8 SDK + ilspycmd, Mono's monodis)
  --with-desktop-capture Also install a screenshot tool, so the human visual
                         sign-off leaves a citable frame (grim, maim)
  --with-vkd3d-source    Build vkd3d-compiler from source into /opt/vkd3d when
                         this host has no packaged one that reads HLSL. Needed
                         on Debian and Ubuntu, which package vkd3d 1.2; a no-op
                         where the distribution already ships 1.3 or newer
  --all                 Install the full suite in one flag: --with-authoring,
                        --with-research, --with-extras, --with-desktop-capture,
                        --with-unity-prereqs and --with-vkd3d-source together
  --check                Report what is present or missing and install nothing
  -h, --help             Show this help

BASE TOOLS
  python3 (>=3.11)   The pipeline CLI and its TOML configuration parser
  uv                 The Python toolchain: environments, installs, and runs
  git, make          Version control and the consumer Makefile targets
  shellcheck         Lints this repository's scripts in 'make check'
  pactl              Mutes and unmutes a test client (shamway client mute)
  unityz (>=0.1.1)   Reads, verifies, and extracts Unity bundles and assets.
                     Built from a pinned, checksum-verified source archive
                     into ~/.local/bin because no release artifact exists yet
  vkd3d-compiler     HLSL to DXBC: the shader a synthesized prefab's material
                     needs. Requires vkd3d >= 1.3, which is when vkd3d-shader
                     learned to read HLSL. Debian and Ubuntu package 1.2, so
                     this script does not install theirs -- see NOTES below.
                     Without a usable one a mesh is packed as a bare Mesh and
                     'shamway build' prints a note saying so

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

WITH --with-extras
  Optional reference/lane tools from docs/authoring/authoring-tools.md, not
  wired to any command. Installed (downloaded) where a Linux release exists:
  gltfpack           meshoptimizer's mesh optimizer (quantize + vertex-cache
                     order before import)
  compressonatorcli  GPUOpen command-line BC1-7/ATC compressor for measuring
                     what block compression would save a texture/clip set
  AssetRipper        export a vanilla prefab/material/graph set for reference
                     reading (read-only against the install)
  Reported (not auto-installed): fsb5 (the Python 'audio' extra already provides
  it) and bc7enc_rdo (a source build; see authoring-tools.md).

NOTES
  vkd3d differs by distribution, and only the version matters
    The shader lane needs vkd3d >= 1.3, which is when vkd3d-shader learned to
    read HLSL. Where the distribution packages one that new, this script
    installs it with no flag:

      Arch      vkd3d             1.19   works
      Fedora    vkd3d-compiler    1.17   works
      openSUSE  vkd3d             Factory, probed rather than assumed
      Debian    vkd3d-compiler    1.2    too old
      Ubuntu    vkd3d-compiler    1.2    too old

    Debian's and Ubuntu's are deliberately NOT installed: a binary on PATH that
    cannot compile the shader is worse than none, because it looks like the lane
    is available. On those two, build one:

      scripts/install-tools.sh --with-vkd3d-source

    That downloads WineHQ's release tarball for the pinned version, verifies its
    SHA-256 against a digest recorded in this script, builds vkd3d-compiler,
    installs it under /opt/vkd3d, and tells you the one line to add to PATH.
    The tarball rather than a git clone on purpose: a clone needs Wine's widl to
    generate headers, and the tarball ships them. Override the location with
    VKD3D_SOURCE_PREFIX; overriding VKD3D_SOURCE_VERSION also needs
    VKD3D_SOURCE_SHA256, because this script does not install a download it
    cannot verify. It is a no-op on a host that already has a usable compiler,
    so it is safe to pass on any distribution.

    Without a usable compiler nothing breaks: a mesh is packed as a bare Mesh
    and 'shamway build' prints a note saying which it wrote.

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
		--with-vkd3d-source) WITH_VKD3D_SOURCE=1; shift ;;
		--with-extras) WITH_EXTRAS=1; shift ;;
		--all)
			WITH_AUTHORING=1; WITH_RESEARCH=1; WITH_EXTRAS=1
			WITH_DESKTOP_CAPTURE=1; WITH_UNITY_PREREQS=1; WITH_VKD3D_SOURCE=1
			shift ;;
		--check) CHECK_ONLY=1; shift ;;
		-h|--help) usage; exit 0 ;;
		*) echo "ERROR: unknown option $1" >&2; usage >&2; exit 1 ;;
	esac
done

# The version comes from the interpreter's own --version line rather than an
# embedded program, so this file stays one language. sort -V decides the
# comparison, which is what handles 3.10 < 3.9 correctly.
has_python_311() {
	local version
	command -v python3 >/dev/null 2>&1 || return 1
	version="$(python3 --version 2>&1 | awk '{print $2}')"
	[[ -n "$version" ]] || return 1
	[[ "$(printf '%s\n3.11\n' "$version" | sort -V | head -n1)" == "3.11" ]]
}

# The optional Python capabilities, probed by a sibling script for the reason
# the JSON selection is one: this file stays shell. install_python_extras puts
# them in the checkout's .venv (`uv sync --extra all`), so probe that python
# when this is a checkout with a .venv — probing the system interpreter reports
# the extras as MISS even after a successful install.
has_module() {
	local py=python3
	if [[ -x "$ROOT/.venv/bin/python" ]]; then py="$ROOT/.venv/bin/python"; fi
	"$py" "$ROOT/scripts/have_module.py" "$@"
}

# Presence is not capability: vkd3d-shader grew HLSL support in 1.3, and Debian
# and Ubuntu both still package 1.2. Ask the binary what it reads rather than
# comparing versions — it is the same question the writer will ask, and a host
# whose answer is "no hlsl" would otherwise be told everything is fine and then
# fail in the middle of a build.
has_vkd3d_hlsl() {
	command -v vkd3d-compiler >/dev/null 2>&1 &&
		vkd3d-compiler --print-source-types 2>/dev/null | grep -q hlsl
}

has_unityz_contract() {
	"$ROOT/scripts/install-unityz.sh" --check
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
	report unityz "Unity asset inspection and verification; needs unityz >= 0.1.1" \
		has_unityz_contract
	report vkd3d-compiler "HLSL to DXBC (synthesized shaders and materials); needs vkd3d >= 1.3" \
		has_vkd3d_hlsl
	if ((WITH_AUTHORING)); then
		report blender "mesh authoring" have blender
		report openscad "parametric geometry" have openscad
		report magick "icons and textures" have magick
		report ffmpeg "audio" have ffmpeg
		report xvfb-run "icon rendering on a headless host" have xvfb-run
		report gltf_validator "glTF conformance" have gltf_validator
		report UnityPy "synthesized-writer type trees and serialization" has_module UnityPy
		report Pillow "icon and texture lanes" has_module PIL
		report NumPy "texture lane" has_module numpy
		report trimesh "mesh checks" has_module trimesh
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
	if ((WITH_EXTRAS)); then
		report gltfpack "meshop optimizer (mesh lane)" have gltfpack
		report compressonatorcli "BC1-7 compressor (texture lane)" have compressonatorcli
		report AssetRipper "vanilla export for reference" have assetripper
		report fsb5 "decode an FSB5 bank (Python audio extra)" has_module fsb5
		report bc7enc_rdo "BC7 encoder (source build)" have bc7enc_rdo
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
	have curl || PACKAGES+=(curl)
	have tar || PACKAGES+=(tar)
	# Arch ships /usr/bin/vkd3d-compiler in `vkd3d` (verified with pacman -Qo),
	# currently 1.19, which reads HLSL.
	has_vkd3d_hlsl || PACKAGES+=(vkd3d)
	# Arch ships /usr/bin/glslangValidator in `glslang` (verified with
	# pacman -Qo, currently 1.4.357.0). It compiles the OpenGLCore
	# sub-program's GLSL offline, which the runtime will not explain.
	have glslangValidator || PACKAGES+=(glslang)
	# Zig builds the SMOL-V codec (zmol-v) the Vulkan shader lane loads.
	have zig || PACKAGES+=(zig)
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
	have curl || PACKAGES+=(curl)
	have tar || PACKAGES+=(tar)
	# Debian and Ubuntu ship glslangValidator in `glslang-tools`.
	have glslangValidator || PACKAGES+=(glslang-tools)
	# Zig builds the SMOL-V codec (zmol-v) the Vulkan shader lane loads.
	have zig || PACKAGES+=(zig)
	# Deliberately not installed here. Debian and Ubuntu package vkd3d 1.2
	# (measured: Ubuntu noble ships vkd3d-compiler 1.2-15build1), which
	# predates the HLSL support this writer needs, so `apt install
	# vkd3d-compiler` puts a binary on PATH that cannot do the job. `--check`
	# reports it as MISS with the reason, and the shader lane degrades with a
	# printed note rather than failing. --with-vkd3d-source builds a usable
	# one; see the NOTES section of --help.
	:
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
	have curl || PACKAGES+=(curl)
	have tar || PACKAGES+=(tar)
	# Fedora names the binary's package after the binary, and ships 1.17 in
	# Rawhide, which is new enough to read HLSL.
	has_vkd3d_hlsl || PACKAGES+=(vkd3d-compiler)
	# Ships glslangValidator in `glslang`. Not verified on this host:
	# only the Arch name was checked, with pacman -Qo.
	have glslangValidator || PACKAGES+=(glslang)
	# Zig builds the SMOL-V codec (zmol-v) the Vulkan shader lane loads.
	have zig || PACKAGES+=(zig)
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
	have curl || PACKAGES+=(curl)
	have tar || PACKAGES+=(tar)
	# openSUSE Factory carries `vkd3d`. If this host ends up without a binary
	# that reads HLSL anyway, --check says MISS with the reason and the build
	# degrades with a printed note rather than failing.
	has_vkd3d_hlsl || PACKAGES+=(vkd3d)
	# Ships glslangValidator in `glslang`. Not verified on this host:
	# only the Arch name was checked, with pacman -Qo.
	have glslangValidator || PACKAGES+=(glslang)
	# Zig builds the SMOL-V codec (zmol-v) the Vulkan shader lane loads.
	have zig || PACKAGES+=(zig)
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

# Every distribution reaches a usable shader lane by one of two routes: its own
# package where that is >= 1.3, and this build where it is not. Kept in the same
# script so "how do I get the shader lane" has one answer everywhere.
build_vkd3d_from_source() {
	local version="$VKD3D_SOURCE_VERSION" prefix="$VKD3D_SOURCE_PREFIX"
	local workspace url archive expected actual
	if has_vkd3d_hlsl; then
		echo "OK: vkd3d-compiler already reads HLSL ($(command -v vkd3d-compiler)); nothing to build"
		return
	fi
	# WineHQ publishes a GPG .sign beside each tarball but no checksum file, so
	# the digest is pinned here. An overridden version has no pin, and this
	# script does not install unverified downloads - the same rule
	# install-unity-editor.sh follows.
	expected="${VKD3D_SOURCE_SHA256:-}"
	if [[ -z "$expected" ]]; then
		if [[ "$version" != "$VKD3D_PINNED_VERSION" ]]; then
			echo "ERROR: no checksum known for vkd3d $version." >&2
			echo "       Pass VKD3D_SOURCE_SHA256=<sha256 of vkd3d-$version.tar.xz>," >&2
			echo "       or leave VKD3D_SOURCE_VERSION at $VKD3D_PINNED_VERSION." >&2
			return 1
		fi
		expected="$VKD3D_PINNED_SHA256"
	fi
	case "$(uname -s)" in
		Linux) ;;
		*)
			echo "ERROR: this source build is scripted for Linux only." >&2
			echo "       Build vkd3d $version from https://gitlab.winehq.org/wine/vkd3d" >&2
			return 1
			;;
	esac
	local build_deps=()
	if command -v pacman >/dev/null 2>&1; then
		build_deps=(base-devel flex bison vulkan-headers spirv-headers)
		$SUDO pacman -S --needed --noconfirm "${build_deps[@]}"
	elif command -v apt-get >/dev/null 2>&1; then
		build_deps=(build-essential pkg-config flex bison libvulkan-dev spirv-headers xz-utils curl)
		$SUDO apt-get update
		$SUDO apt-get install -y "${build_deps[@]}"
	elif command -v dnf >/dev/null 2>&1; then
		build_deps=(gcc make pkgconf flex bison vulkan-headers spirv-headers xz curl)
		$SUDO dnf install -y "${build_deps[@]}"
	elif command -v zypper >/dev/null 2>&1; then
		build_deps=(gcc make pkg-config flex bison vulkan-headers spirv-headers xz curl)
		$SUDO zypper --non-interactive install "${build_deps[@]}"
	else
		echo "ERROR: cannot install build dependencies on this package manager." >&2
		echo "       Install a C toolchain, flex, bison, and the Vulkan and SPIRV" >&2
		echo "       headers, then build vkd3d $version from" >&2
		echo "       https://gitlab.winehq.org/wine/vkd3d" >&2
		return 1
	fi
	workspace="$(mktemp -d)"
	# Removed on every exit, including a failed configure: a half-built tree
	# under /tmp is the kind of thing a later run silently reuses.
	trap 'rm -rf "$workspace"' RETURN
	url="https://dl.winehq.org/vkd3d/source/vkd3d-$version.tar.xz"
	archive="$workspace/vkd3d-$version.tar.xz"
	echo "Downloading $url"
	curl -fsSL --retry 3 -o "$archive" "$url"
	actual="$(sha256sum "$archive" | cut -d' ' -f1)"
	if [[ "$actual" != "$expected" ]]; then
		echo "ERROR: checksum mismatch for vkd3d-$version.tar.xz" >&2
		echo "       expected $expected" >&2
		echo "       actual   $actual" >&2
		return 1
	fi
	echo "OK: checksum verified"
	tar xJf "$archive" -C "$workspace"
	(
		cd "$workspace/vkd3d-$version"
		./configure --prefix="$prefix" --disable-tests --disable-demos
		make -j"$(nproc 2>/dev/null || echo 2)"
		$SUDO make install
	)
	if [[ -x "$prefix/bin/vkd3d-compiler" ]]; then
		echo "OK: built vkd3d $version at $prefix/bin/vkd3d-compiler"
		echo "    Add it to PATH:  export PATH=\"$prefix/bin:\$PATH\""
	else
		echo "ERROR: the build finished but $prefix/bin/vkd3d-compiler is not there" >&2
		return 1
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

# Download a Linux x86_64 GitHub release asset, extract it, and install the
# named executable to ~/.local/bin. These §7 tools (docs/authoring/authoring-tools.md)
# have no distribution package on the supported managers, so they are fetched
# the way gltf_validator is. bc7enc_rdo and fsb5 are not fetched here: the
# first is a source build and the second is the Python 'audio' extra.
install_binary_release() {
	local tool="$1" repo="$2" suffix="$3" binary="$4"
	local url archive staging dest found
	dest="${HOME}/.local/bin"
	if have "$tool"; then
		echo "OK: $tool is already installed ($(command -v "$tool"))"
		return
	fi
	if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
		echo "note: automatic $tool setup supports Linux x86_64 only; see $repo"
		return
	fi
	for required in curl tar python3 unzip; do
		have "$required" || { echo "note: $required missing; skipped $tool"; return; }
	done
	url="$(curl --fail --location --silent --show-error --max-time 30 \
		"https://api.github.com/repos/$repo/releases/latest" 2>/dev/null |
		python3 "$ROOT/scripts/github_asset_url.py" --suffix="$suffix" || true)"
	if [[ -z "$url" ]]; then
		echo "note: could not resolve a $tool release; skipped"
		return
	fi
	archive="$(mktemp)"
	staging="$(mktemp -d)"
	echo "Installing $tool from $url"
	if curl --fail --location --silent --show-error --max-time 180 "$url" -o "$archive"; then
		case "$suffix" in
			*.zip) unzip -q "$archive" -d "$staging" ;;
			*.tar.gz) tar -xzf "$archive" -C "$staging" ;;
			*.tar.xz) tar -xJf "$archive" -C "$staging" ;;
		esac
		found="$(find "$staging" -type f -name "$binary" -perm -u+x 2>/dev/null | head -n1)"
		if [[ -n "$found" ]]; then
			mkdir -p "$dest"
			install -m 755 "$found" "$dest/$tool"
			echo "OK: installed $dest/$tool"
		else
			echo "note: $tool release extracted but no '$binary' executable found; skipped"
		fi
	else
		echo "note: $tool download failed; skipped"
	fi
	rm -f "$archive"
	rm -rf "$staging"
}

# AssetRipper ships as a GUI whose executable needs its sibling libcapstone.so,
# so it cannot be installed as a lone binary the way gltfpack / compressonatorcli
# can. Install the whole extracted directory and symlink the executable.
install_assetripper() {
	local url archive staging dest bin
	dest="${HOME}/.local/opt/assetripper"
	if have assetripper; then
		echo "OK: AssetRipper is already installed ($(command -v assetripper))"
		return
	fi
	if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
		echo "note: automatic AssetRipper setup supports Linux x86_64 only;"
		echo "      see https://github.com/AssetRipper/AssetRipper"
		return
	fi
	for required in curl tar python3; do
		have "$required" || { echo "note: $required missing; skipped AssetRipper"; return; }
	done
	url="$(curl --fail --location --silent --show-error --max-time 30 \
		"https://api.github.com/repos/AssetRipper/AssetRipper/releases/latest" 2>/dev/null |
		python3 "$ROOT/scripts/github_asset_url.py" --suffix="_linux_x64.tar.xz" || true)"
	if [[ -z "$url" ]]; then
		echo "note: could not resolve an AssetRipper release; skipped"
		return
	fi
	archive="$(mktemp)"
	staging="$(mktemp -d)"
	echo "Installing AssetRipper from $url"
	if curl --fail --location --silent --show-error --max-time 180 "$url" -o "$archive" &&
		tar -xJf "$archive" -C "$staging" &&
		bin="$(find "$staging" -maxdepth 2 -type f -name 'AssetRipper*' -perm -u+x 2>/dev/null | head -n1)" &&
		[[ -n "$bin" ]]; then
		rm -rf "$dest"
		mkdir -p "$dest" "$HOME/.local/bin"
		cp -a "$staging"/. "$dest/"
		ln -sf "$dest/$(basename "$bin")" "$HOME/.local/bin/assetripper"
		echo "OK: installed $dest (launcher ~/.local/bin/assetripper)"
	else
		echo "note: AssetRipper download or extraction failed; skipped"
	fi
	rm -f "$archive"
	rm -rf "$staging"
}

install_extras() {
	# gltfpack's Linux asset is a manylinux zip; compressonatorcli is a tar.gz.
	install_binary_release gltfpack "zeux/meshoptimizer" "-ubuntu.zip" "gltfpack"
	install_binary_release compressonatorcli "GPUOpen-Tools/compressonator" "-Linux.tar.gz" "compressonatorcli"
	install_assetripper
	echo "note: bc7enc_rdo is a source build (see docs/authoring/authoring-tools.md);"
	echo "      fsb5 comes from the Python 'audio' extra (shamway capabilities --missing)."
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
		echo "      Use its install command for each missing Python capability:"
		echo "      UnityPy writer support, Pillow, NumPy, and trimesh."
		return
	fi
	if ! have uv; then
		echo "note: uv is unavailable, so the Python capabilities were skipped. Run:"
		echo "      uv sync --project '${target}' --extra all"
		return
	fi
	echo "Installing optional Python capabilities:"
	echo "  UnityPy writer support, Pillow, NumPy, trimesh"
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


install_zmolv() {
	# The SMOL-V codec the Vulkan shader lane loads (shader_blob.smolv_library).
	# Installed into this checkout's gitignored .local/lib, which that search
	# treats as a default; ZMOLV_LIBRARY still overrides. Without the library
	# a synthesized shader carries no Vulkan sub-program and a -force-vulkan
	# client draws it magenta - and that degradation was once silent.
	# Zig names the artifact per host (.so / .dylib / .dll); copy whichever
	# one the build produced rather than assuming Linux.
	local root lib clone built dest
	root="$(cd "$(dirname "$0")/.." && pwd)"
	for lib in "$root/.local/lib"/libzmolv.so "$root/.local/lib"/libzmolv.dylib \
		"$root/.local/lib"/zmolv.dll "$root/.local/lib"/libzmolv.dll; do
		if [[ -f "$lib" ]]; then
			echo "OK: libzmolv is already installed ($lib)"
			return
		fi
	done
	if ! have zig || ! have git; then
		echo "note: zig or git missing; skipped libzmolv (the shader's Vulkan lane stays off)"
		return
	fi
	clone="$(mktemp -d)"
	echo "Building zmol-v ($ZMOLV_PINNED_COMMIT) for the Vulkan shader lane"
	if git clone --quiet "$ZMOLV_REPO" "$clone/zmol-v" &&
		git -C "$clone/zmol-v" checkout --quiet "$ZMOLV_PINNED_COMMIT" &&
		(cd "$clone/zmol-v" && zig build -Doptimize=ReleaseFast); then
		built=""
		for lib in "$clone/zmol-v/zig-out/lib"/libzmolv.so \
			"$clone/zmol-v/zig-out/lib"/libzmolv.dylib \
			"$clone/zmol-v/zig-out/lib"/zmolv.dll \
			"$clone/zmol-v/zig-out/lib"/libzmolv.dll; do
			if [[ -f "$lib" ]]; then
				built="$lib"
				break
			fi
		done
		if [[ -n "$built" ]]; then
			mkdir -p "$root/.local/lib"
			dest="$root/.local/lib/$(basename -- "$built")"
			cp "$built" "$dest"
			echo "OK: installed $dest"
		else
			echo "note: zmol-v built but produced no shared library; skipped libzmolv"
		fi
	else
		echo "note: zmol-v build failed; skipped libzmolv (the shader's Vulkan lane stays off)"
	fi
	rm -rf "$clone"
}

"$ROOT/scripts/install-unityz.sh"
export PATH="${UNITYZ_INSTALL_PREFIX:-$HOME/.local}/bin:$PATH"
install_zmolv

if ((WITH_AUTHORING)); then
	install_blender
	install_gltf_validator
	install_python_extras
fi
if ((WITH_RESEARCH)); then
	install_ilspycmd
fi
if ((WITH_EXTRAS)); then
	install_extras
fi
if ((WITH_VKD3D_SOURCE)); then
	build_vkd3d_from_source
fi

echo
echo "Installed base tooling. Current state:"
run_check

# The two things every later step needs. A table line saying MISS is easy to
# scroll past; a non-zero exit is not.
missing=()
has_python_311 || missing+=("python3 >= 3.11")
have uv || [[ -x "$HOME/.local/bin/uv" ]] || missing+=("uv")
has_unityz_contract || missing+=("unityz >= 0.1.1")
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
