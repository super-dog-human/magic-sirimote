"""Owned button assignments and coordinated single-slot IR/TV updates.

Schema 1 contains inactive preview choices. Schema 2 is consumed by the
integrated receiver on its next verified start; no change is applied on browse.
"""
import fcntl
import json
import os
import stat
import tempfile
from pathlib import Path
from ir_programmer import BUTTONS

ACTION = 'screen-toggle'
ACTIONS = ('none', 'back', 'home', 'settings', 'playpause', 'play', 'pause', ACTION)
ROWS = (('MENU', 32), ('TV', 1), ('Mic', 16), ('Play / Pause', 8), ('Plus', 2), ('Minus', 4))
DEFAULTS = {'20:00': 'back', '01:00': 'home', '10:00': ACTION, '08:00': 'playpause'}


def valid_action(action):
    import re
    return type(action) is str and (action in ACTIONS or re.fullmatch('ir:[0-9A-F]{2}', action) is not None)

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
            type(value['schema']) is not int or value['schema'] not in (1, 2) or
            type(value['bindings']) is not dict or
            any(key not in keys or not valid_action(action) for key, action in value['bindings'].items())):
        raise ValueError('Unsupported TV assignment format.')
    if value['schema'] == 2 and any(int(key[:2], 16) not in [mask for _, mask in ROWS] for key in value['bindings']):
        raise ValueError('Choose one of the six configurable buttons.')
    if value['schema'] == 1 and any(action != ACTION for action in value['bindings'].values()):
        raise ValueError('Unsupported preview assignment.')
    return value


def load(directory):
    from settings import _unique
    try:
        fd = os.open(Path(directory) / FILE, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
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
    if operation not in ('set', 'delete', 'assign'):
        raise ValueError('Choose Save or Delete.')
    if operation == 'assign' and (not valid_action(code) or button not in [mask for _, mask in ROWS]):
        raise ValueError('Choose an available action.')
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
        if operation == 'assign':
            # Preview-only choices were never active; do not silently enable them.
            if value['schema'] == 1:
                value = {'schema': 2, 'bindings': {}}
            value['bindings'][key] = code
        elif operation == 'set':
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
        return {'status': 'saved' if operation == 'assign' else 'configured-only', 'operation': operation, 'active': False}
    finally:
        os.close(lock)
        if name is not None:
            try: os.unlink(name)
            except FileNotFoundError: pass


def assign(directory, action, button, delay, code, *, program):
    """Update one slot, removing its competing IR action before a TV/None choice.

    A failed or uncertain write never commits the requested mapping. The IR
    programmer keeps a durable receipt; a local save failure is reported as
    partial, and no operation is automatically repeated.
    """
    slot(button, delay)
    if action != 'assign' or not valid_action(code) or button not in [mask for _, mask in ROWS]:
        raise ValueError('Choose an available action.')
    load(directory)  # Refuse malformed storage before a persistent remote write.
    ir = code.startswith('ir:')
    result = program(directory, 'set' if ir else 'delete', button, delay, code[3:] if ir else '')
    if result.get('status') != 'submitted':
        return result
    if result.get('clientReleased') is not True or result.get('receiptSaved') is not True:
        return {**result, 'status': 'partial', 'mappingSaved': False}
    try:
        execute(directory, 'assign', button, delay, code)
    except (OSError, ValueError):
        return {**result, 'status': 'partial', 'mappingSaved': False}
    return {**result, 'status': 'saved', 'mappingSaved': True}
