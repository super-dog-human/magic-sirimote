"""Service-owned configuration and cooperative lifecycle operations."""
import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'runtime'), str(ROOT / 'native')]
import runtime_bundle as bundle
from control_processes import processes, require_no_other_input, clean_state
from settings import load, save, validate, _unique


def safe_json(path, owner, limit=4096):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        a = os.fstat(fd)
        if not stat.S_ISREG(a.st_mode) or a.st_uid != owner or a.st_gid != 5000 or a.st_nlink != 1 or not 0 < a.st_size <= limit:
            raise RuntimeError('Runtime record unavailable')
        raw = os.read(fd, limit + 1); b = os.fstat(fd)
        if (a.st_ino, a.st_size, a.st_mtime_ns, a.st_ctime_ns) != (b.st_ino, b.st_size, b.st_mtime_ns, b.st_ctime_ns) or len(raw) != a.st_size:
            raise RuntimeError('Runtime record changed')
        return json.loads(raw, object_pairs_hook=_unique)
    finally:
        os.close(fd)


def status():
    found = processes()
    try:
        load(bundle.ROOT / 'state'); configured = True
    except FileNotFoundError:
        configured = False
    return {'returnValue': True, 'configured': configured, 'processes': found,
            'cleanStop': not found['controller'] and not found['receiver'] and clean_state(),
            'runtimeActivationAvailable': True, 'automaticStartupRegistered': False}


def configure(values):
    found = processes()
    if found['controller'] or found['receiver'] or not clean_state():
        try:
            if validate(values) == load(bundle.ROOT / 'state'):
                return {'returnValue': True, 'status': 'unchanged'}
        except (OSError, ValueError):
            pass
        raise RuntimeError('Stop the input runtime before changing settings')
    values = validate(values)
    from bundle_boot import bind_device
    bind_device(bundle.ROOT / 'state', values)
    save(bundle.ROOT / 'state', values)
    return {'returnValue': True, 'status': 'configured'}


def prepare_start():
    found = processes()
    if found['legacy']:
        raise RuntimeError('The previous input runtime must be stopped first')
    if len(found['controller']) == 1 and found['controller'][0]['uid'] == os.getuid():
        return {'returnValue': True, 'status': 'already-running'}
    require_no_other_input()
    load(bundle.ROOT / 'state')
    for role in ('controller', 'receiver'):
        if not bundle.package_matches(bundle.role_path(role, ''), bundle.PACKAGE, bundle.read_pin(role)):
            raise RuntimeError('Installed runtime code differs')
    return {'returnValue': True, 'status': 'start-ready'}


def stop():
    found = processes()
    if not found['controller']:
        return {'returnValue': True, 'status': 'stopped' if not found['receiver'] and clean_state() else 'needs-recovery'}
    if len(found['controller']) != 1 or found['controller'][0]['uid'] != os.getuid():
        raise RuntimeError('Controller identity is not unique')
    process = found['controller'][0]
    state = bundle.ROOT / 'roles/controller/state'
    matches = []
    for path in state.glob('controller-instance-*.json'):
        record = safe_json(path, os.getuid())
        if record.get('pid') == process['pid'] and record.get('startTicks') == process['startTicks']:
            matches.append(record)
    if len(matches) != 1 or processes()['controller'] != [process]:
        raise RuntimeError('Live controller instance changed')
    from stop_request import publish_request, check_request
    fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        args = dict(pid=process['pid'], start_ticks=process['startTicks'], instance=matches[0]['instance'], owner_uid=os.getuid())
        if not check_request(fd, **args):
            publish_request(fd, **args)
    finally:
        os.close(fd)
    return {'returnValue': True, 'status': 'stop-requested'}


def main():
    bundle.select('controller')
    command = sys.argv[1] if len(sys.argv) == 2 else ''
    raw = sys.stdin.buffer.read(8193)
    if len(raw) > 8192:
        raise ValueError('Request too large')
    params = json.loads(raw or b'{}', object_pairs_hook=_unique)
    if type(params) is not dict:
        raise ValueError('Invalid request')
    if command == 'configure':
        if set(params) != {'settings'}:
            raise ValueError('Settings are required')
        return configure(params['settings'])
    if command == 'reset':
        from reset_state import reset_service
        def idle():
            require_no_other_input()
            if not clean_state(): raise RuntimeError('Input cleanup is not confirmed')
        return reset_service(bundle.ROOT, params, idle)
    if params:
        raise ValueError('Unexpected request fields')
    if command == 'status': return status()
    if command == 'start': return prepare_start()
    if command == 'stop': return stop()
    raise ValueError('Unknown runtime command')


if __name__ == '__main__':
    try:
        response = main()
    except (OSError, ValueError, RuntimeError) as error:
        response = {'returnValue': False, 'status': 'attention', 'errorText': str(error)[:180]}
    print(json.dumps(response, separators=(',', ':')))
