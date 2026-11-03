# Cable-free pairing verification

The integrated package is `org.magicsirimote.app` 0.6.35. The tested hardware is the first-generation A1513 (main firmware 0241, radio firmware 0107) and LG OLED55G3PJA described in the README.

## Verified on the TV

- The previous TV registration for the selected remote was removed and its unpaired state was confirmed before the trial. The diagnostic cable remained disconnected.
- The user selected Start pairing and held MENU + Volume Up. The TV initiated pairing and established HID input.
- The app read the remote serial number and the exact supported firmware through GATT. This TV required individual characteristic reads; the combined read was rejected.
- Pairing and the HID connection were retained for 70.52 seconds after input initialization.
- The integrated app saved the verified identity and started its controller and receiver automatically. No operator start command was sent after this pairing trial. The receiver reported sensor mode 1, valid input reports and completed cursor calibration.
- After automatic handoff, the user confirmed swipe, surface click, gyro pointer, volume and short TV-button operation. There was a noticeable preparation delay before operation resumed; this trial did not measure that delay precisely.
- Existing paired-device routing, removal of the address field and directional operation of the settings screen were confirmed in the preceding integration trial.
- Pairing does not write IR assignments or enable motion sensors; the normal receiver starts sensors after configuration is accepted.

## Local verification

- 302 Python tests and the integrated/scheduler JavaScript suites passed, followed by 10 scheduler Python tests.
- The 19 pairing tests also passed after replacing test serial values with synthetic data.
- All 175 installed files matched the integrated IPK's hashes.
- Source, IPKs, manifests and checksums are published. Private device addresses, serial numbers and live state receipts are excluded from this report.

## Scope

This verifies cable-free re-pairing of the current remote after TV-side registration removal. A factory-fresh remote, an independently clean TV installation, other firmware and other models still require testing. The separate test package was exercised at 0.1.5; the published 0.1.6 shares the final identity-reading flow with the integrated package but was not separately installed for another hardware trial. Build manifests describe generic outputs and do not assert universal hardware compatibility.
