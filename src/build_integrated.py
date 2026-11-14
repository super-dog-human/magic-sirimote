#!/usr/bin/env python3
"""Build the single-package runtime candidate without contacting a TV."""
import argparse
import json
from pathlib import Path
import build_support as packaging
import build_support

ROOT = Path(__file__).resolve().parent
APP = 'org.magicsirimote.app'
NATIVE_SOURCES = ('entry.py', 'settings.py', 'graphics.py', 'ir_screen.py',
                  'ir_programmer.py', 'native_luna.py', 'tv_assignments.py')
VERSION = '0.6.1'
ROLES = ('controller', 'receiver')


def build(output, *, bytecode_python=None):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Choose an output directory that does not exist.')
    output.mkdir(parents=True)
    names = json.loads((ROOT / 'runtime-files.json').read_text())
    if len(names) != len(set(names)) or set(names) != {p.name for p in (ROOT / 'runtime').glob('*.py')}:
        raise ValueError('Runtime inventory mismatch')
    service = {'runtime/' + name: (ROOT / 'runtime' / name).read_bytes() for name in names}
    # One copy of the native sources is visible to both native and service UIDs.
    service.update({'native/' + name: (ROOT / 'native' / name).read_bytes() for name in NATIVE_SOURCES})
    service['native/battery_status.py'] = (ROOT / 'native/battery_status.py').read_bytes()
    for name in ('native_bus.py', 'native_manager.py', 'pairing_screen.py', 'reset_state.py', 'reset_remote.py', 'reset_screen.py', 'reset_recovery.py'):
        service['native/' + name] = (ROOT / 'integrated' / name).read_bytes()
    service['native/pairing_flow.py'] = (ROOT / 'pairing/flow.py').read_bytes()
    service['native/pairing_transport.py'] = (ROOT / 'pairing/transport.py').read_bytes()
    service['runtime/control_processes.py'] = (ROOT / 'integrated/control_processes.py').read_bytes()
    service['control.py'] = (ROOT / 'integrated/control.py').read_bytes()
    service['service_entry.js'] = (ROOT / 'integrated/service_entry.js').read_bytes()
    service['native/ir_packets.py'] = (ROOT / 'ir_packets.py').read_bytes()
    service['runtime/controller_preload.py'] = (ROOT / 'integrated/controller_preload.py').read_bytes()
    service['controller-preload.js'] = (ROOT / 'integrated/controller-preload.js').read_bytes()
    service['runtime/bundle_boot.py'] = (ROOT / 'integrated/bundle_boot.py').read_bytes()
    service['service.js'] = (ROOT / 'integrated/service.js').read_bytes()
    service['activity-read.py'] = (ROOT / 'integrated/activity_read.py').read_bytes()
    service['process-read.js'] = (ROOT / 'integrated/process-read.js').read_bytes()
    service['startup.js'] = (ROOT / 'integrated/startup.js').read_bytes()
    for name in ('power-hints.js', 'power-observer.js'):
        service[name] = (ROOT / 'integrated' / name).read_bytes()
    service['power-client.js'] = (ROOT / 'integrated/power-client.js').read_bytes()
    service['power-read.py'] = (ROOT / 'integrated/power-read.py').read_bytes()
    service['package.json'] = packaging.js({'name': APP + '.service', 'version': VERSION, 'main': 'service_entry.js'})
    service['services.json'] = packaging.js({'id': APP + '.service', 'services': [{'name': APP + '.service'}],
                                           'requiredACG': ['bluetooth.query', 'application.launcher', 'activity.operation', 'activity.query', 'configurator.callbacks']})
    for role in ROLES:
        service['roles/' + role + '/native_probe.py'] = (
            'import time\nstarted_at=time.monotonic()\nimport sys\nfrom pathlib import Path\nroot=Path(__file__).resolve().parents[2]\n'
            "sys.path[:0]=[str(root/'runtime'),str(root/'native')]\n"
            'from bundle_boot import main\nraise SystemExit(main(' + repr(role) + ', started_at=started_at))\n').encode()
        service['roles/' + role + '/state/README.txt'] = b'Role leases and recovery records. Preserve until verified cleanup.\n'
    service['state/README.txt'] = b'Service-owned settings, automatic startup and runtime records.\n'
    service['state/sessions/README.txt'] = b'Immutable settings snapshots bound to controller PID and start ticks.\n'
    bytecode = None
    if bytecode_python is not None:
        from build_bytecode import compile_files
        cached, bytecode = compile_files(service, bytecode_python, '/media/developer/apps/usr/palm/services/' + APP + '.service')
        service.update(cached)
    # Pins cover common executable code plus BOTH role wrappers, not mutable state.
    code = {name: packaging.digest(data) for name, data in service.items()
            if '/state/' not in name and not name.startswith('state/')}
    for role in ROLES:
        service['pins/' + role + '.json'] = packaging.js({'schema': 'bundled-role-v1', 'appId': APP,
                                                         'role': role, 'files': code,
                                                         'serviceInfoSha256': packaging.digest(service['package.json'])})
    wrapper = (
        'import time\nstarted_at=time.monotonic()\nimport sys\nfrom pathlib import Path\n'
        "root=Path('/media/developer/apps/usr/palm/services/" + APP + ".service')\n"
        "sys.path[:0]=[str(root/'native'),str(root/'runtime')]\n"
        'from native_manager import main\nmain(started_at=started_at)\n')
    files = {'native_probe.py': wrapper.encode(), 'entry': packaging.launcher(output, APP),
             'icon.png': build_support.icon_png(),
             'appinfo.json': packaging.js({'id': APP, 'version': VERSION, 'type': 'native', 'main': 'entry',
                                           'title': 'Magic Sirimote', 'icon': 'icon.png', 'noWindow': False,
                                           'previewMetadata': {'targetEndpoint': 'luna://' + APP + '.service/preview',
                                                               'sourceEndpoint': '@PREVIEW.ENDPOINT.SOURCE_LOCAL_STOREAPP'},
                                           'noSplashOnLaunch': True, 'spinnerOnLaunch': False,
                                           'requiredACG': ['bluetooth.query', 'application.launcher', 'activity.operation', 'activity.query', 'configurator.callbacks']}),
             'state/README.txt': b'Native settings UI state.\n'}
    for name, source in {**files, **service}.items():
        if name.endswith('.py'):
            compile(source, name, 'exec')
    record = packaging.package(output, APP, VERSION, files, service,
                               description='Magic Sirimote integrated runtime with automatic startup',
                               service_state_dirs=('state', 'state/sessions', 'roles/controller/state', 'roles/receiver/state'))
    manifest = {'schema': 1, 'purpose': 'single-package-runtime-candidate', 'package': record,
                'roles': list(ROLES), 'runtimeSourceCopies': 1, 'runtimeActivationAvailable': True,
                'controlsRemote': True, 'hardwareValidated': False,
                'registersAutomaticStartup': True, 'deviceIdentitiesEmbedded': False, 'bytecode': bytecode}
    (output / 'manifest.json').write_bytes(packaging.js(manifest))
    (output / 'SHA256SUMS').write_text(record['packageSha256'] + '  ' + record['package'] + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--bytecode-python', help='Optional CPython executable for checked-hash import caches; source fallback is retained.')
    args = parser.parse_args()
    try:
        result = build(args.out, bytecode_python=args.bytecode_python)
    except (OSError, ValueError) as error:
        parser.exit(2, str(error) + '\n')
    print('Built:', args.out / result['package']['package'])
    print('Save verified device settings to enable automatic remote reception.')


if __name__ == '__main__':
    main()
