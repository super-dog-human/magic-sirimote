# Magic Sirimote

Magic Sirimote lets a first-generation Siri Remote control an LG webOS TV. Install one app on the TV, pair the remote in that app, and choose your button assignments. **Your Mac does not need to stay on after setup. No Apple TV is needed.**

- Move the TV pointer by turning the remote with **gyro pointer control**.
- Swipe the touch surface to navigate up, down, left, or right, and press it to select.
- Assign separate press and hold actions to six buttons, including infrared power and volume, media controls, and screen off / restore.

https://github.com/user-attachments/assets/53afcba6-bafb-4899-95ed-cc63cad6117a

This is an experimental community project with limited hardware testing. Reconnection and recovery are still being improved. Keep the original LG remote available.

- [Compatibility and requirements](#compatibility-and-requirements)
- [Set up from a Mac](#set-up-from-a-mac)
- [Using the remote](#using-the-remote)
- [Troubleshooting](#troubleshooting)
- [Optional firmware update](#optional-firmware-update)
- [Reset or uninstall](#reset-or-uninstall)
- [Development and acknowledgments](#development-and-acknowledgments)

## Compatibility and requirements

### Tested hardware

| Component | Tested model or version |
| --- | --- |
| Siri Remote | First generation, black, **A1513** and **A1962** |
| LG TV | **LG G3 — OLED55G3PJA** |
| webOS platform version | **11.2.0** (`sdkVersion`) |
| TV firmware | **43.21.96** |

These are tested examples, not a model or firmware allowlist. The app and TV-side fix do not require these specific LG versions. The installer checks compatibility and explains any missing requirement.

The webOS platform version and TV firmware version are different values. You do not need to look up the remote's firmware before starting; the app verifies its identity during setup.

Both models have been tested for pairing, infrared assignments, swipes, touch-surface clicks, and gyro pointer control. Later, silver Siri Remote generations are not supported.

<details>
<summary>Technical requirements on the TV</summary>

This ARM package currently needs a 32-bit ARM Python 3.10+ runtime, Luna Service 2, GLib, SDL2 and SDL2_ttf on the TV; input also depends on the TV's Bluetooth and input-device APIs. Other webOS environments may need a matching build or platform support.

</details>

## Set up from a Mac

**Use Magic Sirimote to pair the remote. The TV's standard Bluetooth device settings cannot complete the Siri Remote pairing used by this app.**

For TV app setup, do not pair Siri Remote with the Mac. The Mac installs the app; the TV app pairs directly with Siri Remote. You will enter the TV's network IP address on the Mac. The optional firmware updater has its own connection procedure.

### 1. Install the Mac tools

Install the current **LTS version of [Node.js with npm](https://nodejs.org/en/download)**, then reopen Terminal. Node.js 20 or newer is required by the webOS command-line tools.

The installer checks for LG's **[webOS CLI](https://github.com/webos-tools/cli)** and offers to install it automatically with npm if it is missing. If you prefer to install it beforehand:

```sh
npm install --global @webos-tools/cli
```

The other tools (`curl`, `tar`, and, for the optional TV-side fix, `ssh`) are included with macOS. Missing tools and installation failures are explained before continuing.

### 2. Prepare Developer Mode on the TV

1. Create an account on the [LG webOS TV Developer website](https://webostv.developer.lge.com/) if you do not have one.
2. Install **Developer Mode** from the TV's app store, open it and sign in.
3. Turn **Dev Mode Status** on. Initial activation requires the TV restart requested by LG. **If it is already on, leave it on.**
4. Open Developer Mode and turn **Key Server** on. Keep its **IP address** and **passphrase** available for the installer.
5. Connect the Mac and TV to the same local network.

See [LG's Developer Mode guide](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app) if the TV needs help completing this step.

### 3. Run the installer

Paste this into Terminal to download and run the interactive installer:

```sh
curl --fail --location --output install.sh https://raw.githubusercontent.com/super-dog-human/magic-sirimote/main/install.sh && sh install.sh
```

Choose **Install/update app**. Enter the TV's IP address when asked; press Return to accept the suggested port. The installer reuses a matching saved connection or creates one. If a key is needed, enter the passphrase shown in Developer Mode, **not your LG account password**.

The installer checks compatibility, verifies the download, installs the IPK and verifies the installed files. When updating, it first asks you to close unsaved settings and wake Siri Remote so the running app can stop cleanly.

The **TV-side input-device fix** prevents input loss after repeated Bluetooth reconnections. When offered, choose the fix, then **1: Temporary access**. Keep the Mac and TV on while setup runs; allow local network access if macOS asks. The installer obtains temporary access, applies the fix and removes its temporary service automatically. It does not install permanent root access.

Temporary access depends on the TV’s available browser and service permissions, so it cannot work on every webOS version. If unavailable, use **2: Existing root SSH** if you already have it, or skip the fix and install only the app. The Developer Mode passphrase is not a root SSH password. No model or firmware allowlist is used.

The fix changes LG's handling of A1513/A1962 outside this app as well; other remote models pass through. Applying or removing it briefly restarts the input service, **not the TV**. It checks the service's interfaces and storage rather than requiring a particular TV model or firmware. Without the fix, the repeated-reconnection problem may recur. See [Reset or uninstall](#reset-or-uninstall) to remove it.

When installation finishes, Magic Sirimote opens on the TV. The installer does not reboot the TV. Run `sh install.sh` again to update, or use [uninstall.sh](#reset-or-uninstall) to remove the app and TV-side fix.

### 4. Pair Siri Remote with the TV

Open **Magic Sirimote** on the TV. If it is not already open, select this icon from the TV's Home screen:

![Magic Sirimote app icon](assets/app-icon.png)

![Pairing start screen](assets/screenshots/pairing.png)

The app shows **Pair a Siri Remote**. If it opens the settings screen instead, continue to [Choose all of your button assignments](#5-choose-all-of-your-button-assignments).

1. On the TV, choose **Start pairing** with the LG remote.
2. Wait until the app starts searching. **Start the search before pressing the pairing buttons.**
3. Hold Siri Remote near the TV. Press and hold **MENU and Volume Up (+) together for about five seconds**, then release both.
4. The app automatically pairs with the first available supported Siri Remote it finds. **Put only the remote you want to use into pairing mode.** If this app already has a saved remote, the search stays restricted to that remote.
5. Wait while the app verifies the remote and prepares input. On success, it saves the connection information and closes the window to start reception. If the search expires, choose **Search again** and repeat the pairing-button sequence.
6. Press Siri Remote's touch surface once to wake it. Try swiping to move the TV's selection, then pressing and releasing the surface to select an item.

<details>
<summary>Connection check and search screens</summary>

![Checking the remote connection](assets/screenshots/checking.png)

![Searching for a Siri Remote](assets/screenshots/searching.png)

![Automatic pairing and verification](assets/screenshots/automatic-pairing.png)

</details>

If the app reports an error or no candidate appears, see [Pairing problems](docs/troubleshooting.md#pairing-problems).

### 5. Choose all of your button assignments

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

### 6. Save your settings

1. Press **Back** to return to the first settings screen. Your button edits remain pending.
2. Leave **Gyro cursor** on if you want pointer control.
3. Choose **Save and restart**. The app applies your edited assignments and restarts reception.
4. Wait for the window to close, then use Siri Remote.

If saving fails partway through, some assignments may already have changed. Read the displayed result and press Siri Remote's touch surface once to wake it before retrying. Selecting a choice or leaving the editor with Back does not itself save anything. **Close** asks whether to discard unsaved edits, then returns to Home. Back from the first settings screen also returns to Home.

<details>
<summary>Unsaved changes confirmation</summary>

![Discarding unsaved changes](assets/screenshots/discard.png)

</details>

## Using the remote

With **Gyro cursor** enabled, keep your finger off the touch surface and turn the remote to move the pointer. Press and release the touch surface to select the item under the pointer.

Swiping switches to directional navigation. Subsequent swipes move the TV's selection, and pressing the surface selects the focused item. To return to pointer control, lift your finger and shake the remote side to side; an up-and-down shake does not switch modes.

To change button assignments, toggle **Gyro cursor**, or adjust pointer sensitivity, reopen Magic Sirimote from the TV's Home screen with the LG remote. Choose **Save and restart** to apply changes.

## Troubleshooting

[Troubleshooting guide](docs/troubleshooting.md)

## Optional firmware update

Remote firmware updating is separate from installing or updating the TV app and is not required for setup. The [experimental macOS firmware updater](docs/firmware-update.md) supports only the documented **A1513** version transition. **A1962, the black remote with a white ring around MENU, is not supported by the updater**, even though the TV app supports both models. Read the separate guide before using it.

## Reset or uninstall

### Reset pairing and assignments

**Reset app is destructive.** It removes this remote's TV pairing, the app's active settings, and all short- and long-press infrared assignments on the remote, including power and volume. It also clears the surface-click IR entries, which are not exposed in the six-row editor. It does not reset the TV or remove other Bluetooth devices. It is not a factory-firmware reset of Siri Remote.

To start over:

1. Have the original LG remote ready, then press Siri Remote's touch surface once to wake it.
2. Open Magic Sirimote and choose **Reset app**.
3. Read the confirmation. Choose **Cancel** to leave things unchanged, or **Reset everything** to proceed.
4. Let the reset finish. If it stops partway through, read the error and choose **Continue reset** to finish the remaining steps. Keep Siri Remote awake and disconnect it from any Mac used for a firmware update. If the TV retains a bond that no longer connects, the app can remove that saved bond and search for the same remote: when instructed, hold **MENU + Volume Up** for about five seconds. It verifies the saved address and serial before continuing IR deletion. Until deletion is acknowledged, it keeps the reset pending and does not report success. Some IR assignments may already be deleted.
5. When **Start pairing** appears, follow [Pair Siri Remote with the TV](#4-pair-siri-remote-with-the-tv), then configure and save your button assignments again.

<details>
<summary>Reset confirmation screen</summary>

![Resetting Magic Sirimote](assets/screenshots/reset.png)

</details>

### Uninstall the app and TV-side fix

To uninstall Magic Sirimote and its TV-side fix, run this on the Mac:

```sh
curl --fail --location --output uninstall.sh https://raw.githubusercontent.com/super-dog-human/magic-sirimote/main/uninstall.sh && sh uninstall.sh
```

Use the same [Mac tools](#1-install-the-mac-tools) as for installation. Enter the TV's IP address and confirm removal. The uninstaller checks for the TV-side fix and removes it automatically if present, then removes the app and verifies the result. It also works if you already deleted the app from the Home screen.

**Choose 1: Temporary access** to check and remove the TV-side fix without setting up root SSH. If temporary access is unavailable, choose **2: Existing root SSH**. Without either method, you can explicitly choose app-only removal; TV-side cleanup is reported as **incomplete**. If setup was interrupted, run the script again to finish removing its temporary service. If the fix’s files have changed or cleanup fails, the script explains what remains.

If you also want to erase the remote's pairing and infrared assignments, complete **Reset app** before uninstalling. Uninstalling alone preserves those assignments.

You can still delete just the app using **Edit App List → Delete** on the TV's Home screen. This does not remove the TV-side fix; run `sh uninstall.sh` afterwards to clean it up. Removing the fix briefly restarts only the input service, not the TV.

Uninstalling the app alone should not be treated as unpairing the remote or deleting its stored IR settings. Reset clears the active configuration but may retain inactive local recovery records; it is not secure erasure of diagnostic history.

## Development and acknowledgments

**This project was developed through Vibe Coding:** an AI coding agent wrote and revised the code, with a human directing the work and testing it on real hardware.

Thank you to the open-source Siri Remote and LG webOS communities for the tools, code and discoveries that made this possible. In particular, this project owes much to [open-appleremote](https://github.com/a-funk/open-appleremote), [SiriRemote-Linux](https://github.com/Yanndroid/SiriRemote-Linux), [Clean Your TV](https://github.com/Razdva122/clean-your-tv-lg-webos), [webOSbrew](https://www.webosbrew.org/), and the temporary LS2 access research in [webos-ls2-root](https://github.com/bbo76/webos-ls2-root).
