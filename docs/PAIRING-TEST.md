# Cable-free pairing experiment

This separate native application isolates cable-free pairing tests between a first-generation Siri Remote (A1513) and an LG webOS TV. The pairing flow is also included in the main application; ordinary users should follow the [installation guide](NATIVE_APP.md). This test package is for development and requires the main service to be installed.

The experiment follows the cable-free pairing gesture documented by [SiriRemote-Linux](https://github.com/Yanndroid/SiriRemote-Linux#preparations-only-once): hold MENU and Volume Up for approximately five seconds. The TV initiates pairing through its Bluetooth service, establishes the HID connection, and sends the `F0 AF` input-start request. A successful result requires the TV to report the selected remote as paired and HID-connected for at least 70 seconds after input initialization. It also reads the serial number and checks the supported firmware through Device Information characteristics. Actual remote operation and later reconnection are separate checks.

## Build and install

```sh
python3 src/build_pairing.py --out /tmp/magic-sirimote-pairing-test
ares-install --device YOUR_TV /tmp/magic-sirimote-pairing-test/org.magicsirimote.pairingtest_0.1.6_arm.ipk
ares-launch --device YOUR_TV org.magicsirimote.pairingtest
```

The TV needs Developer Mode and the same native Python/SDL libraries used by Magic Sirimote. Open **Siri Remote Pairing Test** and use the LG remote to operate its screen. The test has its own application ID and state directory. Installation does not replace the main application or enable automatic startup.

## Controlled test

1. Safely stop the main Magic Sirimote receiver and disable its automatic startup. The test checks the main service's `cleanStop` and startup status before changing pairing. This development preview deliberately requires the existing main service; it is not a first-time installation wizard yet.
2. Choose **Read status**. Select the intended remote. For an already paired remote, choose **Prepare remote**, then confirm. This removes that remote's pairing from the TV only. Existing IR assignments are not changed, but Bluetooth control is unavailable until pairing is restored.
3. Choose **Scan**, then hold MENU and Volume Up on that remote for approximately five seconds, with the diagnostic cable disconnected. Scan results may be individual device events or device lists, depending on TV firmware. Their source is recorded; a listed candidate alone is not proof of fresh discovery or successful pairing. Names and advertised services are hints, not proof of model or ownership. Confirm the device address before proceeding.
4. Choose **Finish scan**, select the correct device, and choose **Pair selected remote**. Pairing is attempted once. The application keeps the outgoing pairing subscription open through completion. It never guesses a PIN or changes another device's pairing.
5. Keep the remote awake with occasional surface clicks during the 70-second retention check. The test does not inject TV inputs, program infrared, or enable motion sensors. The screen reports the result. A timeout or uncertain write stops the experiment without an automatic retry.
6. After success, restart the main receiver and separately check swipe, click, cursor movement, sleep recovery, and TV restart. A successful pairing result alone does not establish sleep or restart recovery.

State and bounded event receipts are stored in the test app's `state/` directory. They contain the selected device address and status, but no Bluetooth keys, PINs, audio, or raw input reports. Closing the test cancels only its own pending subscriptions. It does not automatically unpair the remote or restore the main receiver.

The commercial TV's Bluetooth implementation may differ from the [webOS OSE Bluetooth API](https://www.webosose.org/docs/reference/ls2-api/com-webos-service-bluetooth2/). A declared API or a successful scan does not establish that first pairing works. The test package's build manifest intentionally starts with `hardwareValidated: false`.
