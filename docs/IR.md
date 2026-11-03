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
5. Choose **Save and restart** on the first screen. It starts immediately and
   sends all twelve displayed assignments, including unchanged values and default
   **Do nothing** cells. No writes happen while browsing. Reception pauses during
   programming; use the LG remote until it restarts. On success, the window closes
   and reception resumes automatically.
6. Test each changed button. Delivery acknowledgement is not a readback of the
   remote's stored IR entry. If a batch fails partway through, completed slots
   stay saved and remaining edits stay pending. Unknown or partial outcomes stop
   the batch without automatic retry. Inspect the result before retrying.

Closing with pending edits asks whether to discard them. Edits are held in memory, so an app termination
or TV restart before saving loses them.

**Do nothing** deletes the selected IR entry and disables its TV-side action.
A full Save also resends the other displayed assignments. For a button to
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
cannot undo an IR Press command that was already transmitted.

**An IR Hold requires an IR Press on the same button.** On the tested A1513
Main0241 firmware, leaving only a delayed IR entry makes that command fire
immediately. In particular, **Home (TV)** / **Power (IR)** is unsafe: saving the
TV action deletes the immediate IR entry, so even a short press can turn the
TV off. Use **Home (IR)** / **Power on/off (IR)** for that combination.

The app rejects this unsafe pairing before stopping input or writing settings.
Unconfigured cells default to **Do nothing**, so a first Save includes the Hold
slot even when you only selected a Press action. Clearing both cells removes
Hold first; adding both IR cells writes Press first. An unconfirmed operation
stops the save. A hold-only action with **Do nothing** on Press is supported
for TV actions, not IR actions. The IR delay selectors are `00` and `02`;
arbitrary hold durations are not offered.

Unconfigured buttons have no TV-side action. Press and Hold are independent;
a configured Press does not imply a Hold action.

## What the displayed values mean

The remote's production firmware does not provide a verified full IR-table
readback. Each cell shows the saved app choice, a pending edit, or the default
**Do nothing**. Defaults are not a claim about the remote's current memory:
Save applies them and removes the corresponding IR entries. Opening the screen
or pairing does not perform these writes. Saved choices reflect acknowledged
requests, not an independent memory readback.

`state/ir-operation-*.json` records attempted IR operations. These private
receipts are not a backup of unknown entries. Known codes can be set again;
an unknown previous value cannot be reconstructed from a receipt.

The local `state/tv-assignments.json` uses schema 2 and keys such as `10:00`
(Mic / Press) and `10:02` (Mic / Hold). Values identify a TV action, `none`, or
an IR command such as `ir:08`. The receiver loads this file at session start.
Schema 1 came from a configuration-only preview and is not silently activated.
Saving a new assignment migrates to schema 2 without enabling those old choices.

## Available actions

TV action choices are Play / Pause and Screen off / restore.
Back and Settings are offered only as **Back (IR)** (`28`) and **Settings (IR)** (`43`).
Home is offered only as **Home (IR)**. A previously saved TV Home is shown as
**Home (legacy TV)** and remains unchanged until you select a replacement.
Screen off / restore keeps audio playing and suppresses cursor/touch output
that would wake the picture; pressing its assigned button again restores it.

The named LG IR actions are Power on/off (`08`), Back (`28`), Home (`7C`),
Settings (`43`), Volume + (`02`), and Volume - (`03`). Custom codes include
Mute (`09`), Play (`B0`), and Pause (`BA`). These are command choices, not factory defaults. Commands
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
sensor-state reads. Because webOS may return the existing input client, it keeps
that connection open for subsequent assignments and input resumption. It never disconnects
the whole HID link or changes pairing. On uncertain communication, cleanup may
also be unconfirmed; the result reports that separately. If the final operation
record cannot be saved, the app preserves the delivery result and reports the
recording failure without retrying the remote write.

The configuration path and bytes were used in earlier targeted Bluetooth
procedures. Their integration into this generic app still needs an on-TV test,
including service permissions, settings persistence, receipt storage and
retention of the existing Bluetooth connection. There is no automatic runtime pause/resume integration yet.
A configuration transport error does not trigger a permission change, a UART
fallback, a sensor stop, or a repeated IR write.

DCSD diagnostic access is a separate path used during development. Its UART
commands differ from the Bluetooth reports above. Neither that cable nor this
app currently provides a verified complete IR-table backup procedure.

## Timing and Home

The delay selector is a firmware setting, not seconds. Selector `02` gives a hold threshold of approximately 0.7 seconds on the tested firmware. This is the hold threshold, while the TV may need longer to show a picture.

Home (IR) sends immediately. Holding that button can first reach Home, then
send the delayed power command. The corresponding TV action is disabled so
the app does not also send Home over Bluetooth.

MENU → Back and microphone → Back are mappings in the TV input program. They do not require corresponding IR entries in the remote.


## Repeated saves and memory wear

A confirmed Save sends the displayed known assignments again, even if only one
value changed. It does not run on startup, reconnection or slider movement.
IR set/delete commands update the remote's persistent settings; those memories
have finite write endurance. The application cannot measure remaining endurance
or equate one Save with a specified number of internal erase cycles. Avoid
repeatedly saving as a connectivity test. **Reset cursor orientation** restarts
input without sending IR configuration and does not rewrite the remote's IR table.
