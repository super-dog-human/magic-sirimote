#!/usr/bin/env python3
"""Build a separate native pairing test IPK; never connects to a device."""
import argparse
from pathlib import Path
import build as packaging
import build_support

ROOT = Path(__file__).resolve().parent
APP = 'org.magicsirimote.pairingtest'
VERSION = '0.1.6'


def build(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    files = {p.name: p.read_bytes() for p in (ROOT / 'pairing').glob('*.py')}
    files['graphics.py'] = (ROOT / 'native/graphics.py').read_bytes()
    files['native_bus.py'] = (ROOT / 'integrated/native_bus.py').read_bytes()
    # Lifecycle and Bluetooth transports only need this shared ctypes definition.
    source = (ROOT / 'native/native_luna.py').read_text()
    files['native_luna.py'] = ('import ctypes as C\n\n' + source[source.index('class Error'):source.index('class Luna')]).encode()
    files['native_probe.py'] = ("import sys,json\nfrom pathlib import Path\n"
        "root=Path(__file__).resolve().parent\nsys.path.insert(0,str(root))\n"
        "try:\n from entry import main\n main()\n"
        "except Exception as error:\n"
        " (root/'state'/'startup-status.json').write_text(json.dumps({'errorType':type(error).__name__,'message':str(error)[:200]}))\n"
        " raise SystemExit(2)\n").encode()
    for name, data in files.items(): compile(data, name, 'exec')
    files.update({'entry': packaging.launcher(output, APP), 'icon.png': build_support.icon_png(),
        'appinfo.json': packaging.js({'id': APP, 'version': VERSION, 'type': 'native', 'main': 'entry',
            'title': 'Siri Remote Pairing Test', 'icon': 'icon.png', 'noWindow': False,
            'noSplashOnLaunch': True, 'spinnerOnLaunch': False, 'requiredACG': []}),
        'state/README.txt': b'Pairing experiment receipts; no IR settings or bond keys.\n'})
    record = packaging.package(output, APP, VERSION, files, description='Cable-free Siri Remote pairing experiment')
    manifest = {'schema': 1, 'purpose': 'cable-free-pairing-test', 'hardwareValidated': False,
                'programsInfrared': False, 'startsMotionSensors': False, 'registersAutomaticStartup': False,
                'package': record}
    (output / 'manifest.json').write_bytes(packaging.js(manifest))
    (output / 'SHA256SUMS').write_text(record['packageSha256'] + '  ' + record['package'] + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    print(build(args.out)['package']['package'])
