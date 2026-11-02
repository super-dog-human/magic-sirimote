"""Non-mutating checks under the actual native app account.

Opens verified RCU/mouse nodes read/write and closes them without reading or
writing events. Does not open hidraw streams or call Bluetooth services.
"""
import os
import platform
import stat
import struct
from pathlib import Path


def inspect():
    status = {}
    for line in Path('/proc/self/status').read_text().splitlines():
        key, _, value = line.partition(':')
        if key in ('Uid', 'Gid', 'CapEff'):
            status[key] = value.split()
    ordinary = (os.getuid() > 0 and status.get('Uid') == [str(os.getuid())] * 4
                and status.get('Gid') == ['5000'] * 4 and status.get('CapEff') == ['0000000000000000'])
    result = {'ordinaryAccount': ordinary, 'uid': os.getuid(), 'gid': os.getgid(),
              'arm32': (platform.machine().startswith('arm') or platform.machine() == 'aarch64') and struct.calcsize('P') == 4,
              'pythonSupported': __import__('sys').version_info >= (3, 10),
              'devices': {}, 'inputEventsRead': 0, 'inputEventsWritten': 0,
              'bluetoothCalls': 0}
    for expected in ('LGE RCU', 'ClickableMouse'):
        matches = []
        for path in sorted(Path('/sys/class/input').glob('event[0-9]*'))[:128]:
            try:
                if (path / 'device/name').read_text().strip() == expected:
                    matches.append(path)
            except OSError:
                continue
        row = {'unique': len(matches) == 1, 'readWriteOpen': False, 'closed': False}
        if ordinary and len(matches) == 1:
            node = Path('/dev/input') / matches[0].name
            fd = None
            try:
                before = node.lstat()
                if not stat.S_ISCHR(before.st_mode):
                    raise ValueError('Unexpected input node.')
                fd = os.open(node, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
                after = os.fstat(fd)
                if (before.st_dev, before.st_ino, before.st_rdev) != (after.st_dev, after.st_ino, after.st_rdev):
                    raise ValueError('Input node changed.')
                row['readWriteOpen'] = True
            except (OSError, ValueError):
                row['unavailable'] = True
            finally:
                if fd is not None:
                    os.close(fd)
                    row['closed'] = True
        result['devices'][expected] = row
    result['compatibleInputAccess'] = ordinary and result['arm32'] and result['pythonSupported'] and all(r['unique'] and r['readWriteOpen'] and r['closed'] for r in result['devices'].values())
    return result
