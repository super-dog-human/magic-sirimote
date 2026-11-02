# Public export verification — November 2, 2026

The exported source was verified on the development Mac. No public build was installed on the TV, and the existing working installation was left unchanged.

- **82 input/publication Python tests passed:** the 76 baseline input tests plus 6 publication checks.
- **10 scheduler Python tests passed.**
- **21 JavaScript test files passed,** including admission, concurrency, interruption, startup binding, standby resume, package-pin tampering, expiry, and the public expiry-policy gate.
- Two independent builds produced identical bytes for all three IPKs. Archive paths, file hashes, cross-package pins, ARM ELF headers, compiled Python payloads, and the disabled maintenance policy were checked.
- The button demo and pure IR packet encoder ran locally without device access.
- All eight README Mermaid diagrams passed the Mermaid 11 parser. This was a syntax check, not a GitHub screenshot/render comparison.
- 38 local Markdown links/anchors were checked, including the pre-existing root LICENSE at the destination repository.
- Python source compiled; an export scan found no original device addresses/serial, author home-directory paths, or private-key markers. No live runtime state, authentication receipts, recordings, keys, or firmware was included.

## Scope

These checks support the build and the published explanation. They do not validate fresh pairing, native app permissions on a different TV, the parameterized public build on hardware, every possible failure recovery path, or indefinite Developer Mode renewal. Owner-confirmed baseline behavior and the deployment prerequisites are stated in the README and PORTING.md.
