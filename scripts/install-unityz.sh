#!/usr/bin/env bash
# Install the exact unityz reader contract shamway consumes.
set -euo pipefail

UNITYZ_PINNED_COMMIT="8e3925cf08b6f8c7f08e11a1d2fd32dae8a237ce"
UNITYZ_PINNED_SHA256="20545eadcf70f7e8597e7afa7e0af0ec1bcbeb0588020ed5dcfc18b975b5179d"
UNITYZ_SOURCE_COMMIT="${UNITYZ_SOURCE_COMMIT:-$UNITYZ_PINNED_COMMIT}"
UNITYZ_INSTALL_PREFIX="${UNITYZ_INSTALL_PREFIX:-$HOME/.local}"

usage() {
	cat <<'HELP'
Install the pinned unityz reader used by shamway.

USAGE
  scripts/install-unityz.sh [--check]

OPTIONS
  --check   Report whether unityz >= 0.1.1 is on PATH; install nothing
  -h        Show this help

The installer downloads an immutable GitHub source archive, verifies the
SHA-256 recorded in this script, builds with Zig 0.16.0 in ReleaseSafe mode,
and installs the binary into ~/.local/bin. UNITYZ_INSTALL_PREFIX changes that
destination. Overriding UNITYZ_SOURCE_COMMIT also requires the matching
UNITYZ_SOURCE_SHA256; an unverified source archive is never installed.
HELP
}

unityz_contract_at() {
	local executable="$1" version major minor patch
	version="$("$executable" --version 2>/dev/null | awk '$1 == "unityz" {print $2; exit}')"
	IFS=. read -r major minor patch <<<"$version"
	[[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ && "$patch" =~ ^[0-9]+$ ]] || return 1
	((major > 0 || (major == 0 && (minor > 1 || (minor == 1 && patch >= 1)))))
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

case "${1:-}" in
	--check)
		if installed_unityz; then
			echo "OK: unityz >= 0.1.1 ($(command -v unityz))"
		else
			echo "MISS: unityz >= 0.1.1"
			exit 1
		fi
		exit 0
		;;
	-h|--help) usage; exit 0 ;;
	"") ;;
	*) echo "ERROR: unknown option $1" >&2; usage >&2; exit 1 ;;
esac

if installed_unityz; then
	echo "OK: unityz already satisfies the >=0.1.1 metadata contract ($(command -v unityz))"
	exit 0
fi

for required in curl tar zig install; do
	if ! command -v "$required" >/dev/null 2>&1; then
		echo "ERROR: $required is required to build the pinned unityz source." >&2
		exit 1
	fi
done
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
	echo "ERROR: sha256sum or shasum is required to verify the unityz source." >&2
	exit 1
fi

expected="${UNITYZ_SOURCE_SHA256:-}"
if [[ -z "$expected" ]]; then
	if [[ "$UNITYZ_SOURCE_COMMIT" != "$UNITYZ_PINNED_COMMIT" ]]; then
		echo "ERROR: no checksum known for unityz commit $UNITYZ_SOURCE_COMMIT." >&2
		echo "       Pass UNITYZ_SOURCE_SHA256=<archive sha256>, or leave" >&2
		echo "       UNITYZ_SOURCE_COMMIT at $UNITYZ_PINNED_COMMIT." >&2
		exit 1
	fi
	expected="$UNITYZ_PINNED_SHA256"
fi

: "${TMPDIR:=${XDG_CACHE_HOME:-$HOME/.cache}/shamway/tmp}"
mkdir -p "$TMPDIR"
workspace="$(mktemp -d)"
trap 'rm -rf -- "$workspace"' EXIT
archive="$workspace/unityz-$UNITYZ_SOURCE_COMMIT.tar.gz"
source="$workspace/unityz-$UNITYZ_SOURCE_COMMIT"
destination="$UNITYZ_INSTALL_PREFIX/bin/unityz"

echo "Downloading pinned unityz source at $UNITYZ_SOURCE_COMMIT"
curl --fail --location --silent --show-error --retry 3 \
	-o "$archive" \
	"https://github.com/hordeforge/unityz/archive/$UNITYZ_SOURCE_COMMIT.tar.gz"
actual="$(sha256_file "$archive")"
if [[ "$actual" != "$expected" ]]; then
	echo "ERROR: checksum mismatch for unityz-$UNITYZ_SOURCE_COMMIT.tar.gz" >&2
	echo "       expected $expected" >&2
	echo "       actual   $actual" >&2
	exit 1
fi
echo "OK: checksum verified"

tar -xzf "$archive" -C "$workspace"
(
	cd "$source"
	zig build -Doptimize=ReleaseSafe --prefix "$workspace/install"
)
mkdir -p "$UNITYZ_INSTALL_PREFIX/bin"
install -m 755 "$workspace/install/bin/unityz" "$destination"
if ! unityz_contract_at "$destination"; then
	echo "ERROR: $destination does not provide the unityz >=0.1.1 contract" >&2
	exit 1
fi
echo "OK: installed $("$destination" --version) at $destination"
if [[ "$(command -v unityz 2>/dev/null || true)" != "$destination" ]]; then
	echo "    Add it to PATH:  export PATH=\"$UNITYZ_INSTALL_PREFIX/bin:\$PATH\""
fi
