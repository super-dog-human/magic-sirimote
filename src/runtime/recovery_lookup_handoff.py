"""Reserve one recovery lookup before binding the recovery connection.

LG may report a GATT transition during a client lookup. The controller waits
for a fresh stable connection, then passes the actual reply in its authenticated
request. The receiver must adopt it without a second connect operation.
"""
import re
from pathlib import Path
from prelaunch_handoff_runtime import lookup_before_input, write_json_once
from borrowed_gatt_view import BorrowedGattView


def validate_reply(reply):
    BorrowedGattView(reply, generation=1, control_valid=lambda: False,
                     discover=lambda _: None)
    if set(reply) - {'returnValue', 'subscribed', 'address', 'adapterAddress', 'clientId'}:
        raise ValueError('unexpected recovery lookup fields')
    if 'subscribed' in reply and reply['subscribed'] is not False:
        raise ValueError('recovery lookup is not a subscription')
    return reply


def obtain(*, watch, lease, directory, run, eligible,
           lookup=lookup_before_input, record_write=write_json_once):
    if type(run) is not str or not re.fullmatch('[a-f0-9]{32}', run):
        raise ValueError('invalid recovery run')
    if not callable(eligible) or eligible() is not True:
        raise RuntimeError('recovery lookup admission unavailable')

    class GuardedLease:
        def held(self):
            return lease.held() is True and eligible() is True

    def record(stage, value):
        if stage not in ('intent', 'reply', 'stable', 'unknown'):
            raise ValueError('unexpected recovery lookup stage')
        record_write(Path(directory) / ('recovery-gatt-' + run + '-' + stage + '.json'),
                     {'run': run, **value})

    reply, generation = lookup(watch=watch, lease=GuardedLease(), record=record)
    validate_reply(reply)
    current = watch.snapshot()
    if (not GuardedLease().held() or type(current) is not dict
            or current.get('generation') != generation):
        raise RuntimeError('recovery lookup connection changed')
    return reply, generation
