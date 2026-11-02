# Magic Sirimote

Thank you to the open-source Siri Remote and LG webOS communities—especially [open-appleremote](https://github.com/a-funk/open-appleremote), [SiriRemote-Linux](https://github.com/Yanndroid/SiriRemote-Linux), [Clean Your TV](https://github.com/Razdva122/clean-your-tv-lg-webos), and [webOSbrew](https://www.webosbrew.org/)—for sharing the tools, code, and discoveries that made this project possible.

**Use a first-generation Siri Remote to control an LG TV, with the input program running inside the TV.** Swipe to select an app, move the remote to move the pointer, press to select, open settings, go back, and control volume and power over infrared. No Mac, Apple TV, or other computer needs to stay on for everyday use.

This repository shares a working, owner-tested implementation and the lessons behind it. Development combined hands-on testing by the owner with implementation and investigation assisted by OpenAI Codex.

> **Setup status:** this is a working, owner-tested implementation, but **following this README from top to bottom does not yet reproduce a fresh installation**, even on the same remote and TV models. Pairing, app-account discovery, device-access checks, IR programming, and startup/maintenance operations still need setup tooling. See the [setup audit](reviews/setup-audit.md) for the exact gaps. The published packages have passed computer-side tests but have not been installed on the owner’s TV.

- [1. What you can do](#1-what-you-can-do)
- [2. How it works](#2-how-it-works)
- [3. Setup guide](#3-setup-guide)

## 1. What you can do

### Verified behavior

The following behavior was physically confirmed by the owner during development, ending on **November 2, 2026**.

| Action | Result | Path |
| --- | --- | --- |
| Swipe the touch surface | Move the highlighted selection up, down, left, or right; hide the pointer | Bluetooth → TV program |
| Press the surface while a selection is highlighted | Select/open the highlighted item | Bluetooth → native Enter key |
| Move the remote deliberately, with your finger off the surface | Show and move the pointer | Bluetooth → TV program |
| Press the surface in pointer mode | Click at the pointer position | Bluetooth → mouse click |
| Short-press MENU | Open LG settings | Bluetooth → native Settings key |
| Short-press the microphone button | Go back | Bluetooth → native Back key |
| Short-press the TV-picture button | Go to LG Home | Bluetooth Home action; an IR Home entry also exists in the tested remote |
| Hold the TV-picture button for about **0.7 seconds**, then release | Toggle TV power | Infrared from the remote |
| Volume + / − | Adjust TV volume | Infrared from the remote |
| Play/Pause | Pause/resume video in the tested app | Bluetooth; chooses Play or Pause from current media state |

The two recent remaps are intentional: **MENU means Settings**, and **the microphone button means Back**. Voice input is not implemented.

#### Compatibility and limits

| Item | Tested baseline / current limit |
| --- | --- |
| Remote | Black first-generation **A1513**; Main firmware 0241, Radio 0107 |
| TV | **LG OLED55G3PJA**, firmware **43.21.96** |
| Input apps | Controller and receiver 0.9.71 |
| Startup package | 0.0.64 |
| Regular TV off/on | Confirmed on the working installation |
| Full loss of power and restart | Confirmed on the working installation before the final button remap; startup logic was preserved |
| Leaving the remote unused, then using it again | Owner reported normal operation; actual remote sleep/disconnection was not independently established in the final test |
| Pointer motion while touching the surface | **Not supported in this accepted version**; remove your finger to move the pointer |
| A1962, later silver remotes, other LG models/firmware | Not validated by this project |
| Long-term Developer Mode renewal | One extension experiment succeeded; indefinite unattended operation is not established |
| Public source build | Controller/receiver **0.9.72**, scheduler **0.0.65**; builds and passes host tests; has not replaced the working installation on the owner's TV |

This reproduces many everyday Magic Remote interactions, not every function of LG's original remote. Keep the original remote available for setup and recovery.

### Using the remote

#### Two ways to select things

Think of the touch surface as a small directional pad, and the whole remote as an air pointer.

```mermaid
stateDiagram-v2
    [*] --> Pointer
    Pointer: Pointer mode
    Navigation: Directional selection mode
    Pointer --> Navigation: Swipe the surface
    Navigation --> Navigation: More swipes or small hand movements
    Navigation --> Pointer: Finger off, then deliberate larger movement
    Pointer --> Pointer: Press surface to click pointer position
    Navigation --> Navigation: Press surface to select highlighted item
```

1. **To navigate by selection:** swipe. The pointer disappears. Swipe again to move the highlight, then press the surface to open the selected item.
2. **To use the pointer:** lift your finger off the surface and make a deliberate movement with the remote. Once the pointer appears, smaller movements move it. Press the surface to click.
3. **After a fresh connection:** place the remote on a flat surface, with nothing touching the touch area, for about five seconds. This gives the orientation calibration time to settle.

Small hand movements after a swipe should not immediately bring the pointer back. This was an important part of making the remote behave naturally.

#### Power is a short hold, not a three-second wait

```mermaid
flowchart LR
    A["Press TV-picture button"] --> B{"Release before hold threshold?"}
    B -->|Yes| C["Home action"]
    B -->|"Hold about 0.7 s"| D["IR power command"]
    D --> E["Release; let the TV finish turning on/off"]
```

The tested remote's threshold is approximately **0.716 seconds**, not a guaranteed wall-clock response time for the TV screen. Hold for a little under a second and release. Do not keep holding until the entire startup animation finishes. A power toggle is not a separate “on” or “off” command.

## 2. How it works

### How the pieces fit together

There are two independent routes from the remote to the TV:

```mermaid
flowchart LR
    R["Siri Remote A1513"] -->|"Bluetooth: touch, buttons, orientation"| B["Program inside the LG TV"]
    B --> UI["LG interface: pointer, selection, settings, back"]
    R -->|"Infrared: volume and power"| IR["TV infrared receiver"]
    PC["Computer during setup"] -. "Install, inspect, configure" .-> B
```

The computer is a setup tool. It is not a relay for normal button presses. Infrared also works independently of the TV input program once the remote has the correct IR configuration.

Inside the TV, three packages divide the work:

```mermaid
flowchart TD
    OS["webOS Activity Manager"] -->|"Scheduled callback, approximately every minute"| S["Startup service"]
    S -->|"Check package identity and startup state"| C["Controller: manage the remote connection"]
    C --> R["Receiver: decode input"]
    R --> D["Directional keys / Settings / Back / Home"]
    R --> P["Pointer movement and click"]
    D --> TV["LG user interface"]
    P --> TV
```

The minute-based callback is for startup and recovery decisions. It does **not** mean the remote's input is processed once a minute. The receiver handles input continuously while running.

### Automatic startup and standby

“TV-local” means the program can run inside the TV. It does **not** mean it is permanently written into LG's firmware.

```mermaid
sequenceDiagram
    participant OS as webOS
    participant S as Startup service
    participant C as Controller
    participant R as Receiver
    OS->>S: Persistent Activity callback
    S->>S: Validate callback, installed files, and boot/resume state
    S->>C: Launch when eligible
    C->>C: Check paired target and connection
    C->>R: Start one bound input session
    R->>R: Enable notifications and sensor mode, then read input
    R-->>C: Ready / result records
```

The implementation uses a persistent webOS **Activity**, roughly a recurring system callback. This is an internal startup mechanism, not a viewing/recording timer you must set in the TV guide. It keeps records so that a delayed callback or uncertain launch does not blindly start another input process.

### Source code and contributing

```text
src/
  check.py              # Host-only test runner
  build.py              # Configured three-package builder; no TV contact
  build_support.py      # Deterministic IPK archives and tiny ARM launchers
  runtime-files.json    # Explicit list of source modules allowed in packages
  ir_packets.py         # Pure IR configuration packet encoder; never transmits
  runtime/              # Controller, receiver, decoding, lifecycle
  scheduler/            # Startup, standby, expiry service
  tv_inventory.py       # Read-only environment metadata on a TV
config.example.json     # Fake device identities; historical example UIDs
reviews/                # Public export verification results
tests/                 # Input, layout, and publication regression tests
  scheduler/           # Startup service tests and synthetic fixtures
```

Developers can run the regression suite with `python3 src/check.py`. It checks input decoding, navigation, lifecycle handling, and package construction using simulated device operations. It is a development check, not an installation step or proof of hardware compatibility.

Start with these files if you want to understand or adapt the behavior:

| Area | Source |
| --- | --- |
| MENU/microphone/Home/Play-Pause masks | [`system_buttons.py`](src/runtime/system_buttons.py) |
| Native LG key codes | [`system_key_sink.py`](src/runtime/system_key_sink.py) |
| Pointer versus selection mode | [`navigation_mode.py`](src/runtime/navigation_mode.py) |
| Click versus Enter output | [`grouped_prefix_output.py`](src/runtime/grouped_prefix_output.py) and [`output_bridge.py`](src/runtime/output_bridge.py) |
| Truncated report decoding | [`decoder.py`](src/runtime/decoder.py) |
| Orientation-based pointer | [`adaptive_prefix_pose.py`](src/runtime/adaptive_prefix_pose.py) |
| Connection supervision | [`resident_controller_entry.py`](src/runtime/resident_controller_entry.py) |
| Startup registration | [`creator.js`](src/scheduler/creator.js) |
| Standby resume checks | [`standby-resume.js`](src/scheduler/standby-resume.js) |
| Developer Mode maintenance | [`expiry.js`](src/scheduler/expiry.js), [`expiry-policy.js`](src/scheduler/expiry-policy.js) |

The runtime separates input decoding, device identity, connection management, process coordination, and verified shutdown. Scheduler tests live under `tests/scheduler`; package hashes are generated during the build. An explicit source inventory and dependency test define which modules belong in the packages.

Read [PORTING.md](docs/PORTING.md) for deployment requirements and handling of unsupported state records. Source provenance is recorded in [`docs/source-provenance.json`](docs/source-provenance.json).

Useful contributions include a verified clean-install workflow, additional TV/remote compatibility reports, better bounded status reporting, and investigation of complete touch-plus-orientation input. Include your model, firmware, steps, expected behavior, and actual behavior. Remove addresses, serials, tokens, private keys, and raw recordings from public reports.

### Credits and license

We are grateful to the authors and contributors of:

- **[open-appleremote](https://github.com/a-funk/open-appleremote)** — Siri Remote protocol documentation, input activation, button and touch research. Its documented captures must not be treated as proof of every behavior on our A1513/LG combination.
- **[SiriRemote-Linux](https://github.com/Yanndroid/SiriRemote-Linux)** — earlier first-generation Siri Remote investigation and implementation references.
- **[Clean Your TV for LG webOS](https://github.com/Razdva122/clean-your-tv-lg-webos)** — a valuable reference for TV-local native helpers and exploring the webOS application boundary.
- **[webOSbrew / Homebrew Channel](https://github.com/webosbrew/webos-homebrew-channel)** and **[webOS Dev Manager](https://github.com/webosbrew/dev-manager-desktop)** — community tooling and references for installation, services, and startup behavior. Homebrew Channel is not a bundled runtime dependency here.
- **LG's [webOS OSE Bluetooth service](https://github.com/webosose/webos.service.bluetooth2), [Luna Service 2](https://github.com/webosose/luna-service2), and [webOS developer documentation](https://webostv.developer.lge.com/)** — essential platform source and documentation.
- The Linux input, Python, Node.js, and LLVM communities whose tools underpin the implementation and build process.

Links credit research and tooling; they do not imply endorsement or identical compatibility. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for scope. Project-authored code is under the [MIT license](LICENSE). Apple and LG names identify the hardware; this is an independent project.

## 3. Setup guide

The steps below describe the intended setup sequence. **They are not yet a complete executable installation guide.** “Missing tool” means the reader would currently have to write or adapt code; it does not mean running the next command will fill in the gap.

| Stage | What is available | What is still missing |
| --- | --- | --- |
| 1. Developer access | Official CLI registration and key setup, outlined below | Target TV access must be verified |
| 2. Pairing | History of the successful DCSD-assisted repair | A supported first-pairing tool and fresh-pairing validation |
| 3. Target preparation | Required facts and a limited metadata reader | Identity collection, inert app installation to discover runtime UIDs, native access checks |
| 4. Package build | Runnable, tested builder | Verified target values from stage 3 |
| 5. Install and launch | Conditional installation/launch commands and runtime code | Installed-file/status verification and usable stop/resume/startup-registration tools |
| 6. Infrared | Tested command entries and a packet encoder | Backup, write, readback, and restore tool; the encoder does not program the remote |
| 7. Acceptance | Physical checks for both IR and Bluetooth | A fresh-install run of the published build, including automatic startup |

The [setup audit](reviews/setup-audit.md) separates documentation corrections from implementation work. These gaps apply to a new unit of the same model too: its pairing state, IR settings, and app account IDs are not inherited from the owner's installation.

### Before you begin

You need:

- An A1513 Siri Remote and a charged battery.
- A compatible LG webOS TV. Only the G3 configuration above has been validated here.
- The original LG remote.
- A computer for preparation, on the same network as the TV.
- For the diagnostic setup path used during development: an **A1513-compatible DCSD Lightning diagnostic cable** providing access to the remote’s serial console. A normal USB-to-Lightning charging cable cannot substitute for it. See the distinction below before obtaining hardware.
- A macOS or Linux development environment, Python 3.10+, Node.js 18+, and Git. The exported workflow was tested on macOS; Linux/WSL host setup has not been independently verified.
- The [webOS CLI](https://webostv.developer.lge.com/develop/tools/cli-installation) for the commands below. A GUI developer tool alone does not provide the `ares-*` commands.
- Clang with an ARM target to build the small native launchers. The builder defaults to `clang`; set `CLANG` if yours is elsewhere.
- Developer access to your own TV and an understanding of the [porting checkpoints](docs/PORTING.md).

The source targets a **32-bit ARM Linux input layout** and uses Python 3.10 or newer, Node, and webOS libraries already present on the tested TV. The Python requirement applies on the TV as well as when importing the runtime on the computer; the packages do not bundle Python, Node, `palmbus`, or the native libraries. Having a newer or more expensive LG TV is not sufficient to establish compatibility.

#### When is the diagnostic cable needed?

| Situation | Cable requirement / evidence |
| --- | --- |
| Everyday operation after setup | No cable; the remote talks directly to the TV |
| Reusing an already working TV pairing and IR configuration | The input program has no cable dependency; existing settings may be preserved |
| Reproducing the pairing repair used during development | A DCSD cable was used to select the TV on the remote and verify the stored peer |
| Reading/restoring IR settings or checking sensor shutdown when Bluetooth stopped responding | The diagnostic console was used during development |
| Setting up a different, previously unpaired remote from scratch | A cable-free procedure has **not** been validated; this public release does not yet provide a complete first-time pairing/programming tool |

The verified console used **115200 baud, 8 data bits, no parity, 1 stop bit, no flow control**. A serial port appearing on the computer is not enough: the remote must actually answer with its `DIAG>` prompt and correct identity/version. Compatibility of other cables sold as “DCSD” is not established by this project. Buying a cable alone does not complete the missing setup tooling.

Clone or download this repository and open a terminal in its directory before following the steps below.

### Step 1: Set up developer access

Install the CLI using [LG's installation guide](https://webostv.developer.lge.com/develop/tools/cli-installation), then confirm it is available:

```sh
npm install -g @webos-tools/cli
ares -V
```

Follow [LG's Developer Mode guide](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app) to install the TV app, sign in, enable Developer Mode, and complete the reboot. On the computer, run:

```sh
ares-setup-device
```

Choose **add**, name the device `my-tv`, enter the TV's current IP address, use port **9922** and user **prisoner**. Then enable **Key Server** in the TV's Developer Mode app and run:

```sh
ares-novacom --device my-tv --getkey
```

Enter the passphrase displayed by the TV when prompted. Confirm access:

```sh
ares-device --device my-tv --system-info
ares-install --device my-tv --list
```

These are LG's developer-connection steps; they do not pair the Siri Remote. Keep credentials and keys out of this repository. The CLI has its own host-tool compatibility requirements; consult its installation guide if it conflicts with an existing CLI installation.

**Developer access does not prove native app access.** The receiver needs the TV's input nodes and internal services under its own app identity. This repository does not grant those permissions or install TV language runtimes. Those checks belong in Step 3.

### Step 2: Establish Bluetooth pairing

**Pairing belongs here: after developer access, before building and starting the input programs. Installing the three packages does not pair the remote.** Pairing tells the remote and TV that they belong together; reconnecting to a previously paired remote is a separate operation performed by the controller.

If this exact remote already has a working pairing with this exact TV, preserve it and verify the identities in Step 3. Pairing with an Apple TV or a Mac does not satisfy this requirement.

For an unpaired remote, this is currently a **missing general setup procedure**, not a step that can be completed by running an included installer. The project did successfully repair a registration between the tested A1513 and G3 using the following coordinated sequence:

1. Collect the model, firmware, remote address/name and TV adapter address listed in Step 3 **before changing pairing**. Connect the diagnostic cable and verify the remote's model, firmware, Bluetooth identity, and saved peer; independently verify the TV's Bluetooth adapter and the intended remote registration.
2. In that repair, remove only the stale registration for the intended remote on the TV. This was specific to the mismatched existing registration, not a blanket instruction to unpair working devices.
3. Start the TV's outgoing pairing request for that remote while using the remote's diagnostic console to select the measured TV adapter as its peer.
4. Establish the HID input connection and send the known input-start request. Pairing and a connected link alone were insufficient in the tested repair: earlier attempts lost the remote's saved peer around a minute later.
5. Verify both sides' identities and pairing state again after more than a minute. The initialized repair retained the peer through a 70-second observation. The cable remained attached for that check; later cable-free input tests were separate.

This sequence records what worked on the owner's devices. It is **not a verified fresh-pairing recipe for every LG TV**. The original scripts were tied to those devices and their existing state; they are not shipped as a general pairing tool. A new setup needs that tool adapted and validated before proceeding. Do not assume that choosing the remote in an ordinary Bluetooth menu completes all these steps.

```mermaid
flowchart LR
    C["Computer + diagnostic cable"] --> R["Remote: select the TV peer"]
    T["TV: pair with the intended remote"] <--> R
    T --> H["Establish HID and initialize input"]
    H --> V["Verify both sides after more than a minute"]
    V --> N["Proceed to device checks and package setup"]
```

### Step 3: Identify and check your devices

**Check the remaining device-specific requirements here.** If you cannot establish these facts, stop here and use the source as a reference while investigating your model.

Collect the identity rows below before pairing in Step 2; then verify the paired input and app-access requirements here. A successful build cannot establish these facts for you.

Record the following locally:

| Fact | Why it matters |
| --- | --- |
| Remote model and firmware | Different generations can send different data |
| Remote Bluetooth address | Prevents controlling an unintended nearby device |
| TV Bluetooth adapter address | Confirms the connection belongs to the expected TV |
| Exact remote name/serial exposed by Bluetooth | Additional identity check |
| Developer, controller, and receiver numeric user IDs | The runtime checks file/process ownership; these are not passwords |
| `LGE RCU` and `ClickableMouse` input devices | These provide the tested key and pointer output paths |
| A readable matching `hidraw` device and the expected report layout | This provides the remote's input stream |
| Native app access to the relevant webOS services | SSH access and app permissions are different things |

The read-only `src/tv_inventory.py` can report the current process account, executable presence, and selected input-node metadata when transferred to and run on the TV. It does not discover Bluetooth identities, determine app runtime UIDs, check interpreter versions, or prove native app permissions.

**There is an unresolved first-install dependency here:** Step 4 requires the controller and receiver's runtime user IDs, but those apps have not yet been installed in Step 5. The missing bootstrap tool must install inert versions under the final app IDs, observe their actual process identities and access, then rebuild and update without changing those identities. The package files' owner and the SSH user's ID are not substitutes. No inert bootstrap package or tool is included; do not guess the IDs or install an example build as a probe.

See [PORTING.md](docs/PORTING.md) for the precise ownership and access requirements. Those checks must also establish the TV's Python/Node/library compatibility, access to `hidraw`, `LGE RCU` and `ClickableMouse`, and required internal service calls under the native app identities. There is no general permission-setup tool in this release.

```mermaid
flowchart TD
    A["Step 1: developer access works"] --> B["Step 2: TV pairing verified; identities known"]
    B --> C["Native app access and input devices verified"]
    C --> D{"All target assumptions match?"}
    D -->|Yes| E["Configure and build"]
    D -->|No or unknown| F["Investigate the port before installing/running"]
```

### Step 4: Build packages for your setup

Copy the example configuration:

```sh
cp config.example.json config.local.json
```

Edit `config.local.json` with the values you actually measured:

| Field | Meaning |
| --- | --- |
| `remoteAddress` | Siri Remote Bluetooth address, lowercase colon-separated hex |
| `adapterAddress` | TV Bluetooth adapter address in the same format |
| `remoteName` | Exact observed remote name/serial; the current configuration validator accepts ASCII letters, digits, `_` and `-` |
| `developerUid` | Numeric account ID for the developer connection |
| `controllerUid` | Numeric account ID assigned to the controller app |
| `receiverUid` | Numeric account ID assigned to the receiver app |
| `devmodeMaintenance` | `disabled`, `check-only`, or `extend`; explained below |

The numeric IDs in the example are **historical baseline values**, not defaults that are safe to assume on your TV. The builder checks their format, not their correctness on a real device. Other fixed platform assumptions remain; this file is not a universal compatibility switch.

Build using your local configuration:

```sh
python3 src/build.py --config config.local.json --out build/my-tv
```

Choose a new output directory for each build. The builder refuses to overwrite an existing one. For a non-example build it also refuses unchanged placeholder device identities.

The output contains:

| Package | Role |
| --- | --- |
| `org.codex.siriremote.autocoord20261029v_0.9.72_arm.ipk` | Connection controller |
| `org.codex.siriremote.hidgattrouterb20261029u_0.9.72_arm.ipk` | Input receiver |
| `org.codex.siriremote.v20scheduler20261031a_0.0.65_arm.ipk` | Startup app and service |

The long internal package names are retained for compatibility with the tested implementation. Do not rename just one package: the components verify one another's identities and file hashes.

The builder regenerates those hashes from the configured source. This is why editing a file inside an installed package afterward can cause startup to be refused.

### Step 5: Install and start on a verified setup

**This is an advanced, conditional stage, not an unattended installer.** Continue only after the checks in Step 3 and [PORTING.md](docs/PORTING.md) are satisfied. A clean-TV installation has not been independently reproduced from this public checkout.

Before updating an existing installation, stop its input session cooperatively and verify the receiver's sensor-stop result. Keep its packages and state records. Do not overwrite a running receiver or delete its state to get past a refusal.

On a prepared, verified TV, the package installation commands are:

```sh
ares-install --device my-tv build/my-tv/org.codex.siriremote.autocoord20261029v_0.9.72_arm.ipk
ares-install --device my-tv build/my-tv/org.codex.siriremote.hidgattrouterb20261029u_0.9.72_arm.ipk
ares-install --device my-tv build/my-tv/org.codex.siriremote.v20scheduler20261031a_0.0.65_arm.ipk
```

Then:

1. Compare the installed files with `build/my-tv/manifest.json`, including package metadata and the startup service. Re-check app user IDs and state-directory ownership after installation.
2. Put the TV on its home screen. Disconnect the remote's diagnostic cable, if one is attached.
3. Press the touch surface to wake the remote.
4. Launch the **controller**, not the receiver directly:

   ```sh
   ares-launch --device my-tv org.codex.siriremote.autocoord20261029v
   ```

5. Verify the current run’s `receiver-ready-<run>.json` in the receiver’s `state` directory against the live receiver PID/start ticks and current session. The file contains `sensorModeVerified: 1`. An old ready file or a launch acknowledgement is insufficient. A supported status command that performs these checks is still missing.
6. Stop pressing the surface. Place the remote still for about five seconds, then perform the **Bluetooth input** checks in Step 7. Complete IR programming and startup registration before their corresponding tests.

The controller obtains the receiver's current file hashes from the startup service. Installing that service is therefore required even for manual controller launch. **Installing it does not automatically register startup.** Startup provisioning is a separate operation described in [PORTING.md](docs/PORTING.md#startup-provisioning).

#### Stop and resume before programming IR

Step 6 requires a cleanly stopped input session. The stop protocol exists in `src/runtime/stop_request.py`, but this checkout has no supported command that finds the live instance, requests stop, verifies sensor shutdown/process exit, and reconciles the completed stop records for later resume. [PORTING.md](docs/PORTING.md#stopping-updating-and-removing) describes that contract. Repeating `ares-launch` while a completed stop veto remains is not a substitute for the missing resume operation.

#### Register automatic startup before restart tests

Installation and a successful manual launch do not register the persistent Activity. The [startup provisioning contract](docs/PORTING.md#startup-provisioning) requires a fresh request, launch under the scheduler's own identity, verification of creation/binding/callback, and archival of the completed request. Its handlers exist, but a supported operator command is still missing. Complete and verify that operation before the off/on and full-restart tests in Step 7. Choosing `devmodeMaintenance` does not perform this registration.

### Step 6: Set up infrared separately

The program that handles Bluetooth input does not, by itself, teach the remote infrared commands. The working remote had its IR entries read, preserved, and selectively restored/configured during development.

The tested IR configuration was:

| Remote button | Entry | LG NEC bytes |
| --- | --- | --- |
| Volume + | Immediate | `20 DF 40 BF` |
| Volume − | Immediate | `20 DF C0 3F` |
| TV-picture | Immediate Home | `20 DF 3E C1` |
| TV-picture | Delayed Power, firmware delay selector `2` | `20 DF 10 EF` |

These bytes describe the tested remote's stored configuration. They are **not** ready-to-send shell commands. The delay selector is not a number of seconds; selector `2` produced the approximately 0.716-second behavior on this firmware.

A Bluetooth Home event and the stored IR Home entry can coexist. This release does not claim hardware-level short/long-press suppression across both routes; holding the TV button may produce Home before Power. The table describes the owner-accepted behavior, not a guarantee that a long press emits only Power.

If your remote already controls volume and power correctly, preserve those settings. During development, the diagnostic cable was used to read and restore IR settings; later power-hold adjustments were sent over Bluetooth. This does not establish a complete cable-free setup procedure. If your remote needs programming, read [IR.md](docs/IR.md) before adapting an IR programmer. The repository includes a pure packet encoder for inspection, **not** a universal IR-writing tool:

```sh
python3 src/ir_packets.py
```

Confirm IR independently with the TV input program cleanly stopped: point the remote at the TV, press Volume + once and Volume − once, and check that the volume rises and returns. Test power separately. Do not infer IR success from a Bluetooth-delivered key.

Running the encoder above only prints bytes; **it does not save these settings to your remote**. The missing programmer must handle existing entries and enable flags, write the intended entries, read them back, and verify the physical IR result. After IR checks, the missing resume operation from Step 5 must reconcile the clean stop and allow the controller to start again before the combined acceptance tests.

### Step 7: Verify everyday use

After manual input works, IR programming is verified, input has resumed, and automatic startup is registered, run these tests. Completing the host test suite does not replace them. If one fails, record exactly which step failed before changing anything.

| Test | What to do | Success looks like |
| --- | --- | --- |
| Directional selection | Swipe on the home screen | Pointer disappears; highlight moves |
| Selection click | Press after choosing an app by swiping | Highlighted app opens |
| Back | Short-press microphone | Previous screen returns |
| Settings | Short-press MENU | LG settings opens |
| Home | Short-press TV-picture | LG Home appears |
| Pointer | Finger off, five seconds still, then deliberate movement | Pointer appears and follows movement |
| Pointer click | Point at an item and press surface | Item under pointer is clicked |
| Media | Play a video; press Play/Pause twice | Pause, then resume in a supported media state |
| Volume | Point at TV; + once, then − once | Volume rises, then returns |
| Power | Hold TV-picture briefly, release; wait; repeat | TV switches off and back on |

For persistence, distinguish three different tests:

```mermaid
flowchart LR
    T["What are we testing?"] --> I["Remote unused; TV stays on"]
    T --> S["Ordinary TV off/on"]
    T --> B["Complete TV restart after power loss"]
    I --> IR["Input works again without manual restart"]
    S --> SR["Program resumes during everyday standby cycle"]
    B --> BR["TV starts the program after a new boot"]
```

- **Remote left unused:** leave the TV on and the unplugged remote untouched for about 15 minutes, then press the surface and try the controls. Note any delay. This proves usability after inactivity; proving actual remote sleep needs connection evidence as well.
- **Ordinary off/on:** after configuring startup, turn the TV off normally, wait about 30 seconds, and turn it back on. Try the same controls without using the computer to relaunch anything.
- **Full restart:** this is a separate startup test, not a daily requirement. When the TV is not updating, turn it off, disconnect its own power plug for about 30 seconds, reconnect, and start it again. Do not switch a household breaker for this test. Check automatic startup and input without a manual launch.

A working pointer is not proof that all buttons work. A successful power toggle is not proof that Bluetooth input resumed. Test both paths.

### Developer Mode expiry

Developer Mode still has an expiry. LG documents that expiry can disable Developer Mode and remove development apps. Follow [LG's current guidance](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app); do not treat this repository as an expiry bypass.

Public builds default to **`devmodeMaintenance: "disabled"`**:

| Setting | Behavior |
| --- | --- |
| `disabled` | No session-token read or LG session query by the maintenance module; manage expiry yourself |
| `check-only` | Read the TV's existing Developer Mode session token locally and query LG's official server; do not extend |
| `extend` | Also attempt official app-based extension when at most 14 days remain, normally checking daily |

The query uses HTTPS to `developer.lge.com`. The extension route launches LG's Developer Mode app with an extension request; its UI may appear. The source avoids printing or storing the raw token. An uncertain extension is retained as uncertain rather than immediately retried. These are implementation details of the experiment, not a documented guarantee from LG.

Changing `devmodeMaintenance` requires rebuilding and updating the package. The published default differs from the owner's existing experiment; exporting this repository did not change the running TV.

### Troubleshooting

| Symptom | Check first |
| --- | --- |
| Volume works, but swipes do nothing | IR and Bluetooth are separate. Check controller/receiver readiness and the paired target |
| Pointer stops when my finger touches the surface | Expected in this version; lift your finger |
| Pointer does not appear after a swipe | Finger off; deliberate larger movement. Small hand tremors deliberately keep selection mode |
| Pointer never starts after connection | Place the remote still with no surface contact for about five seconds; inspect calibration/readiness |
| Click works with the pointer but not after swiping | Confirm the matching receiver build; selection mode must emit Enter, not a mouse click |
| Settings works but microphone does not go back | Confirm the final button mapping and supported packet shape; no voice processing is needed |
| Play/Pause does nothing in one app | Media state may be missing or stale; the implementation does not blindly guess a toggle |
| Power seems slower than 0.7 seconds | Release after the threshold; screen startup time is separate from button hold time |
| `ares-launch` succeeds but there is no response | Check the per-run ready/result records; a launch acknowledgement is not receiver readiness |
| A package hash/ownership check fails | Verify the installed build and target account IDs. Do not disable checks or recursively chmod system directories |
| It works until an ordinary TV off/on | Inspect startup binding, power-state evidence, and retained stop requests |
| Diagnostics stop updating after a couple of minutes | Startup progress snapshots are intentionally bounded; a stale snapshot alone does not prove a stopped receiver |
| Bluetooth reports an error or stops replying | Preserve the result and session records. Do not repeatedly restart Bluetooth, re-pair, or resend sensor commands without understanding the current state |

The runtime favors stopping on an uncertain state over repeatedly issuing device commands. A retained record may be the reason it refuses to start, but it may also be the evidence needed to stop a previous sensor session correctly.

### Backup, updates, and removal

Before changing a working setup, keep:

- The exact three packages and their `SHA256SUMS`.
- Your local configuration, stored privately.
- A private copy of the relevant runtime/startup records, with ownership information.
- A readback of the remote's IR entries before changing them.
- A short list of physical tests that passed.

```mermaid
flowchart LR
    A["Working setup"] --> B["Save packages, settings, and evidence"]
    B --> C["Stop input and verify sensor stop"]
    C --> D["Install matching candidate packages"]
    D --> E{"Physical tests pass?"}
    E -->|Yes| F["Keep the candidate and its backup"]
    E -->|No| G["Stop candidate; restore matching prior packages"]
    G --> H["Reconcile session/startup records before restarting"]
```

A backup of application packages is not a full TV-firmware or remote-EEPROM backup. Do not restore old runtime state over a live session, and do not copy another TV's private state.

For removal, first disable/cancel the exact startup Activity through its creator, then request a cooperative controller stop and verify the receiver reports `sensorStopVerified: true`. Preserve any uncertain result for diagnosis. After no related process remains, remove the three app packages with your developer tooling. The IR settings live in the remote and survive removal of the TV apps; restore them separately if desired. See the [lifecycle notes](docs/PORTING.md#stopping-updating-and-removing).

The stop/cancel/restore protocols are engineering contracts, not a complete rollback command in this release. Pairing changes and IR writes also affect the remote itself; saving TV packages alone does not back up those settings.
