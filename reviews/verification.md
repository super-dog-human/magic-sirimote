# Build and runtime verification

Host checks were run on macOS. Hardware validation of the public package versions is pending.

- **109 input/publication Python tests passed,** including 13 checks for interrupted launch recovery and diagnostic logging.
- **10 scheduler Python tests passed.**
- **22 JavaScript test files passed,** including admission, concurrency, interruption, startup binding, standby resume, package-pin tampering, expiry, and the public expiry-policy gate.
- Two independent builds produced identical bytes for all three IPKs. Archive paths, file hashes, cross-package pins, ARM ELF headers, compiled Python payloads, and the disabled maintenance policy were checked.
- The pure IR packet encoder ran locally without device access.
- All eight README Mermaid diagrams passed the Mermaid 11 parser. This was a syntax check, not a GitHub screenshot/render comparison.
- 56 local Markdown links/anchors were checked, including the pre-existing root LICENSE at the destination repository.
- Python source compiled; an export scan found no original device addresses/serial, local home-directory paths, or private-key markers. No live runtime state, authentication receipts, recordings, keys, or firmware was included.

## Runtime checks

The checked public builds are controller/receiver 0.9.78 and scheduler 0.0.71.

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

A fresh TV boot produced a receiver failure at `setup-open-outputs`; a later read-only open passed, and the existing recovery path restored normal input. The precise initial exception was not retained, so a startup timing race is suspected rather than proven. The receiver now rechecks the full output inventory for at most 12 seconds while its original connection and lease remain valid. Every failed attempt closes its descriptors; uncertain closure stops retrying. Fixed diagnostic categories distinguish inventory, permissions, held keys, changed nodes, timeout, and cleanup failures. Nine tests cover delayed availability, bounded failure, cancellation, duplicate rejection, closure uncertainty, backwards clocks, and diagnostic redaction. The same startup change was installed in test packages (controller/receiver 0.9.77 and scheduler 0.0.70), with all 410 installed files checked against their build hashes. Swipe, press-to-select, and pointer movement were verified after startup. Initial pointer calibration can still take longer than five seconds; a cold-boot reproduction test is still pending.
