# Magic Sirimote

**This project was developed through Vibe Coding:** an AI coding agent wrote and revised the code, with a human directing the work and testing it on real hardware.

Thank you to the open-source Siri Remote and LG webOS communities for the tools, code and discoveries that made this possible. In particular, this project owes much to [open-appleremote](https://github.com/a-funk/open-appleremote), [SiriRemote-Linux](https://github.com/Yanndroid/SiriRemote-Linux), [Clean Your TV](https://github.com/Razdva122/clean-your-tv-lg-webos), and [webOSbrew](https://www.webosbrew.org/).

Magic Sirimote lets a first-generation Siri Remote control an LG webOS TV. Install one app on the TV, pair the remote in that app, and choose your button assignments. **Your Mac does not need to stay on after setup. No Apple TV is needed.**

This is an experimental community project with limited hardware testing. Reconnection and recovery are still being improved. Keep the original LG remote available.

- [Compatibility and requirements](#compatibility-and-requirements)
- [Set up from a Mac](#set-up-from-a-mac)
- [Troubleshooting](#troubleshooting)
- [Optional TV-side input-device fix](#optional-tv-side-input-device-fix)
- [Reset or uninstall](#reset-or-uninstall)

## Compatibility and requirements

### Tested hardware

| Component | Tested model or version |
| --- | --- |
| Siri Remote | First generation, black, **A1513** and **A1962** |
| LG TV | **LG G3 — OLED55G3PJA** |
| webOS platform version | **11.2.0** (`sdkVersion`) |
| TV firmware | **43.21.96** |

The webOS platform version and TV firmware version are different values. You can check your TV's values during the connection step below. You do not need to look up the remote's firmware before starting; the app verifies its identity during setup. Firmware version numbers do not restrict support for A1513 or A1962.

Both models have been tested for pairing, infrared assignments, swipes, touch-surface clicks, and gyro pointer control. Later, silver Siri Remote generations are not supported.

## Set up from a Mac

**Use Magic Sirimote to pair the remote. The TV's standard Bluetooth device settings cannot complete the Siri Remote pairing used by this app.**

Do not pair Siri Remote with the Mac. The Mac installs the app; the TV app pairs directly with Siri Remote. You will enter the TV's network IP address on the Mac.

### 1. Create an LG Developer account

Open the [LG webOS TV Developer website](https://webostv.developer.lge.com/), select **Sign In**, and create an account if necessary. Complete the registration and any verification requested by LG. You will use that account in the TV's Developer Mode app.

### 2. Enable Developer Mode on the TV

1. Open the TV's app store and search for **Developer Mode**.
2. Install and open LG's Developer Mode app.
3. Sign in with your LG Developer account.
4. Turn **Dev Mode Status** on and let the TV restart.
5. Reopen Developer Mode. Note the displayed **IP address**; you will use it to connect the Mac to the TV.

If Dev Mode Status is already on, leave it on. LG documents this process in its [Developer Mode guide](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app).

### 3. Install the Mac tools

Open **Terminal** on a Mac with [Node.js and npm](https://nodejs.org/en/download) installed.

Run these commands to check whether Node.js and npm are installed:

```sh
node --version
npm --version
```

Install LG's command-line tools and select the TV profile:

```sh
npm install --global @webos-tools/cli
```

```sh
ares -V
ares-config --profile tv
```

`ares -V` should print a version number. If installation reports a permissions error, use the guidance linked from [LG's CLI installation page](https://webostv.developer.lge.com/develop/tools/cli-installation) before continuing.

### 4. Connect the Mac tools to your TV

Connect the Mac and TV to the same local network, using Wi-Fi or Ethernet. In Terminal, run:

```sh
ares-setup-device
```

Use the arrow keys to choose **add**, then press Return. Enter the following values when prompted:

| Prompt | What to enter |
| --- | --- |
| Device name | `my-tv` — this is a nickname used in the commands below |
| Device IP address | The actual IP address shown in Developer Mode on your TV |
| Device port | `9922` |
| SSH user | `prisoner` |
| Description | Any description you like, such as `Living room TV` |
| Password, if asked | Leave empty; do not enter your LG account password |
| Set default / Save | Confirm saving; making it the default is optional |

If you already registered this TV, choose **modify** instead and check its IP address. If you use a different nickname, replace `my-tv` in every command below with that nickname.

On the TV, turn **Key Server** on in Developer Mode. Then run:

```sh
ares-novacom --device my-tv --getkey
```

When prompted for a passphrase, type the characters displayed in the TV's Developer Mode app, exactly as shown. This is separate from your LG account password. Do not put the passphrase in a public screenshot or issue report.

Check the connection:

```sh
ares-device --system-info --device my-tv
```

**Continue when this prints the TV's system information.** If it cannot connect, fix the connection first; installing the app will otherwise fail too. The commands follow LG's [CLI guide](https://webostv.developer.lge.com/develop/tools/cli-dev-guide) and [TV connection instructions](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app#connecting-with-cli).

### 5. Download and install Magic Sirimote

An **IPK** is the app's installation file.

The following commands create a folder under Downloads and download the package and its checksum. Copy each command into Terminal and wait for it to finish before continuing:

```sh
mkdir -p "$HOME/Downloads/magic-sirimote"
cd "$HOME/Downloads/magic-sirimote"
```

```sh
curl --fail --location --output org.magicsirimote.app_arm.ipk \
  https://raw.githubusercontent.com/super-dog-human/magic-sirimote/main/releases/org.magicsirimote.app_arm.ipk
```

```sh
curl --fail --location --output SHA256SUMS \
  https://raw.githubusercontent.com/super-dog-human/magic-sirimote/main/releases/SHA256SUMS
```

Check the download:

```sh
shasum -a 256 -c SHA256SUMS
```

The result should end with `org.magicsirimote.app_arm.ipk: OK`. If it does not, download both files again before installing.

Keep the TV on, then install and open the app:

```sh
ares-install --device my-tv org.magicsirimote.app_arm.ipk
```

```sh
ares-launch --device my-tv org.magicsirimote.app
```

Wait for the installation command to report success before running the launch command. **Magic Sirimote** should open on the TV. You can open it later from the TV's Home screen, like other apps.

### 6. Pair Siri Remote with the TV

Open **Magic Sirimote** on the TV. If it is not already open, select this icon from the TV's Home screen:

![Magic Sirimote app icon](assets/app-icon.png)

![Pairing start screen](assets/screenshots/pairing.png)

The app shows **Pair a Siri Remote**. If it opens the settings screen instead, continue to [Choose all of your button assignments](#7-choose-all-of-your-button-assignments).

1. On the TV, choose **Start pairing** with the LG remote.
2. Wait until the app starts searching. **Start the search before pressing the pairing buttons.**
3. Hold Siri Remote near the TV. Press and hold **MENU and Volume Up (+) together for about five seconds**, then release both.
4. The app automatically pairs with the first available supported Siri Remote it finds. **Put only the remote you want to use into pairing mode.** If this app already has a saved remote, the search stays restricted to that remote. No **Pair selected remote** step is needed in v0.4.0.
5. Wait while the app verifies the remote and prepares input. On success, it saves the connection information and closes the window to start reception. If the search expires, choose **Search again** and repeat the pairing-button sequence.
6. Press Siri Remote's touch surface once to wake it. Try swiping to move the TV's selection, then pressing and releasing the surface to select an item.

<details>
<summary>Connection check and search screens</summary>

![Checking the remote connection](assets/screenshots/checking.png)

![Searching for a Siri Remote](assets/screenshots/searching.png)

![Automatic pairing and verification](assets/screenshots/automatic-pairing.png)

These pairing illustrations are rendered from the v0.4.0 UI code.

</details>

If the app reports an error or no candidate appears, see [Pairing problems](#pairing-problems).

### 7. Choose all of your button assignments

Reopen **Magic Sirimote** from the TV's Home screen using the LG remote. Choose **Button Assignments**.

![Remote settings](assets/screenshots/settings.png)

The six rows are **Menu**, **TV / Control Center** (the button with a TV picture), **Siri** (the microphone button), **Play/Pause**, **Volume Up**, and **Volume Down**. Touch-surface clicks and swipes are separate and do not need button assignments.

Use the LG remote's direction keys to select a cell, press OK to open its choices, and select an action. Siri Remote can also navigate these screens when reception is working, but keep using the LG remote for saving.

Here is a useful starting configuration. **It is a suggestion, not a preset applied automatically:**

| Button | Press | Hold (~0.7 s) |
| --- | --- | --- |
| Menu | Back (IR) | Do nothing |
| TV / Control Center | Home (IR) | Power on/off (IR) |
| Siri | Screen off / restore | Do nothing |
| Play/Pause | Play / Pause | Do nothing |
| Volume Up | Volume + (IR) | Do nothing |
| Volume Down | Volume - (IR) | Do nothing |

The screenshot below uses the suggested assignments above.

![Example button assignments](assets/screenshots/assignments.png)

<details>
<summary>Action choices and custom IR code entry</summary>

![Choosing a button action](assets/screenshots/action-picker.png)

![Entering a custom IR code](assets/screenshots/custom-ir.png)

</details>

**What “IR” means:** the remote itself sends infrared light to the TV. Point its front end toward the TV's infrared receiver. Configured IR power and volume can work even when the app's Bluetooth input is unavailable. Choices without “(IR)” are handled by the app running on the TV.

**How Press and Hold interact:** an IR Press action is sent immediately and may also happen at the beginning of a long hold. For example, holding the suggested TV button can send Home first, then Power. If you assign an IR action to Hold, also assign an IR action to Press on that button. A hold-only IR assignment can fire on a short press, so the app prevents that combination.

**What “Do nothing” means:** on an unconfigured app, all twelve cells display Do nothing. That display is not a readback of the remote's existing infrared memory. Explicitly choosing Do nothing and saving removes that slot's IR assignment and disables its TV-side action. Unedited buttons are left unchanged. To disable a button completely, set both its cells to Do nothing.

Choose every cell you want to use before your first save. The app cannot recover an unknown infrared assignment after you overwrite or delete it.

### 8. Save your settings

1. Press **Back** to return to the first settings screen. Your button edits remain pending.
2. Leave **Gyro cursor** on if you want pointer control.
3. Choose **Save and restart**. The app applies your edited assignments and restarts reception.
4. Wait for the window to close, then use Siri Remote.

If saving fails partway through, some assignments may already have changed. Read the displayed result and press Siri Remote's touch surface once to wake it before retrying. Selecting a choice or leaving the editor with Back does not itself save anything. **Close** asks whether to discard unsaved edits, then returns to Home. Back from the first settings screen also returns to Home.

<details>
<summary>Unsaved changes confirmation</summary>

![Discarding unsaved changes](assets/screenshots/discard.png)

</details>

## Troubleshooting

### Keep Developer Mode active

Periodically open **Developer Mode** on the TV and check **Remain Session**. While time remains and the TV is online, use **EXTEND** to renew it. Magic Sirimote does not renew it for you. If Developer Mode becomes disabled, LG removes the apps installed through it. See [LG's session instructions](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app#extending-developer-mode-time).

### The Mac cannot connect to the TV

Confirm that the TV is on, Dev Mode Status is on, and both devices are on the same local network. Recheck the IP address shown by the TV: it can change after a restart. Run `ares-setup-device`, choose **modify**, and update `my-tv` if needed. Then retry `ares-device --system-info --device my-tv`.

If key authentication fails, enable Key Server and repeat `ares-novacom --device my-tv --getkey` with the current on-screen passphrase. Do not switch Developer Mode off and on merely to refresh an IP address or key.

### The app does not open

Check that installation reported success, then run this command on the Mac to open the app:

```sh
ares-launch --device my-tv org.magicsirimote.app
```

### Pairing problems

- Start searching in the app **before** holding MENU + Volume Up. Release both buttons after about five seconds and keep the remote near the TV.
- Charge the remote if necessary, then disconnect its cable before testing input.
- If no candidate appears, choose **Search again** when offered and repeat the sequence.
- Pairing starts automatically when a supported, available remote is found. Put only your intended remote into pairing mode; wait for identity verification to finish. If the search expires, choose **Search again**.
- If remote identification fails, record the exact message. A name resembling “Siri Remote” is not sufficient for acceptance.

The pairing used by Magic Sirimote may not appear in the TV's ordinary Bluetooth-controller list. An empty list there does not by itself mean pairing failed. Use Magic Sirimote's own screen and test input instead.

### The remote does not respond after being idle

Siri Remote can go to sleep after a period of inactivity. **Press the touch surface down once to wake it**, then swipe or move the remote. Simply touching or swiping the surface may not wake it. Allow a moment for Bluetooth to reconnect. If it still does not respond, follow the checks below.

### Restart Siri Remote

If the remote remains unresponsive, restart the remote itself:

1. Disconnect its charging or diagnostic cable.
2. Press and hold **TV / Control Center** (the TV-picture button) and **Volume Down (−)** together for about **five seconds**.
3. Release both buttons and wait **5–10 seconds**.
4. Press the touch surface once, allow Bluetooth to reconnect, and try swiping again.

This is the remote-restart button sequence documented by [Apple](https://support.apple.com/en-us/102569). Apple TV status-light and connection messages in that guide do not apply to an LG TV. This is separate from Magic Sirimote's destructive **Reset app** command; do not choose Reset app just to restart the remote.

### Only power or volume works

Infrared and Bluetooth operate independently. Working IR buttons do not confirm that Bluetooth reception is working.

1. Press the touch surface once, then try a few swipes. Allow time for reconnection, especially just after turning on the TV.
2. With the LG remote, open Magic Sirimote and read any message. If a settings window was left open, choose **Close**, then try Siri Remote again.
3. Check that Developer Mode is still enabled.
4. If input remains unavailable, try a normal TV power-off/power-on with the LG remote, then press Siri Remote's touch surface once to wake it.
5. If normal power cycling does not help, a full restart may clear a stuck Bluetooth state: when the TV is not updating, turn it off, unplug it for about 30 seconds, reconnect power, and turn it on. Allow startup time before testing again.

Recovery is not guaranteed for every Bluetooth failure. If the problem keeps returning, report it rather than repeatedly resetting pairings or deleting app files. Include whether swipes, surface clicks, cursor movement and IR still work, and whether the problem followed sleep, power-on or saving settings.

### Bluetooth connects, but input remains unavailable

On the TV used for testing, Developer Mode apps can access input devices numbered **0–31** (`/dev/hidraw0` through `/dev/hidraw31`). Repeated reconnections eventually assigned Siri Remote a number outside that range: Bluetooth connected, but Magic Sirimote could not receive input. These are OS input-device numbers, not saved pairing slots.

The investigation found that LG's `bthidmanager` process retained 41 disconnected input-device references. Linux retains a device's number until its last open reference is released (see the [Linux hidraw implementation](https://github.com/torvalds/linux/blob/v6.12/drivers/hid/hidraw.c)). An optional, firmware-specific [TV-side fix](#optional-tv-side-input-device-fix) prevents this retention for supported Siri Remotes. **Updating the app IPK alone does not install this fix.**

Without TV root access, a full restart remains a temporary recovery option: when the TV is not updating, turn it off, unplug it for about 30 seconds, reconnect power, and turn it on. This restored an accessible number in an earlier test without deleting the pairing, but does not prevent recurrence. **Reset app is not needed for this recovery.** The root-only fix below was applied without rebooting the TV.

### Swipes work but the pointer does not

Check that Gyro cursor is on and saved. Lift your finger completely off the touch surface and move the remote more deliberately. If movement is misdirected, lay the remote flat with its touch surface up and front end toward the TV. Choose **Reset cursor orientation**, confirm **Restart**, and leave the remote still until reception resumes. A working swipe does not necessarily mean orientation setup has completed yet.

<details>
<summary>Cursor orientation reset confirmation</summary>

![Resetting cursor orientation](assets/screenshots/orientation.png)

</details>

### Voice input

Voice input is not supported.

## Optional TV-side input-device fix

This is a separate system workaround for the retained-device problem above. It is **not an app feature or an automatic IPK install step**. It has been tested only on **LG G3 OLED55G3PJA, firmware 43.21.96**, with Siri Remote **A1513 / A1962**. The installer checks the exact LG executable and service hashes and refuses other versions. Do not bypass those checks for another TV or firmware.

### What changes on the TV

The helper intercepts `open64` only inside `/usr/sbin/bthidmanager`. When that LG process opens a hidraw device, it reads the device's bus/vendor/product identifiers. For Bluetooth Apple `004c:0266` or `004c:026d`, it immediately closes that process's reference and reports `ENODEV`. It also releases the reference if the device disappears during the identity check. Other devices pass through. Magic Sirimote continues receiving Siri Remote input through its own process.

The installer creates these files:

| TV path | Purpose |
| --- | --- |
| `/var/lib/magic-sirimote-hid-guard/libsirimote-hid-guard.so` | Small helper library |
| `/var/lib/magic-sirimote-hid-guard/installed.json` | Installed hashes and rollback information |
| `/var/lib/magic-sirimote-hid-guard/rollback.py` | Restore the original service behavior |
| `/var/systemd/system/env/bthidmanager.env` | `LD_PRELOAD` setting for this service only |

The existing LG service already reads that environment-file path. Its unit and executable are not edited. The files are root-owned and stored on the TV's persistent `/var` filesystem. No global preload, root login server, firmware replacement, pairing reset, or IR assignment change is installed. The helper does not read input reports and has no background polling or delay loop.

Only `bthidmanager` is restarted during installation or rollback. Bluetooth remote operation may pause briefly; the TV itself is not rebooted. If Siri Remote is still unresponsive afterward, open Magic Sirimote with the LG remote, choose **Restart**, and wake Siri Remote. Both remotes worked after this step in the hardware test, and the LG process no longer held Siri Remote's input reference.

These files are intended to survive a TV restart; persistence and the existing service loading path were checked, but **a reboot test has not been performed**. Firmware updates require a new compatibility review. This workaround does not guarantee recovery from unrelated Bluetooth failures.

### Requirements and installation

You must already have a way to run commands **as root on the TV**. The ordinary Developer Mode connection uses `prisoner`; `ares-install`, `ares-novacom`, and running `sudo` on the Mac do not turn that into TV root. The implementation used during this investigation ran once through a temporary privileged service, then removed that registration. It did not leave a root SSH connection available. This release supplies the installer, not a root-access method.

On the Mac, obtain the tagged source:

```sh
git clone --branch v0.4.0 --depth 1 https://github.com/super-dog-human/magic-sirimote.git
cd magic-sirimote/tools/hid-guard
shasum -a 256 -c SHA256SUMS
```

Transfer this directory to `/tmp/magic-sirimote-hid-guard` on the TV using your existing root-access method. For example, **only if root SSH is already configured**, use its actual IP address and port:

```sh
TV_IP=192.168.1.100       # Replace with your TV's address.
TV_ROOT_PORT=22          # Replace with your existing root SSH port.
scp -P "$TV_ROOT_PORT" -r . root@"$TV_IP":/tmp/magic-sirimote-hid-guard
ssh -p "$TV_ROOT_PORT" root@"$TV_IP"
```

Do not use the Developer Mode port `9922` as though it provided root. If no root-access method is available, stop here; normal app installation can still proceed.

Run the following **in the TV's root shell**, first checking without making changes:

```sh
id -u
/usr/bin/python3 -I -B /tmp/magic-sirimote-hid-guard/install.py --check
```

`id -u` must print `0`, and the check must report compatibility. Then apply:

```sh
/usr/bin/python3 -I -B /tmp/magic-sirimote-hid-guard/install.py --apply
```

The installer refuses to overwrite another configuration, checks that the service loads the helper and stays running, and attempts to restore the original service if activation fails. If the same fix is already installed and loaded, it reports that and makes no changes. It does not restart the whole TV. After success, the transferred `/tmp/magic-sirimote-hid-guard` directory can be removed; keep the installed files under `/var`.

### Remove the TV-side fix

Run this **as root on the TV**:

```sh
/usr/bin/python3 -I -B /var/lib/magic-sirimote-hid-guard/rollback.py
```

Rollback verifies the recorded library hash and environment contents before removing the service setting, restarting only `bthidmanager`, and deleting the installed helper files. If those files have been changed independently, it stops for inspection. **Uninstalling or resetting Magic Sirimote does not remove this separate TV-side fix.**

### Source, tests, and timing

Source and isolated tests are in [`tools/hid-guard`](tools/hid-guard). The shipped library is the exact binary tested on the TV. Host tests and a TV-side isolated test exercised 1,200 simulated Siri Remote opens, including both supported product IDs and pass-through for other hardware. The fake backend is test-only and must never be loaded into the real LG service.

To rebuild separately with Zig 0.13.0 and run the host C tests, from the repository root:

```sh
python3 tools/hid-guard/build.py --zig /path/to/zig --out build/hid-guard
python3 -m unittest discover -s tools/hid-guard -p 'test_*.py'
```

The installer accepts the pinned, hardware-tested library; a newly built binary with a different hash needs review and hardware testing before release. It is not automatically substituted into the installer.

The helper adds a device-information check when LG opens a hidraw device, and closes the reference for Siri Remote. It adds **no intentional wait or retry to normal connection or wake-up**. Before/after connection latency has not been measured. The few seconds of stability checks in the installer happen only during installation. The app's separate disconnect-notification ordering fix also adds no new wait interval; it keeps the existing recovery worker alive when notifications arrive in a different order. A1962's first button press after a full sleep disconnect remains unverified.

For the app's host checks and IPK build, from the repository root:

```sh
python3 src/check.py
python3 src/build_integrated.py --out build/app --bytecode-python /path/to/python3.12
```

Use a new output directory. CPython 3.12 matches the tested TV's import cache; omitting `--bytecode-python` builds source-only. These checks do not establish compatibility with an untested TV.

## Reset or uninstall

**Reset app is destructive.** It removes this remote's TV pairing, the app's active settings, and all short- and long-press infrared assignments on the remote, including power and volume. It also clears the surface-click IR entries, which are not exposed in the six-row editor. It does not reset the TV or remove other Bluetooth devices. It is not a factory-firmware reset of Siri Remote.

To start over:

1. Have the original LG remote ready, then press Siri Remote's touch surface once to wake it.
2. Open Magic Sirimote and choose **Reset app**.
3. Read the confirmation. Choose **Cancel** to leave things unchanged, or **Reset everything** to proceed.
4. Let the reset finish. If it stops partway through, read the error; reopening the app may offer **Continue reset** to finish the remaining steps. Some IR assignments may already be deleted.
5. When **Start pairing** appears, follow [Pair Siri Remote with the TV](#6-pair-siri-remote-with-the-tv), then configure and save your button assignments again.

<details>
<summary>Reset confirmation screen</summary>

![Resetting Magic Sirimote](assets/screenshots/reset.png)

</details>

To uninstall Magic Sirimote, open **Edit App List** on the TV's Home screen, select Magic Sirimote, and choose **Delete**. If you also want to remove its remote pairing and infrared assignments, complete **Reset app** before uninstalling.

Uninstalling the app alone should not be treated as unpairing the remote or deleting its stored IR settings. Reset clears the active configuration but may retain inactive local recovery records; it is not secure erasure of diagnostic history.
