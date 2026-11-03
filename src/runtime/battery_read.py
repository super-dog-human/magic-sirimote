"""Optional single read on the authenticated link before enabling sensors.

No connect, discovery, subscription, write or retry. Failure cannot prevent
remote input; it replaces the previous cached value with unavailable.
"""
from pathlib import Path
from pumping_luna_client import PumpingLunaClient
from borrowed_gatt_view import valid_client
from runtime_device import identity
import runtime_bundle as bundle


class BatteryClient(PumpingLunaClient):
    def __init__(self, client_id, *, pump, guard):
        from battery_status import SERVICE, LEVEL
        if not valid_client(client_id): raise ValueError('Invalid battery client')
        super().__init__(pump=pump, guard=guard, native_app=True)
        self.params = {'clientId': client_id, 'service': SERVICE, 'characteristics': [LEVEL]}
        self.used = False

    def _validate_request(self, method, params, timeout):
        if self.used or method != 'gatt/readCharacteristicValues' or params != self.params or timeout != 2:
            raise ValueError('Unexpected battery operation')
        self.used = True
        return method, 2, False


def capture(client_id, *, pump, guard, client_factory=BatteryClient, state=None):
    from battery_status import SERVICE, LEVEL, percentage, save
    device = identity()
    state = Path('/media/developer/apps/usr/palm/applications') / bundle.APP / 'state' if state is None else state
    level = None
    try:
        if guard() is not True: raise RuntimeError('Battery link unavailable')
        call = client_factory(client_id, pump=pump, guard=guard)
        reply = call('gatt/readCharacteristicValues',
                     {'clientId': client_id, 'service': SERVICE, 'characteristics': [LEVEL]}, timeout=2)
        if guard() is not True: raise RuntimeError('Battery link changed')
        level = percentage(reply, device.remote, device.adapter, client_id)
    except Exception:
        pass  # Optional telemetry must not change input lifecycle outcomes.
    try:
        save(state, device.remote, device.adapter, level)
    except (OSError, ValueError):
        pass
    return level
