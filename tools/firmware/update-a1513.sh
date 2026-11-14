#!/bin/bash
# Standalone macOS updater. Never invoked by the LG TV installer.
set -euo pipefail
umask 077
tool_dir=$(cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(cd -- "$tool_dir/../.." && pwd)
mode=--check
mode_set=0
archive=
cache_dir="$repo_dir/local/firmware"
logs_dir="$repo_dir/local/firmware/logs"
usage() {
    cat <<'HELP'
Usage: bash tools/firmware/update-a1513.sh [--check | --apply | --verify]
       [--firmware ZIP] [--cache-dir DIR] [--logs-dir DIR]

  --check         Download/validate the pinned firmware, compile and self-test.
                  Default; no device access or administrator privileges.
  --apply         Validate, then use sudo to update Main0241/Radio0107 to
                  Main0257/Radio0120 and reboot the A1513. Real firmware writes.
  --verify        Read the new firmware, battery, HID status and passive input
                  for 40 seconds. No download, sudo or application SET commands.
  --firmware ZIP  Use your own copy of the exact 0x0257 ZIP; no network access.
  --cache-dir DIR Default: repository/local/firmware (ignored by Git).
  --logs-dir DIR  Default: repository/local/firmware/logs (ignored by Git).

Read docs/firmware-update.md before --apply. This is experimental; recovery is
not guaranteed. Only the A1513 firmware combination above has been tested.
A1513 only: no white ring around MENU. A1962 (white MENU ring) is NOT supported.
Check the model number on the back. LG TV app support does not imply updater support.
HELP
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --check|--apply|--verify)
            if [ "$mode_set" -ne 0 ]; then echo 'Choose exactly one mode.' >&2; exit 2; fi
            mode=$1; mode_set=1; shift ;;
        --firmware|--cache-dir|--logs-dir)
            if [ "$#" -lt 2 ] || [ -z "$2" ]; then echo "Missing value for $1" >&2; exit 2; fi
            case "$1" in
                --firmware) archive=$2 ;;
                --cache-dir) cache_dir=$2 ;;
                --logs-dir) logs_dir=$2 ;;
            esac
            shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done
if [ "$mode" = '--verify' ] && [ -n "$archive" ]; then
    echo '--verify does not use firmware files; omit --firmware.' >&2; exit 2
fi
echo 'MODEL NOTICE: A1513 only (no white MENU ring). A1962 (white MENU ring) is NOT supported.'
echo 'Check the model number on the back. Do not bypass model/version checks or use A1513 firmware on A1962.'
if [ "$(uname -s)" != Darwin ]; then echo 'This launcher requires macOS.' >&2; exit 2; fi
if [ "$(id -u)" -eq 0 ]; then
    echo 'Run this launcher as your normal user. --apply requests sudo only after validation.' >&2; exit 2
fi
for required in python3 /usr/bin/swiftc; do
    if ! command -v "$required" >/dev/null 2>&1; then echo "Missing prerequisite: $required" >&2; exit 2; fi
done
python3 -c 'import sys; assert sys.version_info >= (3, 9), "Python 3.9 or newer is required"'
task_tmp=$(mktemp -d /tmp/magic-sirimote-firmware.XXXXXX)
lock_owned=0
lock_dir=
cleanup() {
    rm -rf -- "$task_tmp"
    if [ "$lock_owned" -eq 1 ]; then rmdir "$lock_dir"; fi
}
trap cleanup EXIT

if [ "$mode" != '--verify' ]; then
    prepare_args=(--cache-dir "$cache_dir" --output-dir "$task_tmp/payloads")
    if [ -n "$archive" ]; then prepare_args+=(--firmware "$archive"); fi
    python3 "$tool_dir/firmware.py" "${prepare_args[@]}"
    echo 'Building updater...'
    /usr/bin/swiftc -module-cache-path "$task_tmp/modules" "$tool_dir/UpdateA1513.swift" -o "$task_tmp/updater"
    "$task_tmp/updater" --self-test > "$task_tmp/tests.log"
    tail -n 1 "$task_tmp/tests.log"
    if [ "$mode" = '--check' ]; then echo 'CHECK PASSED. No device access or firmware writes.'; exit 0; fi
else
    echo 'Building post-update verification...'
    /usr/bin/swiftc -module-cache-path "$task_tmp/modules" "$tool_dir/VerifyA1513.swift" -o "$task_tmp/probe" \
        -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$tool_dir/BluetoothInfo.plist"
fi

mkdir -p "$logs_dir"
logs_dir=$(cd -- "$logs_dir" && pwd)
if [ "$mode" = '--verify' ]; then
    output_log=$(mktemp "$logs_dir/verify-a1513.XXXXXX")
    printf 'Log: %s\n' "$output_log"
    set +e
    python3 - "$task_tmp/probe" <<'PY' 2>&1 | tee "$output_log"
import subprocess, sys
try:
    sys.exit(subprocess.run([sys.argv[1]], timeout=65).returncode)
except subprocess.TimeoutExpired:
    print('UNCONFIRMED: observation timed out; no firmware or mode SET was sent.', flush=True)
    sys.exit(124)
PY
    result=${PIPESTATUS[0]}
    set -e
else
    # One lock per checkout, independent of configurable cache/log locations.
    mkdir -p "$repo_dir/local/firmware"
    lock_dir="$repo_dir/local/firmware/update.lock"
    if ! mkdir "$lock_dir"; then
        echo 'STOP: update.lock already exists. Check for an active/interrupted update before removing it.' >&2; exit 3
    fi
    lock_owned=1
    # Both compilation and archive processing above ran as the ordinary user.
    /usr/bin/python3 -c 'import sys; assert sys.version_info >= (3, 9), "System Python 3.9 or newer is required"'
    echo 'This will write firmware and reboot the remote. Keep it charged and connected to the Mac by Bluetooth.'
    echo 'Requesting administrator access for update execution and its timeout supervisor.'
    /usr/bin/sudo -v
    output_log=$(mktemp "$logs_dir/update-a1513.XXXXXX")
    journal="$output_log.json"
    printf 'Log: %s\nJournal: %s\n' "$output_log" "$journal"
    set +e
    /usr/bin/sudo -n /usr/bin/python3 "$tool_dir/supervise.py" "$task_tmp/updater" "$task_tmp/payloads" "$journal" 2>&1 | tee "$output_log"
    result=${PIPESTATUS[0]}
    set -e
fi
printf 'Log saved: %s\n' "$output_log"
exit "$result"
