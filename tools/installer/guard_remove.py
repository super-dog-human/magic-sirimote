"""Inspect/remove only Magic Sirimote's root-installed input-device fix."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

BASE = Path('/var/lib/magic-sirimote-hid-guard')
ENV = Path('/var/systemd/system/env/bthidmanager.env')
LIB = BASE/'libsirimote-hid-guard.so'
RECORD = BASE/'installed.json'
ROLLBACK = BASE/'rollback.py'


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('Unexpected ownership/type/permissions: '+str(path))
    return path.read_bytes()


def inspect():
    if os.geteuid() != 0:
        raise RuntimeError('Root SSH is required to check the TV-side fix outside Developer Mode')
    paths = (BASE, ENV)
    present = []
    for path in paths:
        try: path.lstat(); present.append(path)
        except FileNotFoundError: pass
    if not present: return {'state': 'absent'}
    try:
        info = BASE.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Unexpected TV-side fix directory')
        record = json.loads(regular(RECORD))
        expected = 'LD_PRELOAD='+str(LIB)+'\n'
        if (regular(ENV).decode() != expected or record['environmentContent'] != expected
                or record['environmentFile'] != str(ENV)
                or hashlib.sha256(regular(LIB)).hexdigest() != record['librarySha256']
                or hashlib.sha256(regular(ROLLBACK)).hexdigest() != record['rollbackSha256']):
            raise RuntimeError('TV-side fix files differ from the installation record')
        # The stored rollback removes directories recorded by the original installer.
        allowed = {str(p) for p in [BASE, *BASE.parents, ENV.parent, *ENV.parent.parents]}
        if (not isinstance(record['createdDirectories'], list)
                or any(not isinstance(p, str) or p not in allowed for p in record['createdDirectories'])):
            raise RuntimeError('Invalid TV-side fix directory record')
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError('TV-side fix is incomplete or unreadable; no files removed: '+str(error)) from error
    return {'state': 'installed'}


def service():
    fields = ['MainPID', 'ActiveState', 'BoundBy', 'ConsistsOf', 'PropagatesStopTo']
    result = subprocess.run(['/bin/systemctl', 'show', 'bthidmanager.service']+
                            ['--property='+field for field in fields],
                            capture_output=True, text=True, timeout=10, check=True)
    props = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if (props.get('ActiveState') != 'active' or not props.get('MainPID', '').isdigit()
            or int(props['MainPID']) <= 1
            or os.path.realpath('/proc/'+props['MainPID']+'/exe') != '/usr/sbin/bthidmanager'):
        raise RuntimeError('The input service is not in the expected running state')
    if any(props.get(key) for key in ('BoundBy', 'ConsistsOf', 'PropagatesStopTo')):
        raise RuntimeError('The input service cannot be restarted independently; no files removed')
    return props


def dispatch(action):
    state = inspect()
    if action == 'inspect' or state['state'] == 'absent': return state
    if action != 'remove': raise ValueError('Unknown removal operation')
    before = service()
    subprocess.run([sys.executable, '-I', '-B', str(ROLLBACK)], capture_output=True,
                   text=True, timeout=45, check=True)
    # An existing old installer can leave its now-empty directory behind.
    if BASE.exists() and not any(BASE.iterdir()): BASE.rmdir()
    if inspect()['state'] != 'absent': raise RuntimeError('TV-side fix files remain after removal')
    after = service()
    if before['MainPID'] == after['MainPID'] or str(LIB) in Path('/proc/'+after['MainPID']+'/maps').read_text():
        raise RuntimeError('TV-side files were removed, but the input service still needs attention')
    return {'state': 'removed', 'tvRebooted': False}
