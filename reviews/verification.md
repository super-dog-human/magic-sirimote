# Build and runtime verification

Host checks were run on macOS. Hardware validation of the public package versions is pending.

- **124 input/publication Python tests passed,** including 13 checks for interrupted launch recovery and diagnostic logging.
- **10 scheduler Python tests passed.**
- **22 JavaScript test files passed,** including admission, concurrency, interruption, startup binding, standby resume, package-pin tampering, expiry, and the public expiry-policy gate.
- Two independent builds produced identical bytes for all three IPKs. Archive paths, file hashes, cross-package pins, ARM ELF headers, compiled Python payloads, and the disabled maintenance policy were checked.
- The pure IR packet encoder ran locally without device access.
- All eight README Mermaid diagrams passed the Mermaid 11 parser. This was a syntax check, not a GitHub screenshot/render comparison.
- 56 local Markdown links/anchors were checked, including the pre-existing root LICENSE at the destination repository.
- Python source compiled; an export scan found no original device addresses/serial, local home-directory paths, or private-key markers. No live runtime state, authentication receipts, recordings, keys, or firmware was included.

## Runtime checks

The checked public builds are controller/receiver 0.9.102 and scheduler 0.0.95.

- Every packaged runtime module is reachable through static imports from the controller/receiver entrypoints; a clean host process can import all modules without device operations.
- A retired request blocks the controller/receiver before native checks, signal setup, or connection work. Ordinary stop/recovery records remain eligible for their existing handlers.
- A retired scheduler request blocks before service-bus access or state writes; dangling symlinks are also blocked.

## Interrupted startup recovery

On the tested TV, runtime 0.9.73 and startup package 0.0.66 archived an expired launch request left by an earlier boot before the receiver started. Input resumed, followed by automatic restart on an ordinary power cycle. The tests reject live receivers, sensor journals, current-boot requests, changed packages, duplicate archives, and symlinks; interrupted archival resumes without overwriting evidence. A long power-off cycle after this repair has not yet been repeated.

## Scope

These checks support the build and the published explanation. They do not validate fresh pairing, native app permissions on a different TV, the parameterized public build on hardware, every possible failure recovery path, or indefinite Developer Mode renewal. Verified controls, tested package versions, and deployment prerequisites are stated in the README and PORTING.md.

## Setup audit

A tracked-files-only Git export passed the same host suite. The separate `setup-audit.md` records missing installation operations and the app-UID bootstrap dependency; the public workflow is not complete for a fresh TV/remote. No TV or remote was contacted during that audit.

## Input-output startup readiness

A fresh TV boot produced a receiver failure at `setup-open-outputs`; a later read-only open passed, and the existing recovery path restored normal input. The precise initial exception was not retained, so a startup timing race is suspected rather than proven. The receiver now rechecks the full output inventory for at most 12 seconds while its original connection and lease remain valid. Every failed attempt closes its descriptors; uncertain closure stops retrying. Fixed diagnostic categories distinguish inventory, permissions, held keys, changed nodes, timeout, and cleanup failures. Nine tests cover delayed availability, bounded failure, cancellation, duplicate rejection, closure uncertainty, backwards clocks, and diagnostic redaction. The same startup change was installed in test packages (controller/receiver 0.9.77 and scheduler 0.0.70), with all 410 installed files checked against their build hashes. Swipe, press-to-select, and pointer movement were verified after startup. That version still required stationary pointer initialization; the updated initialization is described below. A cold-boot reproduction test for output readiness is still pending.

## Pointer initialization without a stationary wait

The reference orientation now comes from the latest valid report after at least 150 ms and eight samples of continuous, untouched input. Normal movement no longer resets initialization; an adjacent orientation jump above 0.20 radians, invalid input, a gap above 60 ms, or touch contact restarts the window. The initial displacement is discarded, and existing filtering, motion limits, and pointer/navigation selection remain in place. Ten tests cover initialization while moving, stationary output, movement after readiness, gaps, jumps, touch, invalid poses, burst delivery, and clock reversal. An additional test verifies bounded transport-failure reasons and compatibility with earlier diagnostic records.

