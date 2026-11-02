# Fresh-install reproducibility audit

Date: November 2, 2026. Code baseline: `a96a93b`. Scope: read the public guide in order, trace each required operation to the exported implementation, compare the recorded owner setup, and run host checks from a clean Git export. No TV or remote was contacted or changed.

## Verdict

**The guide cannot yet reproduce the owner's complete environment from an unprepared TV and remote, even with the same models and firmware.** The runtime and package builder are available; several installation and maintenance operations still exist only as device-specific development procedures or engineering contracts. A working owner installation is not evidence that the public installation path is complete.

## Findings by stage

| Stage | Evidence in the repository | Finding and effect |
| --- | --- | --- |
| Computer prerequisites | [Runtime lifecycle](../src/runtime/lifecycle.py), [GATT reader](../src/runtime/direct_gatt_read.py) | Both evaluate union type annotations without postponed evaluation. The source requires Python 3.10+ on the computer and TV. Minimum-version execution itself was not tested in this audit. |
| Developer connection | README developer connection steps | CLI installation, interactive TV registration, key retrieval and connection checks follow LG's official guides. These prepare developer access, not remote pairing or native permissions. |
| Bluetooth pairing | [README pairing history](../README.md#step-2-establish-bluetooth-pairing); no exported pairing command | The historical DCSD-assisted repair coordinated TV pairing, remote peer selection, HID connection and input initialization. A general first-pairing tool and validation are missing. A reader cannot execute the historical outline with the current checkout alone. |
| Identity collection | [Metadata reader](../src/tv_inventory.py) | Reports only current-process identity, machine/word size, executable presence and selected node metadata. It does not retrieve Bluetooth identities, firmware, app runtime UIDs or interpreter versions, or prove native app/service access. |
| App identities before build | [Configuration validation](../src/build.py), [example configuration](../config.example.json) | Builder requires three measured role UIDs before producing the final packages. The guide installed those apps only afterward. An inert bootstrap installation and identity-discovery/update procedure is missing. File owner, SSH UID and native app runtime UID are different concepts. |
| Native access and dependencies | [Native identity check](../src/runtime/native_app_identity.py), [HID access](../src/runtime/hid_input.py), [output access](../src/runtime/output_devices.py), [system keys](../src/runtime/system_key_device.py) | Runtime checks and uses existing device/service access. The build does not provision that access, install Python/Node/native libraries, or prove native account permissions. Fixed package owner/group and platform assumptions remain outside the configurable role UIDs. |
| Build | [Builder](../src/build.py), [archive/launcher support](../src/build_support.py) | Complete computer-side build path once target inputs are known. It generates three IPKs and pins, never contacts a TV, and marks the build as not hardware-validated. The three-package output cannot supply the missing target measurements. |
| Install and readiness | [Ready record](../src/runtime/receiver_ready_receipt.py), [result record](../src/runtime/receiver_result_receipt.py) | Installation/launch commands are documented. The reader still needs tooling to compare installed files and ownership, identify the current session, bind ready/results to live processes, and report failures. An old ready file or launch acknowledgement is insufficient. |
| IR setup | [Encoder](../src/ir_packets.py), [IR contract](../docs/IR.md) | Encoder prints bytes only. There is no public backup/write/readback/restore tool or full treatment of existing enable flags. Thus new remotes do not acquire volume and delayed power merely by running the documented encoder. |
| Stop and resume | [Stop protocol](../src/runtime/stop_request.py), [deployment contract](../docs/PORTING.md#stopping-updating-and-removing) | Protocol exists, but no supported operator command coordinates live-instance discovery, stop publication, sensor-stop/process-exit verification and subsequent reconciliation/resume. This is needed between the running Step 5 test and the stopped Step 6 IR test. |
| Automatic startup | [Request dispatcher](../src/scheduler/main.js), [creator](../src/scheduler/creator.js) | The implementation exists, but no public operator tool creates and verifies the complete provisioning transaction. Installing the scheduler does not register the persistent Activity. Restart tests depend on this missing operation. |
| Developer Mode longevity | [Policy](../src/scheduler/expiry-policy.js), [maintenance](../src/scheduler/expiry.js) | Default is disabled, unlike the owner's extension experiment. Choosing `extend` still requires a working startup path and target verification. One successful experiment does not establish indefinite renewal. |
| Rollback and fresh acceptance | [Verification report](verification.md), README removal guidance | TV package backup does not include remote pairing/IR settings. A complete cancel/stop/update/restore tool and a fresh end-to-end installation/rollback test are missing. The public build has not replaced the accepted owner build. |

## Intended dependency order

The table above is an audit, not an executable installer. Completing the workflow requires this order:

1. Prepare host tools and official TV developer access. Confirm the TV's existing runtimes and libraries.
2. Read remote/TV identities and current pairing/IR state before making pairing changes. Establish and verify pairing with target-specific tooling.
3. Install inert app probes under the final identities, measure runtime UIDs and native access, and determine whether the target meets the fixed platform assumptions. This bootstrap tool is not included.
4. Build final packages with those measured values, install/update them, and verify the allocated identities and installed files again.
5. Launch manually, verify the live input session, and test Bluetooth controls. Use a supported stop operation to establish a stopped sensor/session before IR programming.
6. Back up, program and read back IR settings; physically verify IR while the input program is stopped. Reconcile the completed stop and resume input.
7. Register and verify persistent startup, then test remote inactivity, ordinary TV off/on and complete restart without a computer relaunch. Select and validate the Developer Mode policy separately.
8. Retain rollback artifacts and demonstrate a complete stop/cancel/restore path.

Changing the order in the README does not implement the missing tools. In particular, do not use the example IPKs or guessed account IDs to break the bootstrap dependency.

## Verification scope

- A clean export containing only Git-tracked files passed 87 input/publication/layout Python tests, 10 scheduler Python tests, and 22 JavaScript test files. The publication suite built all three packages twice and compared output bytes and pins. This checks host reproducibility, not a fresh TV install.
- Compared the owner's recorded pairing repair and IR writes with the published prerequisites; no private addresses, serials, receipts or commands bound to the owner's hardware were copied into this report.
- No installer, pairing tool, device permission change, IR write or TV runtime update was performed by this audit.

Official references checked: [LG CLI installation](https://webostv.developer.lge.com/develop/tools/cli-installation), [LG Developer Mode connection and key setup](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app). These support the developer-access steps only; they do not validate this project's native runtime or pairing workflow.
