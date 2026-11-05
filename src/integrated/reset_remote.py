"""Explicit reset: clear the IR database, then unpair only the saved remote."""
from pathlib import Path
import uuid
import settings
from reset_state import read, write, token, retire

FILE = 'reset-pending.json'
# Retain the progress keys so an interrupted reset from an older version
# remains readable. Acknowledged bulk deletion completes all keys together.
SLOTS = tuple((button, delay) for button in (1, 2, 4, 8, 16, 32, 128) for delay in (2, 0))


def load(state):
    value = read(Path(state) / FILE)
    if type(value) is not dict or set(value) != {'schema', 'id', 'settings', 'completed', 'unpaired', 'phase', 'message'} or value['schema'] != 1:
        raise ValueError('Invalid reset record')
    token(value['id']); settings.validate(value['settings'])
    allowed = ['%02X:%02X' % slot for slot in SLOTS]
    if (type(value['completed']) is not list or value['completed'] != allowed[:len(value['completed'])]
            or type(value['unpaired']) is not bool or value['phase'] not in ('stopping', 'ir', 'unpair', 'clear', 'failed')
            or type(value['message']) is not str or len(value['message']) > 240):
        raise ValueError('Invalid reset progress')
    if value['unpaired'] and len(value['completed']) != len(SLOTS):
        raise ValueError('Reset ordering is incomplete')
    return value


def create(state):
    try: return load(state)
    except FileNotFoundError: pass
    value = {'schema': 1, 'id': uuid.uuid4().hex, 'settings': settings.load(state),
             'completed': [], 'unpaired': False, 'phase': 'stopping', 'message': ''}
    write(Path(state) / FILE, value)
    return value


def run(state, value, program, call, idle, progress=lambda message: None):
    state = Path(state)
    def save(): write(state / FILE, value)
    def message(text):
        value['message'] = text[:240]; save(); progress(value['message'])
    try:
        if settings.load(state) != value['settings']:
            raise RuntimeError('Saved settings changed; reset stopped')
        remote = value['settings']['remoteAddress']; adapter = value['settings']['adapterAddress']
        if len(value['completed']) < len(SLOTS):
            idle(); value['phase'] = 'ir'
            message('Deleting all infrared assignments...')
            result = program(state, 'reset-all', None, None, '')
            if result.get('status') != 'submitted' or result.get('receiptSaved') is not True:
                raise RuntimeError(result.get('message') or 'Infrared deletion was not acknowledged')
            value['completed'] = ['%02X:%02X' % slot for slot in SLOTS]; save()
        # An explicit retry first queries the bond; a lost unpair reply is not
        # automatically treated as failure or repeated in the same attempt.
        idle(); value['phase'] = 'unpair'; message('Removing this remote from the TV...')
        def request(method, params):
            idle(); reply = call(method, params, 10)
            if type(reply) is not dict or reply.get('returnValue') is not True:
                raise RuntimeError('Bluetooth request was not confirmed. Reset stopped.')
            for key, expected in (('adapterAddress', adapter), ('address', remote)):
                if key in reply and reply[key].lower() != expected: raise RuntimeError('Bluetooth identity changed')
            return reply
        actual = settings.tv_address_from_reply(request('adapter/getStatus', {'subscribe': False}))
        if actual != adapter: raise RuntimeError('TV Bluetooth identity changed')
        def paired():
            rows = request('device/getStatus', {'subscribe': False}).get('devices')
            if type(rows) is not list or any(type(d) is not dict for d in rows): raise RuntimeError('Pairing status unavailable')
            found = [d for d in rows if str(d.get('address', '')).lower() == remote]
            if len(found) > 1 or found and (type(found[0].get('paired')) is not bool or found[0].get('pairing') is True):
                raise RuntimeError('Pairing status is ambiguous')
            if found:
                row_adapter = found[0].get('adapterAddress', adapter)
                # webOS clears the device row's adapter after successful unpair.
                # The enclosing reply and current TV adapter are checked above.
                if not (found[0]['paired'] is False and row_adapter == ''):
                    if type(row_adapter) is not str or row_adapter.lower() != adapter:
                        raise RuntimeError('Pairing belongs to a different TV adapter')
            return bool(found and found[0]['paired'])
        if paired():
            request('adapter/unpair', {'address': remote})
            if paired(): raise RuntimeError('Pairing removal was not confirmed')
        value['unpaired'] = True; value['phase'] = 'clear'; message('Clearing Magic Sirimote settings...')
        return value
    except Exception as error:
        value['phase'] = 'failed'
        message(('Infrared deletion acknowledged. ' if len(value['completed']) == len(SLOTS)
                 else 'Infrared deletion not confirmed. ') + str(error))
        return value


def finish_local(state, value):
    if not value['unpaired'] or len(value['completed']) != len(SLOTS):
        raise RuntimeError('Reset has not completed')
    # Keep the reset receipt until all active app settings have been retired.
    receipts = [p.name for p in Path(state).glob('ir-operation-*.json')]
    retire(state, value['id'], ['settings.json', 'tv-assignments.json', 'battery.json', *receipts])
    retire(state, value['id'], [FILE])
