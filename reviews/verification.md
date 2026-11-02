# Public export verification — November 2, 2026

The exported source was verified on the development Mac. No public build was installed on the TV, and the existing working installation was left unchanged.

- **87 input/publication Python tests passed:** the 76 baseline input tests, 6 publication checks, and 5 runtime layout/retired-request checks.
- **10 scheduler Python tests passed.**
- **22 JavaScript test files passed,** including admission, concurrency, interruption, startup binding, standby resume, package-pin tampering, expiry, and the public expiry-policy gate.
- Two independent builds produced identical bytes for all three IPKs. Archive paths, file hashes, cross-package pins, ARM ELF headers, compiled Python payloads, and the disabled maintenance policy were checked.
- The pure IR packet encoder ran locally without device access. The former synthetic button demo was removed from the setup guide and source; developer regression tests remain.
- All nine README Mermaid diagrams passed the Mermaid 11 parser. This was a syntax check, not a GitHub screenshot/render comparison.
- 40 local Markdown links/anchors were checked, including the pre-existing root LICENSE at the destination repository.
- Python source compiled; an export scan found no original device addresses/serial, author home-directory paths, or private-key markers. No live runtime state, authentication receipts, recordings, keys, or firmware was included.

## Cleanup checks

The public builds are now controller/receiver 0.9.72 and scheduler 0.0.65. Runtime modules decreased from 175 to 132; scheduler source files decreased from 54 to 29, with tests moved under `tests/scheduler`.

- Every packaged runtime module is reachable through static imports from the controller/receiver entrypoints; a clean host process can import all modules without device operations.
- A retired request blocks the controller/receiver before native checks, signal setup, or connection work. Ordinary stop/recovery records remain eligible for their existing handlers.
- A retired scheduler request blocks before service-bus access or state writes; dangling symlinks are also blocked.
- The active HID helper function bodies were retained unchanged while removing their old standalone experiment.
- Normal decoding, motion processing, output, reconnect, and session cleanup modules retain their existing algorithms. No new build was installed on the TV.

## Scope

These checks support the build and the published explanation. They do not validate fresh pairing, native app permissions on a different TV, the parameterized public build on hardware, every possible failure recovery path, or indefinite Developer Mode renewal. Owner-confirmed baseline behavior and the deployment prerequisites are stated in the README and PORTING.md.
