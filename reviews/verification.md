# Build and runtime verification

Host checks were run on macOS. Hardware validation of the public package versions is pending.

- **87 input/publication Python tests passed:** the 76 baseline input tests, 6 publication checks, and 5 runtime layout/retired-request checks.
- **10 scheduler Python tests passed.**
- **22 JavaScript test files passed,** including admission, concurrency, interruption, startup binding, standby resume, package-pin tampering, expiry, and the public expiry-policy gate.
- Two independent builds produced identical bytes for all three IPKs. Archive paths, file hashes, cross-package pins, ARM ELF headers, compiled Python payloads, and the disabled maintenance policy were checked.
- The pure IR packet encoder ran locally without device access.
- All eight README Mermaid diagrams passed the Mermaid 11 parser. This was a syntax check, not a GitHub screenshot/render comparison.
- 56 local Markdown links/anchors were checked, including the pre-existing root LICENSE at the destination repository.
- Python source compiled; an export scan found no original device addresses/serial, local home-directory paths, or private-key markers. No live runtime state, authentication receipts, recordings, keys, or firmware was included.

## Runtime checks

The checked public builds are controller/receiver 0.9.72 and scheduler 0.0.65.

- Every packaged runtime module is reachable through static imports from the controller/receiver entrypoints; a clean host process can import all modules without device operations.
- A retired request blocks the controller/receiver before native checks, signal setup, or connection work. Ordinary stop/recovery records remain eligible for their existing handlers.
- A retired scheduler request blocks before service-bus access or state writes; dangling symlinks are also blocked.

## Scope

These checks support the build and the published explanation. They do not validate fresh pairing, native app permissions on a different TV, the parameterized public build on hardware, every possible failure recovery path, or indefinite Developer Mode renewal. Verified controls, tested package versions, and deployment prerequisites are stated in the README and PORTING.md.

## Setup audit

A tracked-files-only Git export passed the same host suite. The separate `setup-audit.md` records missing installation operations and the app-UID bootstrap dependency; the public workflow is not complete for a fresh TV/remote. No TV or remote was contacted during that audit.
