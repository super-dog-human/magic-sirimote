"""Reconnect only the saved remote so an interrupted full reset can finish."""
from pairing_flow import PairingFlow, address
import reset_remote
import settings
from reset_state import write


class ResetRecovery(PairingFlow):
    def __init__(self, bus, state, value):
        self.state, self.value = state, value
        self.expected = value['settings']
        self.repair_started = False
        super().__init__(bus, lambda record: None)
        self.inspect(self.expected['remoteAddress'])

    def checkpoint(self, message):
        if settings.load(self.state) != self.expected:
            raise RuntimeError('Saved settings changed; reset stopped')
        self.value['phase'] = 'reconnecting'
        self.value['message'] = message[:240]
        write(self.state / reset_remote.FILE, self.value)
        self.message = message

    def inspect_rows(self, value):
        rows = value.get('devices')
        if type(rows) is not list or any(type(d) is not dict for d in rows):
            raise ValueError('Pairing status unavailable')
        found = [d for d in rows if str(d.get('address', '')).lower() == self.target]
        if len(found) > 1:
            raise ValueError('Ambiguous saved pairing')
        if not found: return False
        row = found[0]
        if type(row.get('paired')) is not bool or row.get('pairing') is True or row.get('blocked'):
            raise ValueError('Saved remote is not idle')
        adapter = row.get('adapterAddress', self.adapter)
        if not (row['paired'] is False and adapter == '') and address(adapter) != self.adapter:
            raise ValueError('Saved pairing belongs to another TV adapter')
        return row['paired']

    def repair(self):
        # This is part of an explicitly confirmed full reset. It may remove the
        # saved bond before IR deletion, but never claims IR was erased then.
        self.repair_started = True
        self.checkpoint('Restoring the saved remote connection. Infrared deletion is not yet confirmed.')
        self.phase = 'repair-preflight'
        self.send('repair-idle', 'main/status', {})

    def search(self):
        self.was_paired = False
        self.phase = 'ready'
        self.scan_and_pair()

    def on_reply(self, tag, value):
        # A stale bond can fail at connection establishment after a firmware
        # update. Do not use an identity mismatch or an uncertain input write as
        # permission to discard a bond. At most one repair per user attempt.
        if tag in ('identity-client', 'connect', 'connected-check'):
            if value.get('address') and address(value['address']) != self.target:
                raise ValueError('Wrong remote')
            if value.get('adapterAddress') and address(value['adapterAddress']) != self.adapter:
                raise ValueError('Wrong TV adapter')
        if (tag in ('identity-client', 'connect') and value.get('returnValue') is False
                and self.was_paired and not self.repair_started and not self.input_sent):
            self.repair()
            return
        if (tag == 'connected-check' and value.get('returnValue') is True
                and address(value.get('address')) == self.target
                and address(value.get('adapterAddress')) == self.adapter
                and value.get('connected') is False and value.get('connecting') is False
                and self.was_paired and not self.repair_started and not self.input_sent):
            self.repair()
            return
        if tag.startswith('repair-'):
            if value.get('returnValue') is not True:
                raise RuntimeError(value.get('errorText', 'Connection repair was not confirmed'))
            if value.get('adapterAddress') and address(value['adapterAddress']) != self.adapter:
                raise ValueError('Wrong TV adapter')
            if value.get('address') and address(value['address']) != self.target:
                raise ValueError('Wrong remote')
            if tag == 'repair-idle':
                if (value.get('cleanStop') is not True or value.get('processes', {}).get('legacy')
                        or value.get('startup', {}).get('enabled') is not False):
                    raise RuntimeError('Input cleanup is not confirmed')
                self.send('repair-adapter', 'adapter/getStatus', {'subscribe': False})
            elif tag == 'repair-adapter':
                adapters = value.get('adapters', [])
                if (len(adapters) != 1 or adapters[0].get('powered') is not True
                        or adapters[0].get('pairing') or address(adapters[0].get('adapterAddress')) != self.adapter):
                    raise ValueError('TV adapter changed or is not idle')
                self.send('repair-fresh', 'device/getStatus', {'subscribe': False})
            elif tag == 'repair-fresh':
                if self.inspect_rows(value):
                    self.checkpoint('Removing only the saved TV bond to reconnect. IR deletion is still pending.')
                    self.send('repair-unpair', 'adapter/unpair', {'address': self.target})
                else: self.search()
            elif tag == 'repair-unpair':
                self.send('repair-check', 'device/getStatus', {'subscribe': False})
            elif tag == 'repair-check':
                if self.inspect_rows(value): raise RuntimeError('Old pairing removal was not confirmed')
                self.search()
            return
        if tag == 'devices' and value.get('returnValue') is True:
            self.inspect_rows(value)
        super().on_reply(tag, value)
        if tag == 'adapter' and self.adapter != self.expected['adapterAddress']:
            raise ValueError('TV Bluetooth identity changed')
        if tag == 'devices':
            self.checkpoint('Connecting to the saved remote. Keep it awake; disconnect it from the Mac.')
            if self.was_paired:
                self.verify_identity()
            else: self.search()
        elif tag == 'identity-serial' and self.pending_serial != self.expected['remoteName']:
            raise ValueError('Remote serial differs from the saved remote')
        elif tag == 'initialize':
            self.message = 'Saved remote verified. Continuing infrared deletion...'
