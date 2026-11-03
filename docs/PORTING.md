# Porting and deployment checkpoints

For installation, use [NATIVE_APP.md](NATIVE_APP.md). This document explains the platform assumptions that must be checked when adapting Magic Sirimote to another television or firmware.

## Build and package

`python3 src/check.py` runs the host tests. `python3 src/build_integrated.py --out build/integrated` builds one IPK containing the native settings application, its service, and the controller/receiver modules. Choose an output directory that does not already exist.

The package contains no personal Bluetooth addresses or credentials. Pairing in the TV application discovers and verifies the remote and TV adapter, then saves their identities locally. Process identities are checked at runtime; users do not supply app UIDs during the build.

`src/build_support.py` constructs deterministic archives and the ARM launcher. `src/runtime-files.json` is the explicit runtime source inventory. Generated manifests and checksums describe each package; the package tests verify reproducibility, contents and integrity pins.

## Platform assumptions

| Area | Requirement |
| --- | --- |
| CPU and input ABI | ARM32; Linux `input_event` represented by `=iiHHi` |
| Native launcher | ARM ELF invoking `/usr/bin/python3 -I -B .../native_probe.py` |
| Python | TV Python 3.10+, Linux `fcntl`, `ctypes` and `/proc` |
| Native libraries | `libluna-service2.so.3`, `libglib-2.0.so.0`, `libSDL2-2.0.so.0`, `libSDL2_ttf-2.0.so.0` |
| Service | TV Node.js and `palmbus` under the installed service identity |
| Package roots | `/media/developer/apps/usr/palm/applications`, `services` and `packages` |
| Shared state directories | Package UID 5999 / GID 5000, mode 0770; specific boot paths also accept 0775 |
| Runtime processes | Unprivileged, GID 5000, zero effective capabilities; controller and receiver identities are verified separately |
| Output devices | Unique, capability-checked `LGE RCU` and `ClickableMouse`; no fixed event number |
| Remote input | Verified Bluetooth/HID identity, firmware gates and supported report shapes |
| Startup | webOS Activity Manager and native application/service lifecycle notifications |

The app and service declare `bluetooth.query`, `application.launcher`, `activity.operation`, `activity.query`, and `configurator.callbacks`. These declarations do not guarantee the same access on every webOS version. Test under the actual native app identity: developer SSH and native applications have different device visibility and permissions. The application does not become root.

Do not weaken an identity or device-capability check merely to make a new TV accept input. Identify the platform difference and update its validation and tests together. `src/tv_inventory.py` can collect read-only metadata through developer SSH; it does not prove what a native application can access.

## Pairing and infrared

Pairing admission uses product information and the HID service, then checks the connected product, serial and firmware. A name or Apple vendor ID alone is insufficient. A1513 is tested on the hardware listed in the README. A1962 is admitted by the product filter, but its operation on an LG TV has not been verified with hardware; infrared programming still requires a validated firmware profile.

Full infrared-table readback is unavailable. The application can set and delete assignments, but its saved records are not a backup of a factory configuration. See [IR.md](IR.md) for the protocol and persistence limits.

## Startup and recovery

`src/integrated/startup.js` registers and maintains the startup Activity and gates reception on the television's power state. Screen Off keeps playback and input active so a configured button can restore the picture. Developer Mode expiry is managed by the user; the application does not automatically renew it.

The controller holds an exclusive project lease and verifies the receiver package and process before accepting its records. A session that might have enabled sensors must complete the sensor-stop/recovery path. Failed or interrupted operations retain their evidence.

A launch that failed before input could start can be archived only after the original process has ended and the absence of input-start and receiver activity has been checked. The archived records do not claim a successful session or a sensor-stop result. Completed historical records do not prevent a new, independent launch from being reconciled.

Do not delete state files to bypass a failed check or copy them between televisions. Project locks serialize this application's work; they do not prove exclusive access against unrelated TV software.

## Input limitations and compatibility reports

The tested TV delivers truncated 21-byte FC reports on the normal input path. The no-touch prefix contains usable orientation data, while touch-bearing prefixes do not contain the same complete orientation. The parser does not reconstruct missing sensor bytes. This is why touch navigation and gyro cursor operation use distinct modes.

Host tests verify parsing, state transitions, rejection paths and package construction. They do not establish compatibility with another TV, a factory-fresh remote, or a different firmware. Reports should include model, firmware, steps and observed behavior, with private addresses, serials, tokens and raw captures removed.
