# Magic Sirimote

**This project was developed through Vibe Coding:** an AI coding agent wrote and revised the code, with a human directing the work and testing it on real hardware.

Thank you to the open-source Siri Remote and LG webOS communities for the tools, code and discoveries that made this possible. In particular, this project owes much to [open-appleremote](https://github.com/a-funk/open-appleremote), [SiriRemote-Linux](https://github.com/Yanndroid/SiriRemote-Linux), [Clean Your TV](https://github.com/Razdva122/clean-your-tv-lg-webos), and [webOSbrew](https://www.webosbrew.org/).

Magic Sirimote lets a first-generation Siri Remote control an LG webOS TV. Install one app on the TV, pair the remote in that app, and choose your button assignments. **Your Mac does not need to stay on after setup. No Apple TV is needed.**

This is an experimental community project with limited hardware testing. Reconnection and recovery are still being improved. Keep the original LG remote available.

- [Compatibility and requirements](#compatibility-and-requirements)
- [What you can do](#what-you-can-do)
- [Set up from a Mac](#set-up-from-a-mac)
- [Everyday use](#everyday-use)
- [Troubleshooting](#troubleshooting)
- [Reset or uninstall](#reset-or-uninstall)
- [Source code and credits](#source-code-and-credits)

## Compatibility and requirements

### Tested hardware

| Component | Tested model or version |
| --- | --- |
| Siri Remote | First generation, black, **A1513** |
| Remote main firmware | **0241** |
| Remote radio firmware | **0107** |
| LG TV | **LG G3 — OLED55G3PJA** |
| webOS platform version | **11.2.0** (`sdkVersion`) |
| TV firmware | **43.21.96** |

The webOS platform version and TV firmware version are different values. You can check your TV's values during the connection step below. You do not need to look up the remote's firmware before starting; the app checks its identity and firmware during setup.

**A1962 is also accepted by the pairing filter, but has not been tested with this app on an LG TV.** Do not assume its cursor, infrared programming or full reset will work. The infrared writer rejects firmware it has not been validated against. Later, silver Siri Remote generations are not supported.

Testing includes removing and recreating the A1513's pairing. An independently clean installation with a factory-fresh remote and a different TV has not been verified.

### Have these ready

- A compatible LG webOS TV and its original LG remote. Use the LG remote for setup and saving settings.
- A charged Siri Remote.
- A Mac and TV connected to the same local network. Either device can use Wi-Fi or Ethernet, provided they can communicate with each other.
- Internet access to create an LG Developer account and download the tools and app.

The guide uses LG's Developer Mode installation method. Root access is not required. The app relies on Python 3.10+, Node.js, SDL2 and SDL_ttf already present on the tested TV; these TV components are not included in the download. Other TV firmware may lack the components or permissions it needs.

**Do not pair Siri Remote with the Mac as part of this guide.** The Mac installs the app; the TV app pairs directly with Siri Remote. You will enter the TV's network IP address on the Mac, but no Bluetooth addresses need to be entered anywhere.

## What you can do

After configuring the relevant button assignments:

- Turn the TV on and off, and adjust its volume using infrared.
- Go back, open Home or Settings, and play or pause video.
- Turn only the picture off while audio continues, then restore the picture.
- Swipe the touch surface to move the selection up, down, left or right.
- Press the touch surface to select the highlighted item or click at the pointer.
- Move the pointer by moving the remote, with your finger off the touch surface.
- Change button assignments, enable or disable the gyro cursor, adjust cursor sensitivity, and view battery level in the TV app.

Voice input is not supported. This covers many everyday remote functions, but does not replace every feature of LG's Magic Remote.

## Set up from a Mac

The steps below are for a first installation of the current single-app package. You do not need to build the source code, install Python on the Mac, or install any separate Magic Sirimote helper apps.

### 1. Create an LG Developer account

Open the [LG webOS TV Developer website](https://webostv.developer.lge.com/), select **Sign In**, and create an account if necessary. Complete the registration and any verification requested by LG. You will use that account in the TV's Developer Mode app.

### 2. Enable Developer Mode on the TV

Using the LG remote:

1. Open the TV's app store and search for **Developer Mode**.
2. Install and open LG's Developer Mode app.
3. Sign in with your LG Developer account.
4. Turn **Dev Mode Status** on and let the TV restart.
5. Reopen Developer Mode. Note the displayed **IP address** for step 4.

If Dev Mode Status is already on, leave it on. LG documents this process in its [Developer Mode guide](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app).

### 3. Install the Mac tools

Open **Terminal** on the Mac. You can find it with Spotlight: press Command–Space, type `Terminal`, and press Return.

Run these commands to check whether Node.js and npm are installed:

```sh
node --version
npm --version
```

If either is unavailable, install Node.js from the [official download page](https://nodejs.org/en/download). Node.js **24 LTS** is a suitable choice: it is the version identified as tested by the [webOS CLI project](https://github.com/webos-tools/cli#installation). The Node.js installer includes npm. Reopen Terminal after installation and try the two checks again.

Install LG's command-line tools and select the TV profile:

```sh
npm install --global @webos-tools/cli
```

```sh
ares -V
ares-config --profile tv
```

`ares -V` should print a version number. If installation reports a permissions error, use the guidance linked from [LG's CLI installation page](https://webostv.developer.lge.com/develop/tools/cli-installation) before continuing. If you have an older webOS CLI installed, follow that page's instructions for replacing it rather than mixing CLI installations.

### 4. Connect the Mac tools to your TV

In Terminal, run:

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

An **IPK** is the app's installation file. The current package is **0.6.50**.

The following commands create a folder under Downloads and download the package and its checksum. Copy each command into Terminal and wait for it to finish before continuing:

```sh
mkdir -p "$HOME/Downloads/magic-sirimote"
cd "$HOME/Downloads/magic-sirimote"
```

```sh
curl --fail --location --output org.magicsirimote.app_0.6.50_arm.ipk \
  https://raw.githubusercontent.com/super-dog-human/magic-sirimote/main/releases/integrated-preview/org.magicsirimote.app_0.6.50_arm.ipk
```

```sh
curl --fail --location --output SHA256SUMS \
  https://raw.githubusercontent.com/super-dog-human/magic-sirimote/main/releases/integrated-preview/SHA256SUMS
```

Check the download:

```sh
shasum -a 256 -c SHA256SUMS
```

The result should end with `org.magicsirimote.app_0.6.50_arm.ipk: OK`. If it does not, download both files again before installing.

Keep the TV on, then install and open the app:

```sh
ares-install --device my-tv org.magicsirimote.app_0.6.50_arm.ipk
```

```sh
ares-launch --device my-tv org.magicsirimote.app
```

Wait for the installation command to report success before running the launch command. **Magic Sirimote** should open on the TV. You can open it later from the TV's Home screen, like other apps.

If you already downloaded the repository, the same IPK is in [`releases/integrated-preview`](releases/integrated-preview). You can install that file instead; there is no need to download it twice.

### 6. Pair Siri Remote with the TV

Keep the LG remote in your hand for this step. The app normally shows **Pair a Siri Remote**. If it recognizes a remote already paired with this TV and opens the settings screen instead, skip to step 7.

1. On the TV, choose **Start pairing** with the LG remote.
2. Wait until the app starts searching. **Start the search before pressing the pairing buttons.**
3. Hold Siri Remote near the TV. Press and hold **MENU and Volume Up (+) together for about five seconds**, then release both.
4. Watch the candidate list on the TV. When your remote appears, use the LG remote's **Up/Down** keys to select it. Its displayed name may contain a serial number rather than simply “Siri Remote.”
5. Select **Pair selected remote** and press OK. Use Left/Right to move between the bottom buttons if necessary. **Appearing in the list does not mean pairing is complete.** If the app already knows this remote, it may select and pair it automatically.
6. Wait while the app verifies the remote and prepares input. On success, it saves the connection information and closes the window to start reception.
7. Press Siri Remote's touch surface once to wake it. Try swiping to move the TV's selection, then pressing the surface to select an item.

There is no fixed 70-second wait after pairing, although connection and startup still take time. If the app reports an error or no candidate appears, see [Pairing problems](#pairing-problems).

Pairing alone **does not rewrite the infrared assignments already stored in the remote**. Set up the six buttons next, even if some of them happen to work already.

### 7. Choose all of your button assignments

Reopen **Magic Sirimote** from the TV's Home screen using the LG remote. Choose **Button Assignments**.

The editor has six rows and two columns:

- **Press:** the ordinary press action.
- **Hold (~0.7 s):** the long-press action.

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

**What “IR” means:** the remote itself sends infrared light to the TV. Point its front end toward the TV's infrared receiver. Configured IR power and volume can work even when the app's Bluetooth input is unavailable. Choices without “(IR)” are handled by the app running on the TV.

**How Press and Hold interact:** an IR Press action is sent immediately and may also happen at the beginning of a long hold. For example, holding the suggested TV button can send Home first, then Power. An IR Hold action requires an IR Press action on the same button; the app rejects combinations that lack it. TV-side actions such as Play / Pause run when you release the button.

**What “Do nothing” means:** on an unconfigured app, all twelve cells display Do nothing. That display is not a readback of the remote's existing infrared memory. Saving applies the displayed choices: Do nothing deletes that slot's IR assignment and disables its TV-side action. To disable a button completely, set both its cells to Do nothing.

Choose every cell you want to use before your first save. The app cannot recover an unknown infrared assignment after you overwrite or delete it.

### 8. Save and check the result

1. Press **Back on the LG remote** to return to the first settings screen. Your button edits remain pending.
2. Leave **Gyro cursor** on if you want pointer control. Set **Cursor sensitivity** to **3 / 5** as a starting point, or choose a lower value for less movement.
3. Choose **Save and restart** using the LG remote. **Saving begins immediately; there is no additional confirmation.**
4. The controls dim while the app works. It applies **all twelve displayed assignments**, including unchanged cells and Do nothing cells, then restarts reception. Siri Remote input may pause during this process.
5. Wait for saving to finish and the window to close. Press Siri Remote's surface once to wake it, then check the functions below.

With the suggested assignments, check these one at a time:

1. Swipe to highlight an app, then press the surface to open it.
2. Point the remote toward the TV and press Menu briefly to go back.
3. Press the TV-picture button briefly to return to Home.
4. Lift your finger off the surface and move the remote deliberately to bring up the pointer. Aim at an item and press the surface to click it.
5. Point at the TV and press Volume Up once, then Volume Down once.
6. While a video is playing, press and release Play/Pause to pause it, then press and release again to resume.
7. Press and release Siri to turn off only the picture. Press and release it again to restore the picture. Audio should continue while the picture is off.
8. Hold the TV-picture button for a little under a second, then release it to turn the TV off. Wait about ten seconds and repeat to turn it on. Do not hold the button throughout the TV's startup animation.

If saving fails partway through, some assignments may already have changed. Read the displayed result, wake the remote, and see [Saving problems](#saving-problems) before retrying. Selecting a choice or leaving the editor with Back does not itself save anything. **Close** asks whether to discard unsaved edits.

## Everyday use

You can shut down the Mac. Keep Magic Sirimote installed and Developer Mode enabled on the TV. Reception starts automatically; there is no manual reception switch in the app.

### Swipes, clicks and the pointer

- **Move a selection:** swipe the surface. The pointer disappears and swipes move the highlight. Press the surface to choose the highlighted item.
- **Move the pointer:** take your finger off the surface, then move the remote deliberately. Small movements can adjust the pointer once it appears. Press the surface to click at its position.
- **After a swipe:** small hand movements should not immediately bring the pointer back. Use a larger, deliberate movement with your finger off the surface to return to pointer mode.
- **While touching the surface:** touch navigation takes priority. Continuous gyro pointing with a finger resting on the surface is not supported.
- **After sleep:** press the surface to wake the remote and allow it to reconnect. After a full TV restart, startup can take about a minute plus connection time; this is not a guaranteed maximum.

### Cursor settings

Open Magic Sirimote to adjust **Cursor sensitivity** from 1 to 5. Lower values reduce travel distance; they do not add a delay. Choose **Save and restart** to apply the change. Turning **Gyro cursor** off leaves touch navigation and assigned buttons available.

If the pointer's directions feel rotated, save or discard pending edits first. Lay the remote flat, touch surface up, with its front end toward the TV. Using the LG remote, choose **Reset cursor orientation**, then confirm **Restart**. Leave Siri Remote still until reception resumes, then pick it up and try again. This orientation reset does not rewrite the IR assignments.

### Battery level

Opening or reopening Magic Sirimote requests a new battery reading. It may briefly show **Battery: reading...**, followed by a percentage. **Battery: unavailable** means it could not obtain a fresh reading; it does not mean the battery is empty. Wake the remote, let it reconnect, and reopen the app. The screen does not continuously refresh the reading while left open.

### Custom infrared codes

For an action not listed by name, select a cell, choose **Custom code (IR)**, enter exactly two hexadecimal digits (`0`–`9`, `A`–`F`), and choose **Done**. Return to the first screen and use Save and restart to apply it.

For example, **09** is the LG mute/unmute command used on the tested TV. Assign it to Siri's Press cell if you prefer mute to screen off/restore. The code uses the app's LG infrared format; it is not a universal code for every manufacturer or every TV command. Test the result on your TV.

### Keep Developer Mode active

Periodically open **Developer Mode** on the TV and check **Remain Session**. While time remains and the TV is online, use **EXTEND** to renew it. Magic Sirimote does not renew it for you. If Developer Mode becomes disabled, LG removes the apps installed through it. See [LG's session instructions](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app#extending-developer-mode-time).

## Troubleshooting

### The Mac cannot connect to the TV

Confirm that the TV is on, Dev Mode Status is on, and both devices are on the same local network. Recheck the IP address shown by the TV: it can change after a restart. Run `ares-setup-device`, choose **modify**, and update `my-tv` if needed. Then retry the system-information command from step 4.

If key authentication fails, enable Key Server and repeat `ares-novacom --device my-tv --getkey` with the current on-screen passphrase. Do not switch Developer Mode off and on merely to refresh an IP address or key.

### The app does not open

Check that installation reported success, then try the launch command from step 5. If it still fails, note your TV model, system-information output and error message. An installed icon alone does not establish compatibility: the app needs the TV components listed under requirements. There is no universal dependency installer for unsupported TV firmware.

### Pairing problems

- Start searching in the app **before** holding MENU + Volume Up. Release both buttons after about five seconds and keep the remote near the TV.
- Charge the remote if necessary.
- If no candidate appears, choose **Search again** when offered and repeat the sequence.
- If a candidate appears, select it and choose **Pair selected remote**. Discovery and pairing are separate steps.
- If product or firmware verification fails, record the exact message. A name resembling “Siri Remote” is not sufficient for acceptance.

The pairing used by Magic Sirimote may not appear in the TV's ordinary Bluetooth-controller list. An empty list there does not by itself mean pairing failed. Use Magic Sirimote's own screen and test input instead.

### Only power or volume works

Infrared and Bluetooth operate independently. Working IR buttons do not confirm that Bluetooth reception is working.

1. Press the touch surface once, then try a few swipes. Allow time for reconnection, especially just after turning on the TV.
2. With the LG remote, open Magic Sirimote and read any message. If a settings window was left open, choose **Close**, then try Siri Remote again.
3. Check that Developer Mode is still enabled.
4. If input remains unavailable, try a normal TV power-off/power-on with the LG remote, then wake Siri Remote again.
5. If normal power cycling does not help, a full restart may clear a stuck Bluetooth state: when the TV is not updating, turn it off, unplug it for about 30 seconds, reconnect power, and turn it on. Allow startup time before testing again.

Recovery is not guaranteed for every Bluetooth failure. If the problem keeps returning, report it rather than repeatedly resetting pairings or deleting app files. Include whether swipes, surface clicks, cursor movement and IR still work, and whether the problem followed sleep, power-on or saving settings.

### Swipes work but the pointer does not

Check that Gyro cursor is on and saved. Lift your finger completely off the touch surface and move the remote more deliberately. If movement is misdirected, use Reset cursor orientation as described above. A working swipe does not necessarily mean orientation setup has completed yet.

### Saving problems

Keep the TV on and the remote nearby. Wake Siri Remote before saving, then use the LG remote to operate the app while reception pauses.

If you see a partial-save count, the completed items may already be stored. Inspect the choices and the error before retrying; do not assume the previous configuration was restored. An IR Hold must have an IR Press on the same row. For the TV button, use **Home (IR)** with **Power on/off (IR)** as shown in the suggested configuration.

The displayed assignments are the app's saved choices, not a complete readback of the remote's memory. Saving writes persistent IR settings, even when values are unchanged. Save when you intend to apply settings, rather than repeatedly saving as a connection test.

### Report a problem

Open an issue in this repository with your TV model, firmware, Siri Remote model, app version, the steps you took, and the exact message shown. Remove account details, passphrases, device addresses and serial numbers from screenshots or logs before posting them.

## Reset or uninstall

**Reset app is destructive.** It removes this remote's TV pairing, the app's active settings, and all short- and long-press infrared assignments on the remote, including power and volume. It also clears the surface-click IR entries, which are not exposed in the six-row editor. It does not reset the TV or remove other Bluetooth devices. It is not a factory-firmware reset of Siri Remote.

To start over:

1. Have the original LG remote ready and wake Siri Remote.
2. Open Magic Sirimote and choose **Reset app**.
3. Read the confirmation. Choose **Cancel** to leave things unchanged, or **Reset everything** to proceed.
4. Let the reset finish. If it stops partway through, read the error; reopening the app may offer **Continue reset** to finish the remaining steps. Some IR assignments may already be deleted.
5. When **Start pairing** appears, return to step 6 of this guide, then configure and save your button assignments again.

To remove the app and its remote setup, complete that reset first, close the app, then run on the Mac:

```sh
ares-install --device my-tv --remove org.magicsirimote.app
```

Uninstalling the app alone should not be treated as unpairing the remote or deleting its stored IR settings. Reset clears the active configuration but may retain inactive local recovery records; it is not secure erasure of diagnostic history.

## Source code and credits

Normal users can use the supplied IPK. Contributors can run the host checks from the repository root with `python3 src/check.py`, or build a package with `python3 src/build_integrated.py --out build/integrated`. Building requires Python 3 and Clang; the test runner also uses Node.js. Choose an output directory that does not already exist. Host tests do not establish compatibility with a new TV.

Further thanks to:

- [open-appleremote](https://github.com/a-funk/open-appleremote) and [SiriRemote-Linux](https://github.com/Yanndroid/SiriRemote-Linux) for Siri Remote protocol and input research.
- [Clean Your TV](https://github.com/Razdva122/clean-your-tv-lg-webos), [Homebrew Channel](https://github.com/webosbrew/webos-homebrew-channel), and [webOS Dev Manager](https://github.com/webosbrew/dev-manager-desktop) for webOS tooling and platform research.
- LG's [Bluetooth service](https://github.com/webosose/webos.service.bluetooth2), [Bluetooth SIL API](https://github.com/webosose/bluetooth-sil-api), [Luna Service 2](https://github.com/webosose/luna-service2), and [webOS TV documentation](https://webostv.developer.lge.com/) for platform interfaces and guidance.
- The Linux input, Python, Node.js and LLVM communities.

Project-authored code is available under the [MIT license](LICENSE). Upstream projects retain their own copyrights and licenses. These credits describe research and tooling contributions; they do not imply endorsement or that entire upstream packages are bundled. The download does not include TV firmware, LG native libraries, Python, Node.js, LLVM or captured Bluetooth traffic. This is an independent project, not an Apple or LG product.
