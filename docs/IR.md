# Infrared configuration: preserve before changing

The A1513 can store IR commands and transmit them without the TV's Bluetooth input program. This is how the tested setup handles volume and power, including powering the TV on while the receiver program is not processing input.

This repository includes `src/ir_packets.py`, a **pure encoder** for the observed configuration packet format. It prints examples. It never connects to a remote or transmits a packet.

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

## What a real programmer must do

1. Verify the remote model, firmware, address, and current connection independently.
2. Read and privately save **all existing IR entries** and any relevant enable/configuration flags, together with enough identity information to know which device the backup belongs to.
3. Cleanly stop the TV input session and verify the remote's sensor mode is stopped. An unresponsive Bluetooth query is not proof of a stopped sensor.
4. Review a diff containing only the intended IR entry changes. Preserve unrelated entries and the immediate Home entry when adjusting the power hold time.
5. Send each intended change once. An absent response means uncertainty, not permission to replay it.
6. Read back the settings and compare them with the intended result.
7. Test IR with the TV input program still stopped: volume up/down, short Home, and delayed power.
8. Keep the original entries and the readback result privately for rollback.

The private development tools bound every write to the particular remote, firmware, stopped-session evidence, and previous entry. Those device-specific mutation scripts are **not** published as a universal writer; removing their bindings would not create a reliable installer.

A standard USB charging cable is not a diagnostic cable. If a future port needs diagnostic serial access, document the correct hardware and electrical interface separately rather than assuming any Lightning cable will work.

## Timing and two routes for Home

The delay selector is a firmware setting, not seconds. The owner tried longer settings, then accepted selector `02` at about 0.7 seconds. This is the hold threshold, while the TV may need longer to show a picture.

The working remote also has an immediate IR Home entry, and the Bluetooth decoder maps the TV button to Home. A long press may therefore reach Home before the delayed power command. The successful physical tests establish the accepted user experience on the tested setup; they do not establish a universally exclusive short/long-press implementation.

MENU and microphone remapping in version 0.9.71 was performed in the TV input program. It did not rewrite IR settings. An older development configuration had MENU assigned to Settings over IR; do not infer that it is still present in the final remote's IR table.
