# Porting and deployment checkpoints

This document distinguishes the successful private installation from what a new checkout can reproduce. It is an engineering guide for completing a port, not a claim that installation is automatic.

## What is reproducible now

- Run the input and scheduler host tests.
- Build all three IPKs without any files from the author's computer.
- Substitute device identities and three measured role UIDs during the build.
- Inspect complete runtime and scheduler sources, including session lifecycle handling.

## What is not a completed public workflow

A clean-TV installation has not been re-run from this export. The [setup audit](../reviews/setup-audit.md) lists each missing operation and the first-install dependency cycle. First pairing, discovering app runtime UIDs without starting input, permission validation, an operator-friendly provisioning/status tool, and a general IR backup/programming tool are still missing. These are real deployment prerequisites, not optional documentation details.

The three IPKs are useful build artifacts for a developer completing those checks. They are not a universal consumer release. The source can also be reused independently—for example, the decoder, button mapping, navigation state machine, and output framing.

## Export changes compared with the accepted installation

The baseline was controller/receiver 0.9.71 and scheduler 0.0.64. The owner physically accepted MENU → Settings and microphone → Back on November 2, 2026.

The public export:

1. Replaces the owner's remote/adapter addresses and remote serial with example identities. `src/build.py` substitutes the local configuration when building.
2. Substitutes measured developer/controller/receiver UIDs in the packaged sources. Source defaults and old test fixtures retain baseline numeric IDs.
3. Replaces machine-specific build dependencies with local `build_support.py` and a single three-package builder.
4. Regenerates controller and receiver hash pins together.
5. Defaults Developer Mode maintenance to disabled through `expiry-policy.js`. The original scheduler's extension implementation is retained behind that explicit policy.
6. Adds configuration validation, packet inspection, an environment metadata tool, and publication tests.
7. Updates outdated docstrings and removes obsolete experiment-specific repair paths. The cleaned source builds controller/receiver **0.9.72** and scheduler **0.0.65**.
8. Moves scheduler tests into `tests/scheduler`, removes the duplicate session-policy helper, and extracts the unchanged active HID helpers from the old standalone experiment into `hid_input.py`.
9. Requires an explicit `runtime-files.json` inventory and checks that all runtime modules are reachable through imports from the two native entrypoints. Package pins are generated, not stored as stale source.
10. Blocks startup if retired development requests remain, leaving them untouched for reconciliation.

No new public package was installed on the owner's TV as part of publishing this repository. The baseline's physical acceptance therefore does **not** certify all these export changes on hardware. See `reviews/verification.md` for host checks actually performed.

`docs/source-provenance.json` maps exported files to hashes of the baseline sources. Its initial-export hashes are provenance, not the current package pins. Removed-file entries are available in Git history; moved files retain their original export path. Build manifests are the authority for generated package contents.

## Fixed platform assumptions

Changing the JSON config does not change every platform assumption:

| Area | Assumption in this reference |
| --- | --- |
| CPU/input ABI | ARM32; `struct input_event` represented by `=iiHHi` |
| Native launch | Small ARM ELF executable calls `/usr/bin/python3 -I -B .../native_probe.py` |
| Startup app | ARM ELF calls `/usr/bin/node .../main.js` with `NODE_PATH=/usr/lib/nodejs:/usr/lib/node_modules` |
| Python runtime | Existing TV Python **3.10+**, Linux `fcntl`, `ctypes`, and `/proc`; the source evaluates `str | None` / `float | None` annotations |
| Native libraries | Existing `libluna-service2.so.3`, `libglib-2.0.so.0` |
| JavaScript platform | Existing `palmbus` under the native app/service identity |
| App root | `/media/developer/apps/usr/palm/applications` |
| State parent | Package-owned UID 5999 / GID 5000, mode 0770; some validated boot paths accept 0775 |
| Runtime group | GID 5000; process must be unprivileged with zero effective capabilities |
| Native input | Unique, capability-checked `LGE RCU` and `ClickableMouse`; no fixed event number |
| System key device | `LGE RCU`: device major 13, owner 0:505, mode 0660, input ID `(bus=3, vendor=1, product=1, version=4)` |
| Remote input | Matching HID identity and the validated A1513 report shapes; live path observed 21-byte `FC` reports |
| Feature control | Cooperative session serialization; not proof that every other process on the TV is excluded |
| Startup | webOS Activity Manager and application/service identity checks |

