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
ROWS = (('Menu', 32), ('TV / Control Center', 1), ('Siri', 16), ('Play/Pause', 8), ('Volume Up', 2), ('Volume Down', 4))


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


def ir_knowledge(directory, known):
    """Use durable transport receipts even if the subsequent UI save failed.

    This is delivery evidence, not firmware readback. Pending/uncertain writes
    invalidate the slot rather than retaining a possibly stale local choice.
    """
    from settings import _unique
    latest = {}
    for path in Path(directory).glob('ir-operation-*.json'):
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_size > 4096:
                raise ValueError('IR delivery history is unavailable.')
            raw = os.read(fd, 4097)
            after = os.fstat(fd)
            if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(raw) != info.st_size:
                raise ValueError('IR delivery history changed. Try again after saving finishes.')
            receipt = json.loads(raw, object_pairs_hook=_unique)
            if type(receipt) is not dict:
                raise ValueError('IR delivery history is invalid.')
            status = receipt.get('status')
            if status == 'not-sent': continue
            key = slot(receipt.get('button'), receipt.get('delay'))
            action = receipt.get('action')
            code = receipt.get('code')
            if status not in ('pending', 'uncertain', 'submitted') or action not in ('set', 'delete'):
                raise ValueError('IR delivery history is invalid.')
            value = None
            if status == 'submitted':
                value = 'none' if action == 'delete' else 'ir:' + str(code).upper()
                if not valid_action(value): raise ValueError('IR delivery history is invalid.')
            rank = (info.st_mtime_ns, path.name)
            if key not in latest or rank > latest[key][0]: latest[key] = (rank, value)
        finally:
            os.close(fd)
    result = dict(known)
    for key, (_, value) in latest.items():
        if value is None: result.pop(key, None)
        else: result[key] = value
    return result


def plan(directory, changes):
    """Validate affected pairs and order writes without exposing a hold-only IR row.

    A1513 Main0241 sends the first IR entry immediately, even with delay 02.
    Unknown slots are not absent slots. Never invent an IR guard or erase an
    unspecified hold to make a requested TV press safe.
    """
    validate({'schema': 2, 'bindings': changes})
    value = load(directory)
    known = dict(value['bindings']) if value['schema'] == 2 else {}
    final = {**ir_knowledge(directory, known), **changes}
    for name, button in ROWS:
        press, hold = slot(button, 0), slot(button, 2)
        if press not in changes and hold not in changes:
            continue
        p, h = final.get(press), final.get(hold)
        if h is not None and h.startswith('ir:') and (p is None or not p.startswith('ir:')):
            raise ValueError(name + ': IR Hold needs an IR Press. Choose an IR Press or change Hold to a TV action / Do nothing.')
        if press in changes and not changes[press].startswith('ir:') and h is None:
            raise ValueError(name + ': Hold IR is unknown. Also choose Hold (TV action / Do nothing) before removing Press IR.')
    # Clear a hold before removing its immediate IR guard. Install an immediate
    # entry before adding an IR hold. Stop the batch on any unconfirmed write.
    return sorted(changes.items(), key=lambda item: (
        0 if item[0].endswith(':02') and not item[1].startswith('ir:') else
        2 if item[0].endswith(':02') else 1, item[0]))


def assign(directory, action, button, delay, code, *, program):
    """Update one slot, removing its competing IR action before a TV/None choice.

    A failed or uncertain write never commits the requested mapping. The IR
    programmer keeps a durable receipt; a local save failure is reported as
    partial, and no operation is automatically repeated.
    """
    slot(button, delay)
    if action != 'assign' or not valid_action(code) or button not in [mask for _, mask in ROWS]:
        raise ValueError('Choose an available action.')
    plan(directory, {slot(button, delay): code})  # Check the other duration before writing.
    ir = code.startswith('ir:')
    result = program(directory, 'set' if ir else 'delete', button, delay, code[3:] if ir else '')
    if result.get('status') != 'submitted':
        return result
    if result.get('connectionPreserved') is not True or result.get('receiptSaved') is not True:
        return {**result, 'status': 'partial', 'mappingSaved': False}
    try:
        execute(directory, 'assign', button, delay, code)
    except (OSError, ValueError):
        return {**result, 'status': 'partial', 'mappingSaved': False}
    return {**result, 'status': 'saved', 'mappingSaved': True}


def displayed_bindings(directory, drafts):
    """A full save replays every concrete displayed value, never unknown IR."""
    validate({'schema': 2, 'bindings': drafts})
    value = load(directory)
    saved = value['bindings'] if value['schema'] == 2 else {}
    # Only explicit saved/draft slots are known. A short press does not imply
    # a hold assignment, and unknown slots must never cause IR writes/deletes.
    return {**saved, **drafts}
