"""Local TV-side assignments. Saving never contacts the TV or the remote.

The native preview has no input runtime. These bindings describe requested
behavior for that runtime; they must not be reported as active assignments.
"""
import fcntl
import json
import os
import stat
import tempfile
from pathlib import Path
from ir_programmer import BUTTONS

ACTION = 'screen-toggle'
FILE = 'tv-assignments.json'


def slot(button, delay):
    if type(button) is not int or button not in [mask for _, mask in BUTTONS]:
        raise ValueError('Choose one physical button.')
    if type(delay) is not int or delay not in (0, 2):
        raise ValueError('Choose normal or long press.')
    return '%02X:%02X' % (button, delay)


def validate(value):
    keys = {slot(button, delay) for _, button in BUTTONS for delay in (0, 2)}
    if (type(value) is not dict or set(value) != {'schema', 'bindings'} or
            type(value['schema']) is not int or value['schema'] != 1 or
            type(value['bindings']) is not dict or
            any(key not in keys or action != ACTION for key, action in value['bindings'].items())):
        raise ValueError('Unsupported TV assignment format.')
    return value


def load(directory):
    from settings import _unique
    try:
        fd = os.open(Path(directory) / FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return {'schema': 1, 'bindings': {}}
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_size > 4096:
            raise ValueError('TV assignment file is unavailable.')
        raw = os.read(fd, 4097)
        after = os.fstat(fd)
        if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(raw) != info.st_size:
            raise ValueError('TV assignments changed while reading.')
        return validate(json.loads(raw, object_pairs_hook=_unique))
    finally:
        os.close(fd)


def execute(directory, operation, button, delay, code=''):
    key = slot(button, delay)
    if operation not in ('set', 'delete'):
        raise ValueError('Choose Save or Delete.')
    directory = Path(directory)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_gid != os.getgid():
        raise ValueError('TV assignment directory is unavailable.')
    lock = os.open(directory / 'tv-assignments.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    name = None
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise ValueError('TV assignment lock is unavailable.')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        value = load(directory)
        if operation == 'set':
            value['bindings'][key] = ACTION
        else:
            value['bindings'].pop(key, None)
        raw = (json.dumps(validate(value), sort_keys=True) + '\n').encode()
        fd, name = tempfile.mkstemp(prefix='.tv-assignments-', dir=directory)
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, directory / FILE)
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        return {'status': 'configured-only', 'operation': operation, 'active': False}
    finally:
        os.close(lock)
        if name is not None:
            try: os.unlink(name)
            except FileNotFoundError: pass
