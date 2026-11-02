"""One explicitly requested IR change; no I/O on import and no write retries.

Settings cannot be read back on the supported locked firmware. An LS2 success
is a transport acknowledgement, never verification of the EEPROM contents.
"""
import fcntl
import json
import os
import re
import stat
import time
import uuid
from pathlib import Path

from ir_packets import encode_entry, encode_delete
import settings

APP = 'org.magicsirimote.app'
BASE = 'luna://com.webos.service.bluetooth2/'
DIS = '0000180a-0000-1000-8000-00805f9b34fb'
HID = '00001812-0000-1000-8000-00805f9b34fb'
REPORT = '00002a4d-0000-1000-8000-00805f9b34fb'
REFERENCE = '00002908-0000-1000-8000-00805f9b34fb'
SERIAL = '00002a25-0000-1000-8000-00805f9b34fb'
FIRMWARE = '00002a26-0000-1000-8000-00805f9b34fb'
# Exact firmware identification returned by the tested A1513; other versions
# need their own validation rather than assuming the same programming format.
SUPPORTED_FIRMWARE = b'01004102200070033000070131001800B000410240001508'
BUTTONS = (('TV / Home', 1), ('Volume +', 2), ('Volume -', 4),
           ('Play / Pause', 8), ('Microphone', 16), ('MENU', 32), ('Surface click', 128))


def packet(action, button, delay, code=''):
    if type(button) is not int or button not in dict((v, k) for k, v in BUTTONS):
        raise ValueError('Choose one physical button.')
    if action == 'delete':
        return encode_delete(button, delay)
    if action != 'set' or type(code) is not str or not re.fullmatch('[0-9A-Fa-f]{2}', code):
        raise ValueError('Enter a two-digit LG infrared code, such as 02.')
    command = int('{:08b}'.format(int(code, 16))[::-1], 2)
    return encode_entry(button, delay, bytes((0x20, 0xdf, command, command ^ 0xff)))


def runtime_idle(proc=Path('/proc')):
    """Conservative legacy-runtime coexistence check, not a global OS lock."""
    for path in proc.iterdir():
        if not path.name.isdecimal() or int(path.name) == os.getpid():
            continue
        try:
            command = (path / 'cmdline').read_bytes()
        except FileNotFoundError:
            continue
        except PermissionError:
            # An app whose command cannot be inspected might be a controller.
            if path.stat().st_uid >= 5000:
                raise RuntimeError('Cannot check whether another input app is running.')
            continue
        if b'org.codex.siriremote.' in command or b'org.magicsirimote.' in command:
            raise RuntimeError('Stop the other Magic Sirimote apps before changing infrared settings.')


def _values(reply, field, key):
    entries = reply.get('values')
    if type(entries) is not list:
        raise RuntimeError('The remote returned an incomplete response.')
    found = [x.get('value', {}).get('bytes') for x in entries
             if type(x) is dict and x.get(field, '').lower() == key]
    # webOS returns neighbouring characteristics too; only the requested one
    # may establish identity. Reject ambiguous matches rather than guessing.
    if len(found) != 1 or type(found[0]) is not list or any(type(b) is not int or not 0 <= b <= 255 for b in found[0]):
        raise RuntimeError('The remote response could not be identified.')
    return bytes(found[0])


