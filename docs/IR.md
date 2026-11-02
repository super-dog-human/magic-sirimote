# Infrared assignments: set and delete

The A1513 can store IR commands and transmit them without the TV's Bluetooth input program. This is how the tested setup handles volume and power, including powering the TV on while the receiver program is not processing input.

The [native setup app](NATIVE_APP.md) includes an **Infrared** screen with explicit
**Set** and **Delete** actions. Version 0.2.0 has passed offline transaction and UI
tests; the new screen and its native Bluetooth transport still need hardware
validation. Installing or opening the app never programs the remote.

## Use the Infrared screen

1. Save the correct device identities on the setup screen. Pairing and an
   existing HID/GATT connection are prerequisites; this screen does not pair.
2. Stop the input runtime and its automatic restarts through the existing
   deployment procedure. The screen refuses to operate while another project
   app is running or the remote's motion sensors are active. It does not stop
   an existing installation for you. Use the original LG remote for setup.
3. Open **Infrared**. Select the physical button and **Immediate (00)** or
   **Hold about 0.7 seconds (02)**. These are separate stored entries.
4. To assign an LG action, enter its two-digit hexadecimal code, select **Set**,
   review the selected button and press type, then select **Set assignment**.
   Examples: `02` volume up, `03` volume down, `08` power, `43` settings, `7C` home.
5. To remove that entry, select **Delete**, then **Delete assignment**. No
   action code is needed. Other buttons and delay selectors are untouched.
6. Test the button physically. A TV service acknowledgement is shown as
   **Request sent**, not proof that the remote saved the entry. An interrupted
   or missing acknowledgement is shown as unknown and never retried automatically.

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
