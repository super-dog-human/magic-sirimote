"""One immutable device identity per controller/receiver process.

Legacy packages substitute the example values at build time. The integrated
launcher must configure a validated snapshot before importing runtime modules.
Changing devices requires a clean stop and a new process; an active lease or
recovery journal must never silently switch targets. This module performs no I/O.
"""
from dataclasses import dataclass
import json
import re


@dataclass(frozen=True)
class DeviceIdentity:
    remote: str
    adapter: str
    name: str


_current = DeviceIdentity('02:00:00:00:00:01', '02:00:00:00:00:02', 'EXAMPLE_REMOTE_SERIAL')
_selected = False
_frozen = False
_cursor = (True, 3)


def configure(*, remote, adapter, name):
    global _current, _selected
    if _frozen or _selected:
        raise RuntimeError('Device identity is already bound to this process')
    addresses = []
    for value in (remote, adapter):
        if type(value) is not str or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
            raise ValueError('Invalid Bluetooth address')
        value = value.lower()
        if value == '00:00:00:00:00:00' or int(value[:2], 16) & 1:
            raise ValueError('Invalid Bluetooth address')
        addresses.append(value)
    if addresses[0] == addresses[1]:
        raise ValueError('Remote and adapter must differ')
    if type(name) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
        raise ValueError('Invalid remote identity')
    _current = DeviceIdentity(*addresses, name)
    _selected = True


def identity():
    global _frozen
    _frozen = True
    return _current


def connect_intent():
    # Preserve the durable legacy byte format, including key order and newline.
    return (json.dumps({'schema': 1, 'method': 'hid/connect',
                        'address': identity().remote,
                        'outcome': 'reserved-possibly-dispatched'},
                       separators=(',', ':')) + '\n').encode('ascii')


def configure_cursor(*, enabled=True, sensitivity=3):
    global _cursor
    if _frozen: raise RuntimeError('Cursor settings already bound')
    if type(enabled) is not bool or type(sensitivity) is not int or not 1 <= sensitivity <= 5:
        raise ValueError('Invalid cursor settings')
    _cursor = (enabled, sensitivity)


def cursor_preferences():
    return _cursor
