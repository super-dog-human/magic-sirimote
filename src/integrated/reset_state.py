"""Bounded reset records and recoverable retirement of inactive app state."""
import json
import os
import re
import stat
import tempfile
from pathlib import Path


def token(value):
    if type(value) is not str or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('Invalid reset identifier')
    return value


def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or not 0 < info.st_size <= 8192:
            raise RuntimeError('Reset record is unavailable')
        data = os.read(fd, 8193)
        after = os.fstat(fd)
        if (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(data) != info.st_size:
            raise RuntimeError('Reset record changed')
        from settings import _unique
        return json.loads(data, object_pairs_hook=_unique)
    finally:
        os.close(fd)


def write(path, value):
    path = Path(path)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError('Reset directory is unavailable')
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    if len(raw) > 8192: raise ValueError('Reset record too large')
    fd, name = tempfile.mkstemp(prefix='.reset-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        sync(path.parent)
    finally:
        if os.path.exists(name): os.unlink(name)


def sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def retire(directory, reset_id, names=None):
    """Move direct children only, never follow links or recursively delete data."""
    token(reset_id); directory = Path(directory)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    archive = 'reset-archive-' + reset_id
    out = None
    try:
        selected = list(os.listdir(fd)) if names is None else list(names)
        if len(selected) > 4096: raise RuntimeError('Too many records to reset')
        selected = [n for n in selected if n != 'README.txt' and not n.startswith('reset-archive-')]
        if any(type(n) is not str or '/' in n or n in ('', '.', '..') for n in selected):
            raise ValueError('Invalid reset file name')
        try: os.mkdir(archive, 0o700, dir_fd=fd)
        except FileExistsError: pass
        out = os.open(archive, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        if os.fstat(out).st_uid != os.getuid(): raise RuntimeError('Reset archive has a different owner')
        for name in selected:
            try: info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError: continue  # Already retired in this reset.
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)) or stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise RuntimeError('Unexpected reset state entry')
            try: os.stat(name, dir_fd=out, follow_symlinks=False)
            except FileNotFoundError: pass
            else: raise RuntimeError('Reset archive entry already exists')
            os.rename(name, name, src_dir_fd=fd, dst_dir_fd=out)
            os.fsync(out); os.fsync(fd)
    finally:
        if out is not None: os.close(out)
        os.close(fd)


def reset_service(root, params, idle):
    """Invoked only by the authenticated app, after Bluetooth unpair succeeds."""
    from settings import load
    if type(params) is not dict or set(params) != {'resetId', 'remoteAddress', 'adapterAddress'}:
        raise ValueError('Invalid reset request')
    reset_id = token(params['resetId']); root = Path(root); state = root / 'state'
    idle()
    path = state / ('reset-' + reset_id + '.json')
    try: record = read(path)
    except FileNotFoundError:
        values = load(state)
        if any(params[k] != values[k] for k in ('remoteAddress', 'adapterAddress')):
            raise ValueError('Reset target differs from configured remote')
        record = {**params, 'phase': 'prepared'}; write(path, record)
    if any(record.get(k) != v for k, v in params.items()) or record.get('phase') not in ('prepared', 'complete'):
        raise ValueError('Reset record differs')
    if record['phase'] == 'complete': return {'returnValue': True, 'status': 'reset'}
    # Startup stays disabled throughout; active/uncertain journals prohibit this.
    for folder in (root / 'roles/controller/state', root / 'roles/receiver/state', state / 'sessions'):
        idle(); retire(folder, reset_id)
    idle(); retire(state, reset_id, ['settings.json', 'device-binding.json'])
    record['phase'] = 'complete'; write(path, record)
    return {'returnValue': True, 'status': 'reset'}
