#!/bin/sh
# Run from a source checkout, or download this file and run: sh install.sh
set -eu

fail() { printf '\n%s\n' "$*" >&2; exit 1; }
if ! command -v node >/dev/null 2>&1; then
    fail 'Node.js is missing. Install the LTS version (with npm) from https://nodejs.org/en/download, reopen Terminal, then run this installer again.'
fi
node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' ||
    fail 'Node.js 20 or newer is required by the webOS tools. Install the current LTS version from https://nodejs.org/en/download, reopen Terminal, and try again.'
if ! command -v npm >/dev/null 2>&1; then
    fail 'npm is missing. Reinstall Node.js LTS with npm from https://nodejs.org/en/download, then reopen Terminal.'
fi
for tool in curl tar mktemp; do
    command -v "$tool" >/dev/null 2>&1 || fail "Missing tool: $tool. On macOS these tools are built in; check your PATH. On Linux, install $tool with your package manager."
done

script_dir=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
if [ -f "$script_dir/tools/installer/main.js" ] && [ -f "$script_dir/releases/manifest.json" ]; then
    exec node "$script_dir/tools/installer/main.js" "$@"
fi

# One archive keeps scripts, the IPK, and checksums on the same revision.
installer_tmp=$(mktemp -d "${TMPDIR:-/tmp}/magic-sirimote-install.XXXXXX")
trap 'rm -rf "$installer_tmp"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
printf '%s\n' 'Downloading Magic Sirimote...'
curl --fail --location --retry 2 --connect-timeout 15 --max-time 180 \
    --output "$installer_tmp/source.tar.gz" \
    https://github.com/super-dog-human/magic-sirimote/archive/refs/heads/main.tar.gz ||
    fail 'Download failed. Check your internet connection, then run the installer again.'
tar -xzf "$installer_tmp/source.tar.gz" -C "$installer_tmp" || fail 'The download could not be unpacked. Run the installer again.'
[ -f "$installer_tmp/magic-sirimote-main/tools/installer/main.js" ] || fail 'The downloaded installer is incomplete.'
node "$installer_tmp/magic-sirimote-main/tools/installer/main.js" "$@"
