#!/usr/bin/env bash
# Install the exact unityz CLI contract shamway consumes.
set -euo pipefail

# One pinned unityz release. The binaries are the assets unityz's own release
# workflow built from the tagged tree; the source archive is that tag's commit
# (a commit archive, not a tag archive, so GitHub cannot regenerate it under
# the same name). Bump the version, commit, and all three checksums together.
UNITYZ_PINNED_VERSION="0.1.3"
UNITYZ_PINNED_COMMIT="b7ee8db3da36166c45903eea6a2d215a3ff9ef8f"
UNITYZ_PINNED_SOURCE_SHA256="4e58f2ae6f8446ad44823d1b8e6124d38af80a1ac24c9b228a2555e57e2a9e84"
binary_sha256() {
	case "$1" in
		x86_64-linux) echo 511efce6a1b3332e53653e35fb43c26e3acb28e0cc7f095bc62abf909ad1b0db ;;
		aarch64-macos) echo 6c960e5ec18277011824db767b352a2372645a8809142555714adf67ec63f911 ;;
	esac
}

UNITYZ_SOURCE_COMMIT="${UNITYZ_SOURCE_COMMIT:-}"
UNITYZ_FROM_SOURCE="${UNITYZ_FROM_SOURCE:-}"
UNITYZ_INSTALL_PREFIX="${UNITYZ_INSTALL_PREFIX:-$HOME/.local}"

usage() {
	cat <<'HELP'
Install the pinned unityz reader and FSB5 decoder used by shamway.

USAGE
  scripts/install-unityz.sh [--check]

OPTIONS
  --check   Report whether unityz >= 0.1.2 is on PATH; install nothing
  -h        Show this help

On Linux x86_64 and macOS arm64 the installer downloads the pinned unityz
release binary, verifies the SHA-256 recorded in this script, and installs it
into ~/.local/bin; no compiler is needed. Any other platform, or
UNITYZ_FROM_SOURCE=1, downloads the pinned commit's source archive, verifies
its SHA-256, and builds it with Zig 0.16.0 in ReleaseSafe mode instead.
UNITYZ_INSTALL_PREFIX changes the destination. Overriding UNITYZ_SOURCE_COMMIT
also requires the matching UNITYZ_SOURCE_SHA256; an unverified archive is never
installed.
HELP
}

unityz_contract_at() {
	local executable="$1" version major minor patch
	version="$("$executable" --version 2>/dev/null | awk '$1 == "unityz" {print $2; exit}')"
	IFS=. read -r major minor patch <<<"$version"
	[[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ && "$patch" =~ ^[0-9]+$ ]] || return 1
	((major > 0 || (major == 0 && (minor > 1 || (minor == 1 && patch >= 2)))))
}

sha256_file() {
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" | awk '{print $1}'
	elif command -v shasum >/dev/null 2>&1; then
		shasum -a 256 "$1" | awk '{print $1}'
	else
		return 1
	fi
}

installed_unityz() {
	local executable
	executable="$(command -v unityz 2>/dev/null)" || return 1
	unityz_contract_at "$executable"
}

require() {
	local required
	for required in "$@"; do
		if ! command -v "$required" >/dev/null 2>&1; then
			echo "ERROR: $required is required to install unityz." >&2
			exit 1
		fi
	done
}

verify_checksum() {
	local file="$1" expected="$2" actual
	actual="$(sha256_file "$file")"
	if [[ "$actual" != "$expected" ]]; then
		echo "ERROR: checksum mismatch for $(basename "$file")" >&2
		echo "       expected $expected" >&2
		echo "       actual   $actual" >&2
		exit 1
	fi
	echo "OK: checksum verified"
}

# The release target name for this host, or nothing when no binary is
# published for it (the caller then builds from source).
release_target() {
	case "$(uname -s)/$(uname -m)" in
		Linux/x86_64) echo x86_64-linux ;;
		Darwin/arm64) echo aarch64-macos ;;
	esac
}

