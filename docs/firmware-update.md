# Experimental A1513 firmware update from macOS

This optional, standalone tool updates a first-generation Siri Remote **A1513**
from Main `0x0241` / Radio `0x0107` to Main `0x0257` / Radio `0x0120`.
It is not part of the LG TV installer and is not required to install Magic Sirimote.
It does not support A1962 or other remote generations, arbitrary starting versions,
downgrades, or automatic discovery of newer firmware.

> **Check the model before proceeding:** A1513 has no white ring around the MENU
> button. The black remote with a white ring around MENU is **A1962**, which this
> updater does **not** support. Confirm the model number on the back of the remote.
> A1962 firmware updating has not been validated here; this does not establish that
> updating it from a Mac is impossible. Do not bypass the model/version checks or
> use A1513 firmware on A1962. Magic Sirimote's LG TV support is separate from this
> updater's model support.

**This writes real firmware and reboots the remote. Recovery is not guaranteed.**
The transfer was successfully tested on one A1513 on 2026-11-14, using a Mac mini
M4 Pro running macOS 27.2.1 (26B131). Other macOS versions and remotes have not been
validated. This is an independent experimental tool, not an Apple-supported updater.

## What changes

Versions below are hexadecimal component versions, not decimal release numbers.
The updater requires the entire starting revision to match, including unchanged
components. An exact match for the target revision exits without firmware writes.

| Component | Before | After | Written by this tool |
| --- | --- | --- | --- |
| Main application | `0241` | `0257` | Yes |
| Radio application | `0107` | `0120` | Yes |
| Bootloader | `0241` | `0241` | No |
| Touch | `0370` | `0370` | No |
| Radio diagnostics | `0018` | `0018` | No |
| Audio | `0815` | `0815` | No |

Expected complete target revision:

```text
01005702200070033000200131001800B000410240001508
```

## Requirements and connection

- macOS with Xcode Command Line Tools (`swiftc`, Swift 5.7 or newer).
- Python 3.9 or newer as `python3`, and `/usr/bin/python3` 3.9 or newer for the
  administrator-run supervisor. No additional Python packages are needed.
- A normal user account that can use `sudo` for the update.
- One A1513 connected to the Mac over Bluetooth. Keep its charging cable connected
  and keep the Mac awake for the update. Do not run another remote configuration
  tool or another updater at the same time.

Unlike normal Magic Sirimote installation, **this procedure needs the remote paired
with the Mac**. Put it in pairing mode with MENU + Volume Up for about five seconds,
then connect it in macOS Bluetooth settings. Its TV connection is unavailable while
it is connected to the Mac. Afterward, pair it with the TV again using Magic
Sirimote's normal pairing procedure as needed.

Firmware transfer uses Bluetooth HID. The Lightning cable supplies charging power;
this procedure does not use a USB firmware transport. An Apple TV and the webOS CLI
are not required. These scripts do not connect to or modify the LG TV.

## Download and check, without accessing the remote

Run these commands from the repository root:

```sh
bash tools/firmware/update-a1513.sh --check
```

This downloads the one tested firmware ZIP directly from Apple over HTTPS,
validates it, compiles the updater, and runs simulated transfer/failure tests.
It does not open the remote or request administrator access. `--check` is also
the default when no mode is supplied.

The verified ZIP is cached at `local/firmware/a1513-0257.zip`. The repository's
`local/` directory is ignored by Git. Firmware archives, extracted firmware,
device logs, and private pairing data are not distributed in this repository.
Only the `0x0257` ZIP is needed; the older archive used during protocol analysis
is not needed to run the updater.

### Manual or offline firmware

Automatic download is the default, with a manual alternative if Apple's URL is
unavailable or you already have the archive:

```sh
bash tools/firmware/update-a1513.sh --check --firmware "/path/to/firmware.zip"
bash tools/firmware/update-a1513.sh --apply --firmware "/path/to/firmware.zip"
```

`--firmware` performs no network access and does not change the supplied ZIP.
The filename can differ, but its bytes must match exactly. A repacked ZIP or
another version is rejected. A cached ZIP is also checked on every run; an invalid
cache entry stops the operation instead of silently being replaced.

