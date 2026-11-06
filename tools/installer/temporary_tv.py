"""Stage and retire one bounded maintenance service over Developer Mode SSH.

No root is obtained here. Only this installer's randomly named directories are
accepted. A previous interrupted run is unregistered before another is staged.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

PARENT = Path('/media/developer/temp')
PREFIX = 'magic-sirimote-root-'
FILES = ('runner.py', 'operation.py', 'probe.service', 'manifests/probe.json', 'claimed', 'report.json', 'report.pending')


def directory(run, *, exists=True):
    if not isinstance(run, str) or not re.fullmatch('[a-f0-9]{24}', run):
        raise ValueError('Invalid temporary service identifier')
    base = PARENT / (PREFIX + run)
    if exists:
        info = base.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError('Unsafe temporary service directory')
    return base


def dispatch(request):
    action = request['action']
    if action == 'list':
        runs = []
        for item in PARENT.glob(PREFIX + '*'):
            run = item.name[len(PREFIX):]
            directory(run)
            runs.append(run)
        return {'runs': sorted(runs)}
    base = directory(request['run'], exists=action != 'stage')
    if action == 'stage':
        files = request['files']
        if set(files) != set(FILES[:4]):
            raise ValueError('Unexpected temporary service files')
        decoded = {name: base64.b64decode(value, validate=True) for name, value in files.items()}
        if sum(map(len, decoded.values())) > 524288:
            raise ValueError('Temporary service is too large')
        base.mkdir(mode=0o700)
        (base / 'manifests').mkdir(mode=0o700)
        for name, value in decoded.items():
            fd = os.open(base / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as out:
                out.write(value)
        return {'hashes': {name: hashlib.sha256(value).hexdigest() for name, value in decoded.items()},
                'epochMs': int(time.time() * 1000)}
    if action == 'report':
        try:
            fd = os.open(base / 'report.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return {'pending': True}
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= 32768:
                raise RuntimeError('Invalid temporary service receipt')
            return {'owner': info.st_uid, 'report': json.loads(source.read(32769))}
    if action == 'cleanup':
        # The caller must confirm LS2 unregistration (or that no page was served).
        # Never follow a replacement manifests directory or recursively delete.
        manifests = base / 'manifests'
        if manifests.exists() or manifests.is_symlink():
            info = manifests.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError('Unsafe temporary manifest directory')
        for name in FILES:
            try: (base / name).unlink()
            except FileNotFoundError: pass
        if manifests.exists(): manifests.rmdir()
        base.rmdir()
        return {'removed': True}
    raise ValueError('Unknown temporary service operation')
