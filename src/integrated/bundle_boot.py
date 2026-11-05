"""Bind each role to an immutable controller session before runtime imports."""
import json
import os
import stat
import time
from pathlib import Path
import runtime_bundle as bundle
from runtime_device import configure
from settings import validate, load, _unique


def _read(path, owner):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != owner
                or before.st_gid != 5000 or stat.S_IMODE(before.st_mode) not in (0o640, 0o775)
                or not 0 < before.st_size <= 4096):
            raise RuntimeError('Session settings unavailable')
        raw = os.read(fd, 4097)
        after = os.fstat(fd)
        def fingerprint(s):
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if fingerprint(before) != fingerprint(after) or fingerprint(before) != fingerprint(Path(path).lstat()) or len(raw) != before.st_size:
            raise RuntimeError('Session settings changed')
        return validate(json.loads(raw, object_pairs_hook=_unique))
    finally:
        os.close(fd)


def _save_session(path, values):
    raw = (json.dumps(validate(values), sort_keys=True, separators=(',', ':')) + '\n').encode()
    parent = Path(path).parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 5999 or info.st_gid != 5000 or stat.S_IMODE(info.st_mode) not in (0o770, 0o775):
        raise RuntimeError('Session directory unavailable')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o640)
    try:
        os.fchmod(fd, 0o640)
        if os.write(fd, raw) != len(raw):
            raise RuntimeError('Incomplete session settings')
        os.fsync(fd)
    finally:
        os.close(fd)
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def bind_device(directory, values, *, read=_read, write=_save_session):
    """Never apply a different target to retained controller/receiver journals.

    Switching remotes needs a separate verified migration of both role states.
    Cursor preferences may change without rebinding the hardware identity.
    """
    values = validate(values)
    path = Path(directory) / 'device-binding.json'
    try:
        write(path, values)
    except FileExistsError:
        previous = read(path, os.getuid())
        if any(previous[key] != values[key] for key in ('remoteAddress', 'adapterAddress', 'remoteName')):
            raise RuntimeError('Device change requires verified state migration')


def session_path(pid, ticks):
    if type(pid) is not int or pid <= 0 or type(ticks) is not int or ticks <= 0:
        raise ValueError('Invalid session identity')
    return bundle.ROOT / 'state' / 'sessions' / ('%d-%d.json' % (pid, ticks))


def receiver_settings():
    # These modules inspect metadata only. Importing input modules here would
    # freeze the default device before the session has been authenticated.
    from controller_start_record import read_record
    from local_attestation import matching_processes
    state = bundle.role_path('receiver', '') / 'state'
    try:
        (state / 'recovery-request.json').lstat()
    except FileNotFoundError:
        record = read_record(state)
    else:
        try:
            record = read_record(state, name='recovery-controller-start.json')
        except FileNotFoundError:
            record = read_record(state)
    process = record['process']
    role_path = bundle.role_path('controller', '')
    pin = bundle.read_pin('controller')
    def prove():
        if not bundle.package_matches(role_path, bundle.PACKAGE, pin):
            raise RuntimeError('Controller code changed')
        found = matching_processes(role_path, process['status'], allow_exe_permission_denied=True)
        if len(found) != 1 or found[0]['pid'] != process['pid'] or found[0]['startTicks'] != process['startTicks']:
            raise RuntimeError('Session controller unavailable')
        return found
    first = prove()
    owner = int(process['status']['Uid'].split()[0])
    values = _read(session_path(process['pid'], process['startTicks']), owner)
    if prove() != first:
        raise RuntimeError('Session controller changed')
    return values


def main(role, *, started_at=None):
    began = time.monotonic() if started_at is None else started_at
    def timing(stage):
        print(json.dumps({'stage': 'runtime-startup-timing', 'role': role,
            'step': stage, 'pid': os.getpid(), 'epochMs': int(time.time() * 1000),
            'elapsedMs': round((time.monotonic() - began) * 1000)}, separators=(',', ':')), flush=True)
    from controller_preload import token, await_start, revalidate
    preparation = token() if role == 'controller' else None
    prepared_run = None
    bundle.select(role)
    timing('bundle-imported')
    pin = bundle.read_pin(role)
    if role == 'controller':
        receiver_pin = bundle.read_pin('receiver')
        if not bundle.packages_match({'controller':pin, 'receiver':receiver_pin}):
            raise RuntimeError('Installed runtime does not match both role pins')
    elif not bundle.package_matches(bundle.role_path(role, ''), bundle.PACKAGE, pin):
        raise RuntimeError('Installed runtime does not match package')
    timing('package-verified')
    if role == 'controller':
        timing('receiver-package-verified')
        from controller_connect_identity import verify_self
        from local_attestation import _start_ticks
        if not verify_self():
            raise RuntimeError('Controller process identity unavailable')
        timing('controller-identity-verified')
        from control_processes import require_no_other_input, processes
        deadline = time.monotonic() + 15
        while processes()['ui']:
            require_no_other_input(allow_self=True)
            if time.monotonic() >= deadline:
                raise RuntimeError('Close the setup window before starting input')
            time.sleep(.05)
        require_no_other_input(allow_self=True)
        timing('other-processes-checked')
        values = load(bundle.ROOT / 'state')
        if preparation is not None:
            from runtime_device import configure_cursor
            configure_cursor(enabled=values['gyroEnabled'], sensitivity=values['gyroSensitivity'])
            configure(remote=values['remoteAddress'], adapter=values['adapterAddress'], name=values['remoteName'])
            from resident_controller_entry import main as prepared_run
            timing('runtime-preloaded')
            if not await_start(preparation):
                return 0
            def conflicts():
                found = require_no_other_input(allow_self=True)
                if found['ui']:
                    raise RuntimeError('Settings window opened during preparation')
            revalidate(values, {'controller':pin, 'receiver':receiver_pin},
                load_values=lambda:load(bundle.ROOT / 'state'), read_pin=bundle.read_pin,
                verify_package=lambda role, value:bundle.package_matches(bundle.role_path(role, ''), bundle.PACKAGE, value),
                verify_process=verify_self, check_conflicts=conflicts, verify_pair=bundle.packages_match)
            timing('preparation-revalidated')
        bind_device(bundle.ROOT / 'state', values)
        _save_session(session_path(os.getpid(), _start_ticks(Path('/proc/self/stat'))), values)
        timing('session-saved')
    else:
        from control_processes import processes
        if processes()['legacy']:
            raise RuntimeError('The previous input runtime is still active')
        values = receiver_settings()
        timing('session-verified')
    if role == 'receiver':
        from tv_assignments import load as load_assignments
        from system_buttons import configure_assignments
        app_state = Path('/media/developer/apps/usr/palm/applications/org.magicsirimote.app/state')
        assignments = load_assignments(app_state)
        configure_assignments(assignments['bindings'] if assignments['schema'] == 2 else {})
    if prepared_run is not None:
        run = prepared_run
    else:
        from runtime_device import configure_cursor
        configure_cursor(enabled=values['gyroEnabled'], sensitivity=values['gyroSensitivity'])
        configure(remote=values['remoteAddress'], adapter=values['adapterAddress'], name=values['remoteName'])
        timing('device-configured')
        if role == 'controller':
            from resident_controller_entry import main as run
        else:
            from postconnect_receiver_native_entry import main as run
        timing('runtime-imported')
    return run(timing=timing) if role == 'controller' else run()