def program(values, action, button, delay, code, call, record, idle=runtime_idle):
    """Injectable transaction used by the TV UI and offline integration tests."""
    values = settings.validate(values)
    report = packet(action, button, delay, code)
    remote, adapter = values['remoteAddress'], values['adapterAddress']
    client = None
    attempted = False
    result = {'status': 'not-sent', 'action': action, 'button': button, 'delay': delay,
              'code': code.upper() if action == 'set' else None,
              'readbackVerified': False, 'automaticRetries': 0}

    def invoke(method, params, timeout=5, identity=True, check_idle=True):
        if check_idle:
            idle()
        reply = call(method, params, timeout)
        if type(reply) is not dict or reply.get('returnValue') is not True:
            raise RuntimeError('The TV rejected the request. No automatic retry was made.')
        if identity and (str(reply.get('address', '')).lower() != remote or
                         str(reply.get('adapterAddress', '')).lower() != adapter):
            raise RuntimeError('The Bluetooth device identity changed.')
        return reply

    def connected():
        for profile in ('hid', 'gatt'):
            reply = invoke(profile + '/getStatus', {'address': remote, 'subscribe': False})
            if reply.get('connected') is not True or reply.get('connecting') is not False or reply.get('connectRequest') is not False:
                raise RuntimeError('Wake the paired remote and establish its input connection first.')

    def read(service, characteristic):
        reply = invoke('gatt/readCharacteristicValues', {
            'clientId': client, 'service': service, 'characteristics': [characteristic]})
        if reply.get('service') != service:
            raise RuntimeError('Unexpected Bluetooth service response.')
        return _values(reply, 'characteristic', characteristic)

    try:
        record(dict(result))
        connected()
        reply = invoke('gatt/connect', {'address': remote, 'subscribe': False}, 12)
        own = reply.get('clientId')
        if type(own) is not str or not re.fullmatch('[0-9]{1,5}', own) or not 1 <= int(own) <= 65535:
            raise RuntimeError('Could not acquire a configuration connection.')
        client = own
        invoke('gatt/discoverServices', {'address': remote}, 8)
        if read(DIS, SERIAL) != values['remoteName'].encode():
            raise RuntimeError('The connected remote does not match the saved device name.')
        if read(DIS, FIRMWARE) != SUPPORTED_FIRMWARE:
            raise RuntimeError('This remote firmware has not been validated for infrared programming.')
        descriptor = invoke('gatt/readDescriptorValues', {
            'clientId': client, 'service': HID, 'characteristic': REPORT, 'descriptors': [REFERENCE]})
        if descriptor.get('service') != HID or _values(descriptor, 'descriptor', REFERENCE) != b'\xf0\x03':
            raise RuntimeError('The configuration report could not be identified.')
        # Select the nonpersistent sensor-mode query. Never stop or restart
        # sensors here: an active runtime must be stopped by its owner first.
        invoke('hid/internal/setReport', {'address': remote, 'reportType': 'feature',
                                        'reportData': [240, 240, 160]})
        if read(HID, REPORT) != b'\xa0\x00':
            raise RuntimeError('The motion sensors are active. Stop remote control before changing infrared.')
        connected()
        result['status'] = 'pending'
        # Durable record precedes the one persistent request. If communication
        # or recording fails afterwards, do not infer failure or resend.
        record(dict(result))
        attempted = True
        invoke('hid/internal/setReport', {'address': remote, 'reportType': 'feature',
                                        'reportData': list(report)})
        result['status'] = 'submitted'
    except Exception as error:
        result['status'] = 'uncertain' if attempted else 'not-sent'
        result['message'] = (str(error) if isinstance(error, (RuntimeError, ValueError))
                             else 'The operation could not finish.')
    finally:
        if client is not None:
            try:
                # Release only our client even if another runtime has since started.
                reply = invoke('gatt/disconnect', {'clientId': client}, 8, identity=False, check_idle=False)
                if 'clientId' in reply and reply['clientId'] != client:
                    raise RuntimeError('Configuration connection release was not confirmed.')
                result['clientReleased'] = True
            except Exception:
                result['clientReleased'] = False
        try:
            record(dict(result))
            result['receiptSaved'] = True
        except Exception:
            # Preserve delivery evidence if final disk recording fails.
            result['receiptSaved'] = False
    return result


def execute(state, action, button, delay, code):
    """TV entry point; uses saved identities and retains one private receipt."""
    from native_luna import Luna
    state = Path(state)
    values = settings.load(state)
    packet(action, button, delay, code)  # Validate before any device I/O.
    lock = os.open(state / 'ir-programming.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    receipt = None
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise RuntimeError('Infrared configuration lock is unavailable.')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = os.open(state / ('ir-operation-' + uuid.uuid4().hex + '.json'),
                          os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)

        def record(value):
            raw = (json.dumps({'schema': 1, 'time': time.time(), 'remoteAddress': values['remoteAddress'], **value}) + '\n').encode()
            os.lseek(receipt, 0, os.SEEK_SET)
            view = memoryview(raw)
            while view:
                written = os.write(receipt, view)
                if written <= 0:
                    raise OSError('Incomplete operation record')
                view = view[written:]
            os.ftruncate(receipt, len(raw))
            os.fsync(receipt)

        parent = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)  # Persist the new receipt name before any remote write.
        finally:
            os.close(parent)

        with Luna() as call:
            return program(values, action, button, delay, code, call, record)
    finally:
        if receipt is not None:
            os.close(receipt)
        os.close(lock)
