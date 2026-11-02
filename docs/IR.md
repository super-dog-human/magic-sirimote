# Infrared assignments: set and delete

The A1513 can store IR commands and transmit them without the TV's Bluetooth input program. This is how the tested setup handles volume and power, including powering the TV on while the receiver program is not processing input.

The [native setup app](NATIVE_APP.md) includes an **Infrared** screen with explicit
**Set (IR)** and **Delete (IR)** actions. Version 0.2.2 has passed offline transaction and UI
tests; the new screen and its native Bluetooth transport still need hardware
validation. Installing or opening the app never programs the remote.

## Use the Infrared screen

1. Save the correct device identities on the setup screen. Pairing and an
   existing HID/GATT connection are prerequisites; this screen does not pair.
2. Stop the input runtime and its automatic restarts through the existing
   deployment procedure. The screen refuses to operate while another project
   app is running or the remote's motion sensors are active. It does not stop
   an existing installation for you. Use the original LG remote for setup.
3. Open **Infrared**, select **Button (IR)** and choose a physical button
   from the list: TV / Home, Volume +, Volume −, Play / Pause, Microphone,
   MENU, or Surface click. All seven buttons have the same Set/Delete options.
   Select **Press** and choose **Normal press (immediate)** or
   **Long press (about 0.7 seconds)**. These are separate stored entries;
   selecting or cancelling either list does not send a request.
4. Select **Action** and choose a named action such as **Power on/off (IR)**
   or **Back (IR)**. Alternatively, choose **Enter code directly (IR)** and
   enter exactly two hexadecimal digits (`00`–`FF`) using the on-screen keys,
   then select **Done**. Select **Set (IR)**, review the button, press type and
   action, then confirm with **Set (IR)**. Choosing an action alone sends nothing.
5. To remove that entry, select **Delete (IR)** and confirm with **Delete (IR)**.
   No action code is needed. Other buttons and delay selectors are untouched.
6. Test the button physically. A TV service acknowledgement is shown as
   **Request sent**, not proof that the remote saved the entry. An interrupted
   or missing acknowledgement is shown as unknown and never retried automatically.

**Normal press is immediate, not “short press only.”** If both normal and
long-press entries are set, holding a button can send the normal command first
and the long-press command later. To make a button send only a long-press IR
command, delete its normal-press IR entry separately. This does not remove any
Bluetooth action. The two choices use firmware selectors `00` and `02`;
the app does not offer arbitrary hold times.

The editor supports all seven button selectors and both press types; this does
not mean every combination has been tested on hardware. Surface click means
physically pressing the touch surface. Touching or swiping is not an IR button
entry, and this screen does not remap those gestures.

The named choices are Power on/off (`08`), Back (`28`), Home (`7C`),
Settings (`43`), Volume + (`02`), Volume − (`03`), Mute (`09`), Play (`B0`)
and Pause (`BA`). These are LG command choices, not settings read from your
remote or factory defaults. Support depends on the TV and active app; Play
and Pause are separate commands. See the [LG IR code reference](https://gscs-b2c.lge.com/open/downloadFile?fileId=JzkdczeDuzRq6UZINzzTJw).

The screen currently encodes LG TV commands using the tested NEC format. It
is not a universal manufacturer selector. A command code alone does not
identify the complete IR signal for other brands.

**Delete removes an assignment; it does not restore its previous value.**
It does not disable Bluetooth button reports or change the TV runtime's button
mapping. Deleting an immediate entry also does not delete a held-button entry.
The app never clears the entire IR table and never automatically deletes before
setting: Set replaces/adds only the selected button/delay entry.

Current IR settings cannot be read back through the verified public workflow
on this locked firmware. The app does not require an unavailable full-table
backup, invent factory defaults, or present saved operation receipts as remote
readback. Receipts in `state/ir-operation-*.json` record what this app attempted;
keep them private. Known code/selector values can be set again, but an unknown
previous assignment cannot be reconstructed from a receipt.

## Packet reference

`src/ir_packets.py` is still a pure encoder: running it prints examples and
never transmits. The native app uses this encoder with a separate, explicitly
invoked transport. That transport checks the saved remote/adapter identity,
remote serial, exact supported firmware, feature report, and stopped sensor
mode before sending one persistent request. A private lock serializes this
app's operations; process checks detect the legacy project apps. These are
cooperative checks, not exclusion of all possible third-party Bluetooth tools.
Do not run another configuration tool simultaneously.

## Working entries

| Button mask | Delay selector | Command bytes | Meaning on the tested LG TV |
| --- | --- | --- | --- |
| `02` | `00` | `20 DF 40 BF` | Volume up |
| `04` | `00` | `20 DF C0 3F` | Volume down |
| `01` | `00` | `20 DF 3E C1` | Home |
| `01` | `02` | `20 DF 10 EF` | Power toggle after approximately 0.716 seconds |

The configuration report used was:

```text
F0 01 BUTTON DELAY 01 00 00 00 00 00 NEC_BYTE_0 NEC_BYTE_1 NEC_BYTE_2 NEC_BYTE_3
```

The selective deletion report used was:

```text
F0 02 BUTTON DELAY
```

These formats and timings describe this A1513 firmware, not every Siri Remote. Do not replace a four-byte command with a byte-reversed integer copied from an unrelated IR library. The bytes above are in the order used by the tested configuration reports.

## Transport and validation limits

The app calls the TV Bluetooth service as its own native app account, without
root or a system-service identity. It obtains a GATT client for identity and
sensor-state reads and releases that client afterwards. It never disconnects
the whole HID link or changes pairing. On uncertain communication, cleanup may
also be unconfirmed; the result reports that separately.

The configuration path and bytes were used in earlier targeted Bluetooth
procedures. Their integration into this generic app still needs an on-TV test,
including service permissions, settings persistence, receipt storage and
connection cleanup. There is no automatic runtime pause/resume integration yet.
A configuration transport error does not trigger a permission change, a UART
fallback, a sensor stop, or a repeated IR write.

DCSD diagnostic access is a separate path used during development. Its UART
commands differ from the Bluetooth reports above. Neither that cable nor this
app currently provides a verified complete IR-table backup procedure.

## Timing and two routes for Home

The delay selector is a firmware setting, not seconds. Selector `02` gives a hold threshold of approximately 0.7 seconds on the tested firmware. This is the hold threshold, while the TV may need longer to show a picture.

The working remote also has an immediate IR Home entry, and the Bluetooth decoder maps the TV button to Home. A long press may therefore reach Home before the delayed power command. The two routes do not guarantee mutually exclusive short-press and long-press actions.

MENU → Back and microphone → Back are mappings in the TV input program. They do not require corresponding IR entries in the remote.
