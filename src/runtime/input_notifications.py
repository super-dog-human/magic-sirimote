"""Ensure input notifications are enabled for the intended TV remote.

This is the desired operational setting, retained across normal shutdowns.
It is not a temporary test override. Only flags0 -> flags1 is written;
already-enabled flags1 is preserved, other values are not overwritten.
Sensor start/stop remains a separate lifecycle. No link is disconnected.
"""
from pumping_luna_client import PumpingLunaClient
TARGET = '02:00:00:00:00:01'
ADAPTER = '02:00:00:00:00:02'
BASE = '0000{}-0000-1000-8000-00805f9b34fb'
SERVICE, REPORT, CCCD = (BASE.format(s) for s in ('1812', '2a4d', '2902'))

def identity(reply):
    if (type(reply) is not dict or reply.get('returnValue') is not True
            or reply.get('address', '').lower() != TARGET
            or reply.get('adapterAddress', '').lower() != ADAPTER):
        raise RuntimeError('reply rejected or identity differs')

def handle(value):
    if type(value) is not str or not value.isascii() or not value.isdecimal() or not 1 <= len(value) <= 5:
        raise RuntimeError('invalid instance identifier')
    n = int(value)
    if not 0 < n <= 65535:
        raise RuntimeError('invalid instance identifier')
    return n

def select(reply):
    identity(reply)
    services = reply.get('services')
    if type(services) is not list or len(services) > 64:
        raise RuntimeError('service list invalid')
    hid = [s for s in services if s.get('service', '').lower() == SERVICE]
    if len(hid) != 1:
        raise RuntimeError('HID service not unique')
    chars = hid[0].get('characteristics')
    if type(chars) is not list or len(chars) > 64:
        raise RuntimeError('characteristic list invalid')
    reports = [c for c in chars if c.get('characteristic', '').lower() == REPORT]
    handles = sorted(handle(c.get('instanceId')) for c in reports)
    if handles not in ([29], [29, 32, 35]):
        raise RuntimeError('unknown report layout')
    found = [(c, d) for c in reports for d in c.get('descriptors', [])
             if d.get('descriptor', '').lower() == CCCD]
    if len(found) != 1:
        raise RuntimeError('notification descriptor not unique')
    parent, desc = found[0]
    if handle(parent.get('instanceId')) != (29 if len(reports) == 1 else 35) or handle(desc.get('instanceId')) != 36:
        raise RuntimeError('notification descriptor location differs')
    return {'publicReportHandles': handles, 'descriptorHandle': 36, 'expectedInputHandle': 35}

def flags(reply):
    identity(reply)
    values = reply.get('values')
    if type(values) is not list or not 1 <= len(values) <= 16:
        raise RuntimeError('descriptor reply list invalid')
    # The TV returns other cached descriptors alongside the requested UUID.
    # Select exactly one requested descriptor, then verify its actual handle.
    values = [v for v in values if type(v) is dict and v.get('descriptor', '').lower() == CCCD]
    if len(values) != 1:
        raise RuntimeError('descriptor reply not unique')
    value = values[0]
    if value.get('descriptor', '').lower() != CCCD or handle(value.get('instanceId')) != 36:
        raise RuntimeError('descriptor reply location differs')
    data = value.get('value', {}).get('bytes')
    if type(data) is not list or len(data) != 2 or any(type(n) is not int or not 0 <= n <= 255 for n in data):
        raise RuntimeError('descriptor bytes invalid')
    n = data[0] + data[1] * 256
    if n not in (0, 1, 2, 3):
        raise RuntimeError('reserved notification flags')
    return n


class NotificationClient(PumpingLunaClient):
    def __init__(self, client_id, *, pump, guard):
        handle(client_id)
        super().__init__(pump=pump, guard=guard, native_app=True)
        self.client_id = client_id
        self.counts = {'services': 0, 'read': 0, 'write': 0}
    def _validate_request(self, method, params, timeout):
        common = {'clientId': self.client_id, 'service': SERVICE, 'characteristic': REPORT}
        policy = {
            'gatt/getServices': ({'address': TARGET, 'subscribe': False}, 'services', 1),
            'gatt/readDescriptorValues': ({**common, 'descriptors': [CCCD]}, 'read', 2),
            'gatt/writeDescriptorValue': ({**common, 'descriptor': CCCD, 'value': {'bytes': [1, 0]}}, 'write', 1)}
        if method not in policy or timeout != 6:
            raise ValueError('unexpected notification operation')
        expected, key, maximum = policy[method]
        if params != expected or self.counts[key] >= maximum:
            raise ValueError('notification operation differs or budget consumed')
        self.counts[key] += 1
        return method, 6, False

def ensure_notifications(client_id, *, pump, guard, record, client_factory=NotificationClient):
    if guard() is not True:
        raise RuntimeError('notification-control-unavailable')
    if record({'stage': 'notification-config-intent'}) is not True:
        raise RuntimeError('notification-intent-unrecorded')
    call = client_factory(client_id, pump=pump, guard=guard)
    select(call('gatt/getServices', {'address': TARGET, 'subscribe': False}, timeout=6))
    common = {'clientId': client_id, 'service': SERVICE, 'characteristic': REPORT}
    def read():
        if guard() is not True:
            raise RuntimeError('notification-control-unavailable')
        return flags(call('gatt/readDescriptorValues', {**common, 'descriptors': [CCCD]}, timeout=6))
    before = read()
    if before == 0:
        if guard() is not True:
            raise RuntimeError('notification-control-unavailable')
        identity(call('gatt/writeDescriptorValue', {**common, 'descriptor': CCCD, 'value': {'bytes': [1, 0]}}, timeout=6))
        if read() != 1:
            raise RuntimeError('notification-enable-unconfirmed')
    elif before != 1:
        raise RuntimeError('notification-setting-unsupported')
    if guard() is not True or record({'stage': 'notification-enabled'}) is not True:
        raise RuntimeError('notification-proof-unrecorded')
    return {'beforeFlags': before, 'flags': 1, 'writeAttempted': before == 0, 'retainedDesiredSetting': True}