Apple archive: [faab68bc0c5b473c11e836677f9ae189e0aced51.zip](https://updates.cdn-apple.com/2019/ios/041-44746-201908730-71130D66-AFC7-11E9-83A5-4D41F70D717D/com_apple_MobileAsset_MobileAccessoryUpdate_WirelessRemoteFirmware/faab68bc0c5b473c11e836677f9ae189e0aced51.zip)

Size: **238,607 bytes**. SHA-256:

```text
d744170c7a26686687af184d3dc1dd5c03f15240f7d455633c2a40f64465d168
```

There is no HTTP fallback, third-party mirror, or fallback to a different release.
`--cache-dir DIR` and `--logs-dir DIR` override the default storage directories;
keep custom directories out of version control as well.

## Apply the update

```sh
bash tools/firmware/update-a1513.sh --apply
```

Run the launcher as your ordinary user, not with `sudo bash`. It validates and
compiles first, then requests your **Mac administrator password** using `sudo`.
Only firmware execution and its timeout supervisor run as administrator.

Administrator access is necessary on the tested macOS: the initial non-admin OTA
begin request was rejected by the kernel with `b0/02 blocked due to lack of privileges`
and `0xe00002c1`. Ordinary sensor-mode access alone did not demonstrate OTA write
permission. The successful attempt required no SIP changes, special entitlement,
or driver installation.

The updater transfers Main and Radio, requires the remote to report signature
verification success for each, arms activation, and requests a reboot. It then
waits up to 120 seconds for the **same remote** to report the exact target revision.
Success ends with:

```text
PHASE: new-version-reported
PASS: the same remote reports Main0257/Radio0120/Boot0241. Confirm normal operation separately.
```

The execution supervisor has a 15-minute limit. Logs and a JSON phase journal are
written under `local/firmware/logs/`; the printed paths identify each attempt.
The launcher blocks simultaneous updates from the same checkout, but this is not
a system-wide lock across separate copies of the repository.

**If the update stops or reports UNCONFIRMED, retain both files and investigate
before another write attempt.** There is no automatic retry, resume, rollback,
or recovery. In particular, a failure after `arm-pending` may leave activation
pending or may occur after activation; do not assume that a failure means nothing
was written. A stale `update.lock` should only be removed after establishing that
no updater is still running and reviewing the interrupted attempt.

## Verify after the update

```sh
bash tools/firmware/update-a1513.sh --verify
```

Allow Bluetooth and Input Monitoring access if macOS requests them. During the
40-second observation, swipe the touch surface and press ordinary buttons one at
a time. Do not hold pairing or reset combinations.

The verification tool does not download firmware, request `sudo`, send application
SET commands, change sensor mode, unpair, or reset the remote. It checks:

- All eight HID interfaces and their reported target firmware revision.
- Three direct GATT firmware reads from the same remote, hardware/PnP identity,
  and available battery characteristics.
- Native A0 sensor-mode and B2 OTA-status reads before and after observation.
- Passive input event receipt, callback errors, and BLE disconnections.

An observation with no received input events is reported as unconfirmed, even if
firmware verification passes. Retry the read-only verification after checking
permissions and operating the remote; this does not require reflashing.

The tested remote reported the target firmware on all three direct reads, 99%
battery, A0/B2 both `00`, 78 input value callbacks, zero callback errors, and zero
BLE disconnections. This supports successful installation and basic communication.
It does **not** validate every button, touch coordinates, gyro accuracy, infrared,
microphone, battery capacity, or long-term stability. LG TV pointer behavior was
not covered by this check, and this update is not a demonstrated fix for pointer
stalls or jumps. A B2 value of zero is the observed baseline, not proof of every
internal health condition.

## Validation and implementation notes

`firmware.py` pins the entire archive's size and SHA-256, validates the signed
components' header/payload CRCs, SHA-256 and RSA-2048 signatures, and prepares only
the two named payloads. The Swift executable independently pins those payloads'
sizes and SHA-256 values before opening the device. Unknown revisions and ambiguous
device selection are rejected.

The RSA public key was extracted from Main0241 and Main0257 and matched in both.
This is **not an independent Apple certificate-chain validation**; the fixed
archive hash and HTTPS source are part of the trust model. The remote also verifies
the signed payloads before activation. Firmware is neither patched nor resigned.

The audited OTA sequence uses native HID Feature report IDs:

| Request | Purpose |
| --- | --- |
| GET A0 / GET B2 | Require sensor mode zero and the observed idle OTA baseline |
| SET B0 `c3 bc` | Begin; clear the persisted apply mask |
| SET B0 `62 72` | Reset staging for each component |
| SET B1, chunks of up to 128 bytes | Transfer the complete signed component, header first |
| SET B2 `00`, GET B2 | Verify the staged component; require status `a1` |
| SET B2 `c3 bc` | Arm only after both components verify; firmware performs its battery check |
| SET B3, no payload | Request deferred reboot |

An uncertain data write is never retried. Journal writes precede critical commands;
journal failures stop further commands. The bootloader is not transferred.

Offline developer checks, without device access:

```sh
python3 -m unittest discover -s tests -p 'test_firmware_updater.py'
bash tools/firmware/update-a1513.sh --check --firmware "/path/to/firmware.zip"
```

Set `SIRIMOTE_TEST_FIRMWARE` to the ZIP path to include real-archive validation and
component-tampering tests in the Python suite. Firmware fixtures are not committed.