Do not weaken a failed identity/capability check just to obtain input. Investigate whether the new platform legitimately differs, update that assumption deliberately, and add a matching test.

### Declared service permissions

The public builder preserves these declared access-control groups:

- Controller: `bluetooth.query`, `application.launcher`.
- Receiver: `bluetooth.query`.
- Startup app/service: `activity.operation`, `application.launcher`, `configurator.callbacks`.

These declarations do not guarantee access to every internal operation on every firmware. A command that works in a developer SSH session may fail in an app, and the reverse can also happen. Validate under the actual native app identity. Do not impersonate a system service.

The runtime uses the existing Bluetooth service for status, connection management, notification configuration, input activation and sensor-mode reads/writes. Pairing is a prerequisite; this export does not call a generic pairing wizard. See [README Step 2](../README.md#step-2-establish-bluetooth-pairing) for the observed DCSD-assisted registration repair and its limits. This work used an outgoing TV pairing request, remote-side peer selection through the diagnostic console, an HID connection, and input initialization; it was not just a Bluetooth menu selection. A fresh pairing workflow and a cable-free first-time setup remain unvalidated.

### Initial account and device inventory

`src/tv_inventory.py` reads environment metadata only. Review it, transfer it with your developer tooling, and run it with the TV's Python. It does not open input streams, connect Bluetooth, or read Developer Mode credentials.

An SSH invocation reports the **developer connection's** identity. It cannot establish the groups or permissions of a future native app. Likewise, the installed files' owner is not necessarily the native process UID. A clean-install helper must inspect native app allocation using an inert entrypoint, then rebuild with those verified IDs before starting input. That helper is not provided here.

The target profile is deliberately narrow. Existing Bluetooth pairing must match both the remote address and its observed name/serial, and replies must match the TV adapter. Do not copy another person's Bluetooth pairing database.

## Startup provisioning

The installed scheduler can serve package pins before a startup Activity is provisioned. A controller can therefore be launched manually for a first test without registering automatic startup.

The lifecycle for a **fresh, verified** startup registration is implemented in `src/scheduler/main.js` and `creator.js`:

1. Confirm the installed controller and receiver match the newly generated pins.
2. Confirm the scheduler state directory has the intended ownership and access. Check there are no prior or ambiguous registration records.
3. The developer identity publishes a single `intentional-action.json` in the scheduler's `state` directory. It must be a regular, non-symlink file, owned by the configured developer UID, group 5000, mode 0640, at most 1024 bytes.
4. The request has exactly the intended app ID, `action: "provision"`, `experimentalIntent: "enable-experimental-tv-local-startup"`, a newly generated 32-character lowercase hex `operationId`, and a millisecond expiry no more than five minutes ahead. See `main.js` for the validation contract. Never copy a request from a previous run.
5. Launch the scheduler app under its own native identity. It creates private creator state, authenticates preparation with its service, creates one persistent Activity by name, and binds the returned Activity ID.
6. Check both the creator's result and the service's authenticated callback result. The initial callback is scheduled about two minutes ahead; subsequent callbacks are rearmed about a minute ahead. An acknowledgement is not proof of successful startup or input.
7. Once the request's outcome is fully verified, archive the exact request rather than leaving an expired `intentional-action.json` in the dispatch path. Keep the creator receipts and service binding state. These have different purposes.
8. Perform ordinary standby and full-restart tests without manually launching the controller.

This request contract is documentation for an installer author. There is deliberately no copied live request or credential-bearing Activity binding in the repository. The old working installation's numeric Activity ID is not portable.

If creation or binding times out, **do not immediately retry** or invent an Activity ID. The operation may already have happened. Reconcile the returned records with the Activity and creator identity first.

### Private records

A creator receipt can contain a run identifier, nonce, and callback authentication token. Do not post the complete receipt publicly. For bug reports, use status-only results, remove device identities, and review every file before attaching it. A file named `manifest.json` generated by the builder contains local device configuration too; keep it private unless redacted.

## Stopping, updating, and removing

The controller's `stop_request.py` defines a cooperative stop protocol:

1. Identify the live controller instance from its instance record **and** verify the corresponding process start ticks. A stale PID alone is insufficient.
2. Publish a complete, exact-instance `developer-stop-<instance>.json` atomically under the developer UID. The validated fields are schema, action, PID, process start ticks, and instance. Use `publish_request` only after checking the live process.
3. Wait for the controller/receiver to finish and verify the matching receiver result, including `sensorStopVerified: true`, `journalArchived: true`, and process exit.
4. Preserve the stop request while maintaining or replacing packages; it is a deliberate veto on automatic resume.
5. Before resuming, reconcile and archive only the completed stop/request records whose identities and result hashes have been checked. Do not clear the entire state directory.

The startup creator's cancellation path first disarms its exact service binding, then cancels the exact Activity name under the original creator identity. A prior rearm operation may have changed the active binding; inspect the real receipts rather than assuming `creator-private/created.json` is still current.

After verified disarm/cancellation, verified sensor stop, and verified process exit, the installed packages can be removed:

```sh
ares-install --device my-tv --remove org.codex.siriremote.autocoord20261029v
ares-install --device my-tv --remove org.codex.siriremote.hidgattrouterb20261029u
ares-install --device my-tv --remove org.codex.siriremote.v20scheduler20261031a
```

These commands remove the TV apps, not the remote's IR settings. Do not execute them as a substitute for the stop/cancel checks above.

### Removed development requests

The public cleanup removes the old run-specific repair/archive handlers and the scheduler handler tied to an old numeric Activity ID. These are available in Git history at commit `8651328`; they are not included in new packages.

The native entrypoints now reject these **unarchived request filenames** before opening an input session:

- `handoff-diagnostic-request.json`
- `owner-mode-repair-request.json`
- `serial-zero-archive-request.json` and `serial-zero-archive-v2-request.json`
- `serial-zero-archive-next-request.json` and `serial-zero-archive-next-v2-request.json`
- `maintenance-inspection-request.json`
- `generic-presensor-request-<run>.json` or `generic-presensor-request-<run>-<operation>.json`

The scheduler similarly refuses a retained `maintenance-request.json`. This includes dangling symlinks. Records are not read, deleted, or replayed by this check, and even expired requests require review. Confirm the old operation's outcome using the retained baseline and reconcile/archive the exact request before upgrading. Do not clear a whole state directory to bypass the check.

Ordinary `recovery-request.json`, controller stop requests, session journals, startup cancellation, rearming, and standby recovery remain part of the supported lifecycle. They are **not** treated as retired experiment requests.

## Why touch plus pointer motion remains separate

In the accepted LG input path, reports observed by the normal receiver were 21 bytes long. With no touch, the available prefix contains useful orientation information. With touch present, enough touch data arrives for navigation, but the complete orientation payload was not available in that path.

A bounded attempt to change the transport MTU did not recover a usable complete stream; normal input degraded and the earlier behavior was restored. This is not proof that simultaneous touch and orientation is impossible, nor proof that all firmware truncates data in the same way. It is the reason this release does not fabricate missing sensor fields or enable unvalidated touch-time pointer movement.

Several historical algorithm result flags still say `physicalAxesValidated: false` or `complete_sensor_report: false`. The latter correctly describes the limited packet view; the former is a conservative module-level flag, not a live report that the owner's pointer test failed. Physical acceptance is documented separately in the README.
