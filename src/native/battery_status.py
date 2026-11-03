"""A device-bound last battery reading; never presented as a live measurement."""
import json
import math
import os
import stat
import tempfile
import time
from pathlib import Path

SERVICE = '0000180f-0000-1000-8000-00805f9b34fb'
LEVEL = '00002a19-0000-1000-8000-00805f9b34fb'


def percentage(reply, remote, adapter, client_id):
    if (type(reply) is not dict or reply.get('returnValue') is not True
            or type(reply.get('address')) is not str or reply['address'].lower() != remote
            or type(reply.get('adapterAddress')) is not str or reply['adapterAddress'].lower() != adapter
            or type(reply.get('service')) is not str or reply['service'].lower() != SERVICE
            or ('clientId' in reply and reply['clientId'] != client_id)):
        raise ValueError('Battery reply identity unavailable')
    values = reply.get('values')
    if type(values) is not list or not 1 <= len(values) <= 16 or any(type(item) is not dict for item in values):
        raise ValueError('Battery reply is ambiguous')
    # webOS returns other cached characteristics from this service as well.
    # Select the requested UUID only; duplicate matches remain ambiguous.
    values = [item for item in values if type(item.get('characteristic')) is str and item['characteristic'].lower() == LEVEL]
    if len(values) != 1: raise ValueError('Battery reply is ambiguous')
    item = values[0]
    if type(item.get('value')) is not dict:
        raise ValueError('Battery characteristic unavailable')
    data = item['value'].get('bytes')
    if type(data) is not list or len(data) != 1 or type(data[0]) is not int or not 0 <= data[0] <= 100:
        raise ValueError('Invalid battery percentage')
    return data[0]


def save(state, remote, adapter, level, *, now=time.time):
    if level is not None and (type(level) is not int or not 0 <= level <= 100):
        raise ValueError('Invalid battery percentage')
    value = {'schema': 1, 'remote': remote, 'adapter': adapter,
             'percent': level, 'readAt': now()}
    fd, name = tempfile.mkstemp(prefix='.battery-', dir=state)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, separators=(',', ':'), allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, Path(state) / 'battery.json')
    finally:
        if os.path.exists(name): os.unlink(name)


def label(state, remote, adapter, *, now=time.time):
    unavailable = 'Battery: unavailable (read when the remote connects)'
    try:
        fd = os.open(Path(state) / 'battery.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 1024):
                return unavailable
            value = json.loads(stream.read(1025))
        if (type(value) is not dict or value.get('schema') != 1
                or value.get('remote') != remote or value.get('adapter') != adapter
                or type(value.get('percent')) is not int or not 0 <= value['percent'] <= 100
                or type(value.get('readAt')) not in (int, float)):
            return unavailable
        age = now() - value['readAt']
        if not math.isfinite(age) or age < 0: return unavailable
        age_text = ('less than a minute ago' if age < 60 else
                    str(int(age // 60)) + ' min ago' if age < 3600 else
                    str(int(age // 3600)) + ' h ago')
        return 'Battery: %d%% (last read %s%s)' % (value['percent'], age_text, '; may have changed' if age >= 900 else '')
    except (OSError, ValueError, TypeError):
        return unavailable
