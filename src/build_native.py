#!/usr/bin/env python3
"""Build the native setup/IR app. Building never connects to a device."""
import argparse
import json
from pathlib import Path
import build as packaging
import build_support

ROOT = Path(__file__).resolve().parent
APP = 'org.magicsirimote.app'
VERSION = '0.2.0'
SOURCES = ('entry.py', 'settings.py', 'graphics.py', 'device_check.py',
           'ir_screen.py', 'ir_programmer.py', 'native_luna.py')


def build(output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Choose an output directory that does not exist.')
    output.mkdir(parents=True)
    files = {name: (ROOT / 'native' / name).read_bytes() for name in SOURCES}
    files['ir_packets.py'] = (ROOT / 'ir_packets.py').read_bytes()
    for name, source in files.items():
        compile(source, name, 'exec')
    wrapper = ("import os,sys,json\nfrom pathlib import Path\n"
               "root=Path(__file__).resolve().parent\nsys.path.insert(0,str(root))\n"
               "try:\n from entry import main\n main()\n"
               "except Exception as error:\n"
               " # No device identities, input reports or raw tracebacks in status.\n"
               " status={'stage':'native-setup','errorType':type(error).__name__}\n"
               " (root/'state'/'startup-status.json').write_text(json.dumps(status)+'\\n')\n"
               " raise SystemExit(2)\n")
    files.update({
        'native_probe.py': wrapper.encode(),
        'entry': packaging.launcher(output, APP),
        'icon.png': build_support.icon_png(),
        'appinfo.json': packaging.js({'id': APP, 'version': VERSION, 'type': 'native',
                                     'main': 'entry', 'title': 'Magic Sirimote Setup',
                                     'icon': 'icon.png', 'noWindow': False,
                                     'noSplashOnLaunch': True, 'spinnerOnLaunch': False,
                                     'requiredACG': []}),
        'state/README.txt': b'Private settings and IR operation receipts. Not a backup of remote memory.\n',
    })
    record = packaging.package(output, APP, VERSION, files)
    manifest = {'schema': 1, 'purpose': 'native-setup-infrared',
                'controlsRemote': False, 'pairsRemote': False, 'programsInfrared': True,
                'automaticInfraredWrites': False, 'hardwareValidated': False,
                'registersAutomaticStartup': False, 'deviceIdentitiesEmbedded': False,
                'package': record}
    (output / 'manifest.json').write_bytes(packaging.js(manifest))
    (output / 'SHA256SUMS').write_text(record['packageSha256'] + '  ' + record['package'] + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.out)
    except (OSError, ValueError) as error:
        parser.exit(2, str(error) + '\n')
    print('Built:', args.out / result['package']['package'])
    print('Setup and explicit IR programming. Hardware validation pending. No pairing or input runtime.')


if __name__ == '__main__':
    main()
