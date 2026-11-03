# Button assignments and infrared commands

Open **Button Assignments** in the [integrated native app](NATIVE_APP.md). The screen has
six rows: **Menu**, **TV / Control Center**, **Siri**, **Play/Pause**, **Volume Up**, and **Volume Down**.
Each row has a **Press** cell and a **Hold (~0.7 s)** cell. Surface clicking,
swipe navigation and gyro movement are separate from these six buttons.

## Change an assignment

1. Keep the paired Siri Remote awake and have the LG remote nearby.
2. Open **Button Assignments** and select the desired row and column. Use arrows or
   Siri Remote swipes and a click to select a cell.
3. Choose an action. Choices ending in **(IR)** send infrared from the remote.
   The other choices run on the TV. **Custom code (IR)** accepts exactly two
   hexadecimal digits, such as `08`, using the app keypad or a USB keyboard.
   **Done** finishes entry and returns directly to the assignment matrix; no
   second keyboard or Enter confirmation is needed.
4. Use **Back** to return to the first screen. Edits remain pending, including
   when you reopen Button Assignments. Selecting a value does not write it yet.
5. Choose **Save**, then **Save and restart** in the confirmation.
   Reception pauses during programming; use the LG remote until it restarts.
   On success, the window closes and reception resumes automatically.
6. Test each changed button. Delivery acknowledgement is not a readback of the
   remote's stored IR entry. If a batch fails partway through, completed slots
   stay saved and remaining edits stay pending. Unknown or partial outcomes stop
   the batch without automatic retry. Inspect the result before retrying.

Cancel in the restart confirmation changes nothing. Closing with pending edits
asks whether to discard them. Edits are held in memory, so an app termination
or TV restart before saving loses them.

**Do nothing** deletes the selected IR entry and disables its TV-side action.
It leaves other buttons and the other press type unchanged. For a button to
have no effect at either duration, set both cells to **Do nothing**.
Deleting cannot restore an overwritten previous value.

Choosing a TV action deletes that slot's competing IR entry. Choosing an IR
action sets that entry and disables its competing TV action. The app commits
the local mapping only after confirmed delivery and cleanup; if saving then
fails, it reports a partial result rather than claiming that both parts changed.

## Press and hold timing

TV actions run when the button is released. A hold of about 0.7 seconds selects
the hold action instead of the press action. Held buttons at connection start,
button combinations, and a press interrupted by reconnection do not become a
new button action.

**IR Press is immediate, not short-press-only.** The remote can send the Press
entry first and the Hold entry later during the same hold. A TV-side Hold action
cannot undo an IR Press command that was already transmitted. If only the hold
should act, set the Press cell to **Do nothing** first. The IR delay selectors
are `00` and `02`; arbitrary hold durations are not offered.

For unchanged buttons, the integrated runtime retains its normal TV actions:
MENU is Back, TV is Home, Mic is Screen off / restore, and Play / Pause toggles
playback. Unassigned holds retain the corresponding TV press behavior, except
TV hold is reserved for the remote's existing IR power action. Existing IR
settings remain untouched until its pending change is saved from the first screen.

## What the displayed values mean

The remote's production firmware does not provide a verified full IR-table
readback. An unchanged cell marked with `*` shows the TV default or **IR unknown**;
it does not assert that the remote has no IR command. A saved cell shows the
choice last submitted through this app, not an independent memory readback.
Opening this screen never resets entries or installs guessed factory defaults.

`state/ir-operation-*.json` records attempted IR operations. These private
receipts are not a backup of unknown entries. Known codes can be set again;
an unknown previous value cannot be reconstructed from a receipt.

The local `state/tv-assignments.json` uses schema 2 and keys such as `10:00`
(Mic / Press) and `10:02` (Mic / Hold). Values identify a TV action, `none`, or
an IR command such as `ir:08`. The receiver loads this file at session start.
Schema 1 came from a configuration-only preview and is not silently activated.
Saving a new assignment migrates to schema 2 without enabling those old choices.

## Available actions

TV actions are Back, Home, Settings, Play / Pause, and Screen off / restore.
Screen off / restore keeps audio playing and suppresses cursor/touch output
that would wake the picture; pressing its assigned button again restores it.

The named LG IR actions are Power on/off (`08`), Back (`28`), Home (`7C`),
Settings (`43`), Volume + (`02`), Volume - (`03`), Mute (`09`), Play (`B0`),
and Pause (`BA`). These are command choices, not factory defaults. Commands
and app support may differ between TVs. The encoder uses the tested LG NEC
format; entering a code does not make it a universal manufacturer selector.

The editor's six rows and both press types have offline coverage. This does
not establish that every assignment works on every remote and TV firmware.
The lower-level packet encoder still supports the surface-click selector for
explicit external tools; the app does not expose or modify it.

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
also be unconfirmed; the result reports that separately. If the final operation
record cannot be saved, the app preserves the delivery result and reports the
recording failure without retrying the remote write.

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
