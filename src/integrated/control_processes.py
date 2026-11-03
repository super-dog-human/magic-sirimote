"""Read process identities without interpreting a missing observation as exit."""
from pathlib import Path
import os
import runtime_bundle as bundle

LEGACY = ('org.codex.siriremote.autocoord20261029v', 'org.codex.siriremote.hidgattrouterb20261029u')
APP_ROOT = Path('/media/developer/apps/usr/palm/applications')


def processes(proc='/proc'):
    paths = {str(bundle.ROOT / 'roles' / role / 'native_probe.py'): role for role in ('controller', 'receiver')}
    paths.update({str(APP_ROOT / app / 'native_probe.py'): 'legacy' for app in LEGACY})
    paths[str(APP_ROOT / bundle.APP / 'native_probe.py')] = 'ui'
    result = {key: [] for key in ('controller', 'receiver', 'legacy', 'ui')}
    for p in Path(proc).iterdir():
        if not p.name.isdecimal():
            continue
        try:
            raw = (p / 'cmdline').read_bytes()
            if len(raw) > 32768:
                raise RuntimeError('Process command exceeds limit')
            argv = raw.rstrip(b'\0').split(b'\0')
            if len(argv) != 4 or argv[:3] != [b'/usr/bin/python3', b'-I', b'-B']:
                continue
            role = paths.get(argv[3].decode())
            if role is None:
                continue
            def ticks():
                text = (p / 'stat').read_text()
                return int(text[text.rfind(')') + 2:].split()[19])
            start = ticks()
            status = dict(line.split(':', 1) for line in (p / 'status').read_text().splitlines() if ':' in line)
            if ticks() != start:
                raise RuntimeError('Process identity changed')
            uid = status.get('Uid', '').split()
            if len(uid) != 4 or len(set(uid)) != 1 or not uid[0].isdecimal() or int(uid[0]) <= 0 or status.get('Gid', '').split() != ['5000'] * 4 or status.get('CapEff', '').strip() != '0000000000000000':
                raise RuntimeError('Unexpected runtime privileges')
            result[role].append({'pid': int(p.name), 'startTicks': start, 'uid': int(uid[0])})
        except FileNotFoundError:
            continue
    return result


def require_no_other_input(*, allow_self=False):
    found = processes()
    controllers = [p for p in found['controller'] if not (allow_self and p['pid'] == os.getpid())]
    if found['legacy'] or controllers or found['receiver']:
        raise RuntimeError('Another input runtime is active')
    return found
