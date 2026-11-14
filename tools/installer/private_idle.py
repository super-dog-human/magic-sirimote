"""Bounded maintenance stop when the installed status service is silent.

Executed by the existing bounded temporary service, not imported from TV code.
May disable only automatic startup after proving input is already stopped.
Never kills processes, removes recovery state, or touches BLE.
"""
import json
import os
from pathlib import Path
import re
import stat
import time
import secrets

APP_ID = 'org.magicsirimote.app'
APPLICATIONS = Path('/media/developer/apps/usr/palm/applications')
SERVICE_ROOT = Path('/media/developer/apps/usr/palm/services') / (APP_ID + '.service')


def read_startup():
    directory = SERVICE_ROOT / 'state/startup-private'
    # Check the state directory separately: an unavailable mount must not look
    # like an absent startup record.
    parent = directory.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode): raise RuntimeError('Service state directory unavailable')
    try: info = directory.lstat()
    except FileNotFoundError: return None, None
    if not stat.S_ISDIR(info.st_mode): raise RuntimeError('Unexpected startup directory')
    try: fd = os.open(directory / 'startup.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError: return None, None
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_uid <= 0
                or meta.st_uid != info.st_uid or not 0 < meta.st_size <= 4096):
            raise RuntimeError('Startup record cannot be verified')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result: raise ValueError('Duplicate startup field')
                result[key] = value
            return result
        value = json.loads(stream.read(4097), object_pairs_hook=unique)
        after = os.fstat(stream.fileno())
        if (meta.st_ino, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise RuntimeError('Startup record changed during inspection')
    if (type(value) is not dict or value.get('schema') != 1 or type(value.get('enabled')) is not bool
            or not re.fullmatch('[a-f0-9]{48}', str(value.get('token', '')))
            or value.get('phase') not in ('prepared', 'ready', 'completing', 'attention', 'cancel-pending')):
        raise RuntimeError('Startup record is invalid')
    return value, meta


def startup_disabled():
    value, _ = read_startup()
    return value is None or value['enabled'] is False


def active_processes(proc=Path('/proc')):
    paths = {str(SERVICE_ROOT / 'roles' / role / 'native_probe.py'): role for role in ('controller', 'receiver')}
    paths[str(APPLICATIONS / APP_ID / 'native_probe.py')] = 'ui'
    for app in ('org.codex.siriremote.autocoord20261029v', 'org.codex.siriremote.hidgattrouterb20261029u'):
        paths[str(APPLICATIONS / app / 'native_probe.py')] = 'legacy'
    result = []
    for folder in proc.iterdir():
        if not folder.name.isdecimal(): continue
        try:
            raw = (folder / 'cmdline').read_bytes()
            if len(raw) > 32768: raise RuntimeError('Process command exceeds limit')
            argv = raw.rstrip(b'\0').split(b'\0')
            matched = [(p, role) for p, role in paths.items() if p.encode() in argv]
            if not matched: continue
            if len(matched) != 1 or argv != [b'/usr/bin/python3', b'-I', b'-B', matched[0][0].encode()]:
                raise RuntimeError('Unexpected Magic Sirimote process invocation')
            result.append({'role': matched[0][1], 'pid': int(folder.name)})
        except (FileNotFoundError, ProcessLookupError):
            continue
    return result


def snapshot():
    paths = ('roles/controller/state/receiver-launch-intent.json',
             'roles/receiver/state/borrowed-active', 'roles/receiver/state/request.json',
             'roles/receiver/state/recovery-request.json')
    markers = []
    for name in paths:
        parent = (SERVICE_ROOT / name).parent.lstat()
        if not stat.S_ISDIR(parent.st_mode): raise RuntimeError('Runtime state directory unavailable')
        try: (SERVICE_ROOT / name).lstat()
        except FileNotFoundError: continue
        markers.append(name)
    return {'startupDisabled': startup_disabled(), 'processes': active_processes(), 'cleanupMarkers': markers}


def disable_idle_startup():
    """Only flip enabled=false; retain registration, ownership and all settings."""
    def require_idle():
        observed = snapshot()
        if observed['processes'] or observed['cleanupMarkers']:
            raise RuntimeError('Input is not fully stopped; automatic startup was not changed')
    require_idle()
    value, before = read_startup()
    if value is None or value['enabled'] is False: return False
    directory = SERVICE_ROOT / 'state/startup-private'
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = '.maintenance-' + secrets.token_hex(12)
    created = False
    try:
        parent = os.fstat(fd)
        if parent.st_uid != before.st_uid:
            raise RuntimeError('Startup directory owner changed')
        updated = {**value, 'enabled': False}
        raw = (json.dumps(updated, separators=(',', ':')) + '\n').encode()
        if len(raw) > 4096: raise RuntimeError('Startup record exceeds limit')
        out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        created = True
        with os.fdopen(out, 'wb') as stream:
            # A root-created replacement must remain readable by the app UID.
            if os.geteuid() == 0: os.fchown(stream.fileno(), before.st_uid, before.st_gid)
            actual = os.fstat(stream.fileno())
            if (actual.st_uid, actual.st_gid) != (before.st_uid, before.st_gid):
                raise RuntimeError('Cannot preserve startup ownership')
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        require_idle()
        current, meta = read_startup()
        def identity(item):
            return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns
        current_parent = directory.lstat()
        if (current != value or meta is None or identity(meta) != identity(before)
                or (current_parent.st_dev, current_parent.st_ino) != (parent.st_dev, parent.st_ino)):
            raise RuntimeError('Startup state changed; automatic startup was not overwritten')
        os.replace(temporary, 'startup.json', src_dir_fd=fd, dst_dir_fd=fd)
        created = False
        os.fsync(fd)
        confirmed, meta = read_startup()
        if confirmed != updated or (meta.st_uid, meta.st_gid) != (before.st_uid, before.st_gid):
            raise RuntimeError('Automatic startup disable could not be confirmed')
        return True
    finally:
        if created: os.unlink(temporary, dir_fd=fd)
        os.close(fd)


def prepare_idle():
    changed = disable_idle_startup()
    # Do not infer quiescence from a setting write. A previously queued launch
    # or a new cleanup marker still blocks replacement of the package.
    return {**verify_idle(), 'startupChanged': changed}


def verify_idle(clock=time.monotonic, wait=time.sleep):
    deadline = clock() + 20
    consecutive = 0
    while True:
        value = snapshot()
        if value['startupDisabled'] and not value['processes'] and not value['cleanupMarkers']:
            consecutive += 1
            if consecutive >= 2: return {'idle': True, **value}
        else: consecutive = 0
        if clock() >= deadline:
            # Only role/pid and fixed file names; no remote identity or tokens.
            raise RuntimeError('Independent stop check failed; package unchanged: ' + json.dumps(value))
        wait(1)


def shared_state_paths():
    return [APPLICATIONS / APP_ID / 'state', SERVICE_ROOT / 'state', SERVICE_ROOT / 'state/sessions',
            SERVICE_ROOT / 'roles/controller/state', SERVICE_ROOT / 'roles/receiver/state']


def normalize_shared_state():
    """Restore only the five package-owned shared directories, without recursion."""
    verify_idle()
    opened = []
    try:
        for path in shared_state_paths():
            anchor = SERVICE_ROOT if path.is_relative_to(SERVICE_ROOT) else APPLICATIONS / APP_ID
            for parent in (path, *path.parents):
                if not stat.S_ISDIR(parent.lstat().st_mode):
                    raise RuntimeError('Unexpected state directory path: ' + str(parent))
                if parent == anchor: break
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            opened.append((path, fd, os.fstat(fd)))
            info = opened[-1][2]
            if (info.st_uid != 5999 or info.st_gid != 5000
                    or stat.S_IMODE(info.st_mode) not in (0o770, 0o775, 0o777)):
                raise RuntimeError('Unexpected shared state owner/mode: ' + str(path))
        # Validate all directories before changing any. Check input again in
        # case a window or a queued receiver launch appeared during inspection.
        current = snapshot()
        if not current['startupDisabled'] or current['processes'] or current['cleanupMarkers']:
            raise RuntimeError('Runtime changed before state permission repair')
        changes = []
        for path, fd, before in opened:
            now = os.fstat(fd); named = path.lstat()
            fingerprint = lambda item: (item.st_dev, item.st_ino, item.st_uid, item.st_gid, item.st_mode)
            if fingerprint(now) != fingerprint(before) or fingerprint(named) != fingerprint(before):
                raise RuntimeError('Shared state directory changed')
            if stat.S_IMODE(before.st_mode) != 0o770:
                os.fchmod(fd, 0o770); os.fsync(fd)
            after = os.fstat(fd)
            if stat.S_IMODE(after.st_mode) != 0o770:
                raise RuntimeError('Shared state permissions were not restored')
            changes.append({'path': str(path), 'before': oct(stat.S_IMODE(before.st_mode)), 'after': '0o770'})
        verify_idle()
        return changes
    finally:
        for _, fd, _ in opened: os.close(fd)
