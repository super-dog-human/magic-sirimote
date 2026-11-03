"""Editable device identities and cursor preference for the native setup application.

This stores application settings only. It never pairs devices, changes the
remote's memory, or enables the input runtime.
"""
import json
import os
import re
import stat
import tempfile
from pathlib import Path

FIELDS = ('remoteAddress', 'remoteName', 'adapterAddress')
LABELS = ('Remote Bluetooth address', 'Remote device name / serial', 'TV Bluetooth address')
LIMITS = (17, 64, 17)
EDITABLE_FIELDS = FIELDS[:1]
MAIN_FOCUS = (0, 3, 4, 8, 6, 5, 7)
PREFERENCES = ('gyroEnabled', 'gyroSensitivity')
ADDRESS = re.compile(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\Z')
NAME = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')


def validate(values):
    if type(values) is not dict or not {'schema', *FIELDS} <= set(values) <= {'schema', *FIELDS, *PREFERENCES} or type(values['schema']) is not int or values['schema'] != 1:
        raise ValueError('Unsupported settings format.')
    result = dict(values)
    result.setdefault('gyroEnabled', True)
    result.setdefault('gyroSensitivity', 3)
    if type(result['gyroSensitivity']) is not int or not 1 <= result['gyroSensitivity'] <= 5:
        raise ValueError('Choose gyro sensitivity from 1 to 5.')
    if type(result['gyroEnabled']) is not bool:
        raise ValueError('Gyro cursor must be On or Off.')
    for key in ('remoteAddress', 'adapterAddress'):
        raw = values[key]
        if type(raw) is not str:
            raise ValueError('Bluetooth addresses must be text.')
        value = raw.strip().lower()
        if not ADDRESS.fullmatch(value) or int(value[:2], 16) & 1 or value == '00:00:00:00:00:00':
            raise ValueError('Use a nonzero Bluetooth address, such as AA:BB:CC:DD:EE:FF.')
        result[key] = value
    if result['remoteAddress'] == result['adapterAddress']:
        raise ValueError('The remote and TV must have different addresses.')
    if type(values['remoteName']) is not str or not NAME.fullmatch(values['remoteName']):
        raise ValueError('Use the exact device name: 1-64 letters, numbers, underscores or hyphens.')
    return result


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate settings field.')
        result[key] = value
    return result


def load(directory):
    file = Path(directory) / 'settings.json'
    fd = os.open(file, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid() or before.st_size > 4096:
            raise ValueError('Saved settings have an unexpected owner or format.')
        raw = os.read(fd, 4097)
        after = os.fstat(fd)
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(raw) != before.st_size:
            raise ValueError('Settings changed while reading.')
        return validate(json.loads(raw, object_pairs_hook=_unique))
    finally:
        os.close(fd)


def save(directory, values):
    data = (json.dumps(validate(values), sort_keys=True) + '\n').encode()
    directory = Path(directory)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_gid != os.getgid():
        raise ValueError('Settings directory is not available.')
    # The containing app state directory is provided by the IPK. Never follow
    # an existing configuration link or edit any other application's files.
    target = directory / 'settings.json'
    try:
        old = target.lstat()
    except FileNotFoundError:
        old = None
    if old and (not stat.S_ISREG(old.st_mode) or old.st_nlink != 1 or old.st_uid != os.getuid()):
        raise ValueError('Existing settings cannot be replaced safely.')
    fd, name = tempfile.mkstemp(prefix='.settings-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def tv_address_from_reply(reply):
    if type(reply) is not dict:
        raise RuntimeError('The TV Bluetooth adapter could not be identified.')
    adapters = reply.get('adapters')
    if reply.get('returnValue') is not True or type(adapters) is not list or len(adapters) != 1:
        raise RuntimeError('The TV Bluetooth adapter could not be identified. Settings were not changed.')
    adapter = adapters[0]
    import re
    address = adapter.get('adapterAddress') if type(adapter) is dict else None
    if (type(address) is not str or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', address)
            or int(address[:2], 16) & 1 or address.lower() == '00:00:00:00:00:00'):
        raise RuntimeError('The TV returned an invalid Bluetooth identity.')
    return address.lower()


def read_tv_address():
    from native_luna import Luna
    with Luna() as call:
        return tv_address_from_reply(call('adapter/getStatus', {'subscribe': False}, 5))


def remote_name_from_reply(reply, remote, adapter, verified_name=None):
    if (type(remote) is not str or not ADDRESS.fullmatch(remote.lower()) or
            type(adapter) is not str or not ADDRESS.fullmatch(adapter.lower())):
        raise ValueError('Enter the remote Bluetooth address first.')
    if type(reply) is not dict or reply.get('returnValue') is not True or type(reply.get('devices')) is not list:
        raise RuntimeError('The paired remote could not be identified.')
    matches = [row for row in reply['devices'] if type(row) is dict and
               type(row.get('address')) is str and row['address'].lower() == remote.lower()]
    if len(matches) != 1:
        raise RuntimeError('The remote is not registered on this TV. Pair it before saving settings.')
    row = matches[0]
    if row.get('paired') is not True or row.get('pairing') is True or row.get('blocked') is True:
        raise RuntimeError('Complete pairing with this TV before saving settings.')
    if 'adapterAddress' in row and (type(row['adapterAddress']) is not str or row['adapterAddress'].lower() != adapter.lower()):
        raise RuntimeError('The remote registration belongs to a different TV adapter.')
    name = row.get('name')
    if name in ('', None) and type(verified_name) is str and NAME.fullmatch(verified_name):
        name = verified_name
    if type(name) is not str or not NAME.fullmatch(name):
        raise RuntimeError('The paired remote has no supported device identifier.')
    return name


def read_remote_name(remote, adapter, verified_name=None):
    if type(remote) is not str or not ADDRESS.fullmatch(remote.lower()):
        raise ValueError('Enter the remote Bluetooth address first.')
    from native_luna import Luna
    with Luna() as call:
        return remote_name_from_reply(call('device/getStatus', {'subscribe': False}, 5), remote, adapter, verified_name)