case "${1:-}" in
	--check)
		if installed_unityz; then
			echo "OK: unityz >= 0.1.2 ($(command -v unityz))"
		else
			echo "MISS: unityz >= 0.1.2"
			exit 1
		fi
		exit 0
		;;
	-h|--help) usage; exit 0 ;;
	"") ;;
	*) echo "ERROR: unknown option $1" >&2; usage >&2; exit 1 ;;
esac

if installed_unityz; then
	echo "OK: unityz already satisfies the >=0.1.2 pipeline contract ($(command -v unityz))"
	exit 0
fi

require curl tar install
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
	echo "ERROR: sha256sum or shasum is required to verify the unityz download." >&2
	exit 1
fi

: "${TMPDIR:=${XDG_CACHE_HOME:-$HOME/.cache}/shamway/tmp}"
mkdir -p "$TMPDIR"
workspace="$(mktemp -d)"
trap 'rm -rf -- "$workspace"' EXIT
destination="$UNITYZ_INSTALL_PREFIX/bin/unityz"
built=""

target="$(release_target)"
if [[ -z "$UNITYZ_FROM_SOURCE" && -z "$UNITYZ_SOURCE_COMMIT" && -n "$target" ]]; then
	name="unityz-$UNITYZ_PINNED_VERSION-$target"
	archive="$workspace/$name.tar.gz"
	echo "Downloading unityz $UNITYZ_PINNED_VERSION release binary for $target"
	curl --fail --location --silent --show-error --retry 3 \
		-o "$archive" \
		"https://github.com/hordeforge/unityz/releases/download/v$UNITYZ_PINNED_VERSION/$name.tar.gz"
	verify_checksum "$archive" "$(binary_sha256 "$target")"
	tar -xzf "$archive" -C "$workspace"
	built="$workspace/$name/unityz"
else
	commit="${UNITYZ_SOURCE_COMMIT:-$UNITYZ_PINNED_COMMIT}"
	expected="${UNITYZ_SOURCE_SHA256:-}"
	if [[ -z "$expected" ]]; then
		if [[ "$commit" != "$UNITYZ_PINNED_COMMIT" ]]; then
			echo "ERROR: no checksum known for unityz commit $commit." >&2
			echo "       Pass UNITYZ_SOURCE_SHA256=<archive sha256>, or leave" >&2
			echo "       UNITYZ_SOURCE_COMMIT at $UNITYZ_PINNED_COMMIT." >&2
			exit 1
		fi
		expected="$UNITYZ_PINNED_SOURCE_SHA256"
	fi
	require zig
	archive="$workspace/unityz-$commit.tar.gz"
	[[ -n "$target" ]] || echo "note: no unityz release binary for $(uname -s)/$(uname -m); building from source"
	echo "Downloading pinned unityz source at $commit"
	curl --fail --location --silent --show-error --retry 3 \
		-o "$archive" \
		"https://github.com/hordeforge/unityz/archive/$commit.tar.gz"
	verify_checksum "$archive" "$expected"
	tar -xzf "$archive" -C "$workspace"
	(
		cd "$workspace/unityz-$commit"
		zig build -Doptimize=ReleaseSafe --prefix "$workspace/install"
	)
	built="$workspace/install/bin/unityz"
fi

mkdir -p "$UNITYZ_INSTALL_PREFIX/bin"
install -m 755 "$built" "$destination"
if ! unityz_contract_at "$destination"; then
	echo "ERROR: $destination does not provide the unityz >=0.1.2 contract" >&2
	exit 1
fi
echo "OK: installed $("$destination" --version) at $destination"
if [[ "$(command -v unityz 2>/dev/null || true)" != "$destination" ]]; then
	echo "    Add it to PATH:  export PATH=\"$UNITYZ_INSTALL_PREFIX/bin:\$PATH\""
fi