Test packages 0.9.79 / 0.0.72 were installed with all 410 files verified. The user confirmed pointer movement without a stationary wait. The public build remains a separate package export. An output failure in the prior version was recovered before this update; its precise cause remains unknown. The added transport reason improves evidence if it recurs and is not a claim that the separate failure has been fixed.


Resting-pose suppression uses a 0.20-second quiet window within 0.0012 radians and a separate 0.0025-radian movement threshold to resume. The held reference follows very slow drift, while normal tracking keeps the existing filter and gain. Suppressed displacement is discarded at departure. Four additional tests cover resting noise with drift, normal movement resumption, settling after movement, and departure without a queued jump. A read-only trial on 1,200 real stationary reports produced zero candidate motion frames. These thresholds trade the smallest resting movements for a stable pointer; the user confirmed that fine movements remained usable and that the pointer stopped when the remote was placed down. The revised test packages are controller/receiver 0.9.81 and scheduler 0.0.74.


## Pointer travel adjustment

Horizontal and vertical conversion gains are multiplied by 0.45, from 3230 / 4845 to 1453.5 / 2180.25. Initialization, rest detection, filter parameters, and the 20 ms render period are unchanged. Comparing identical synthetic movements on each axis produced output ratios of approximately 0.45 and the same first-output time, with identical filter and rest-state decisions. Integer output rounding and TV acceleration mean this does not promise an exact 55% reduction in displayed pixels for every movement.

The user accepted this travel setting on the TV with controller/receiver 0.9.93 and scheduler 0.0.86. All 410 installed files matched the build hashes. The public packages remain a separate export; all 124 input and publication tests passed.

## System button release timing and shared IR input

MENU, microphone, Home, and Play/Pause dispatch their Bluetooth action on the first neutral button report after an uninterrupted single-button press. Held reports do not repeat; chords, a different button, and reconnects cancel pending actions. Surface clicks and stored IR commands are unchanged. Button-budget rotation consumes the same neutral report to rearm without dropping the next press. Nine tests cover release timing and lifecycle boundaries.

An uncovered Home press reproduced a receiver stop, while a covered IR emitter allowed the same Bluetooth operation to continue. Read-only observation saw the native Home key held for approximately 165 ms. The receiver's original error was `system-key-held`; cleanup also reported `system-key-release-unverified`. IR and Bluetooth were attempting the same shared input concurrently.

The system-key sink now skips a dispatch when a managed native key is already held, without writing, releasing the other source's key, waiting, retrying, or disabling the sink. The next press remains eligible after the external key is released. Uncertain writes and identity failures remain terminal. A skipped media toggle clears its pending expectation and requires a fresh playback sample, preventing it from waiting for a playback change that was never requested. Five added checks cover duplicated IR Home, continued operation, uncertain writes, media-state refresh, and stale media replies; an existing shared-key test was updated to check nonfatal refusal.

Bounded diagnostics retain the original session failure when resource or application cleanup wraps it. Only allowlisted reason codes and cleanup categories are added; nested success and sensor-stop proof never replace the outer lifecycle result. Four checks cover nested diagnostics, legacy records, privacy, and schema bounds.

All 142 input and publication tests passed. Private hardware packages are controller/receiver 0.9.101 and scheduler 0.0.94, with all 410 installed files verified. The user confirmed that an uncovered Home press returns to Home and subsequent navigation and MENU still work. Repeated Home operations and MENU/microphone release timing were also physically confirmed without another stop. The public build remains a separate export.

A subsequent approximately 0.7-second IR power-off/on test launched a new receiver automatically. Controls were initially reported unavailable, then worked without a manual restart. Immediate readiness after power-on is not verified; the startup delay was not measured in this trial. IR configuration was not changed.
