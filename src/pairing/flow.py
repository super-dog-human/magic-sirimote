"""TV pairing flow; validates identity before handing off to normal reception."""
import re


def address(value):
    if type(value) is not str or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
        raise ValueError('Invalid Bluetooth address')
    return value.lower()


def advertising(device):
    """Decode only the public BLE AD fields needed to label a remote candidate."""
    raw = device.get('scanRecord', [])
    if type(raw) is not list or len(raw) > 512 or any(type(x) is not int or not 0 <= x <= 255 for x in raw):
        return {}
    result = {}; pos = 0
    while pos < len(raw):
        size = raw[pos]
        if size == 0: break
        if size < 1 or pos + size >= len(raw): return {}
        kind = raw[pos + 1]; data = bytes(raw[pos + 2:pos + size + 1]); pos += size + 1
        if kind in (8, 9): result['name'] = data.decode('utf-8', 'replace')[:48]
        elif kind in (2, 3) and len(data) % 2 == 0:
            result['hid'] = result.get('hid', False) or b'\x12\x18' in [data[i:i+2] for i in range(0, len(data), 2)]
        elif kind == 255 and len(data) >= 2:
            result['apple'] = data[:2] == b'\x4c\x00'
    return result


def plausible(device):
    ad = advertising(device)
    name = str(device.get('name') or ad.get('name', '')).lower()
    # The serial name is a hint, not authentication. Exact model checks remain
    # the receiver's responsibility before it enables sensors.
    return ('siri remote' in name or 'apple tv remote' in name
            or bool(re.fullmatch(r'dl[a-z0-9]{10}', name))
            or (ad.get('apple') is True and ad.get('hid') is True))


def paired_route(devices, saved):
    candidates = [d for d in devices if d.get('paired') is True and not d.get('blocked') and (plausible(d) or (str(d.get('address', '')).lower() == saved and d.get('name') in ('', None)))]
    exact = [d for d in candidates if str(d.get('address', '')).lower() == saved]
    if len(exact) == 1: return exact[0]
    # Do not silently switch an existing configuration to another remote.
    if not saved and len(candidates) == 1: return candidates[0]
    return None


class PairingFlow:
    def __init__(self, bus, record):
        self.bus, self.record = bus, record
        self.phase = 'idle'; self.message = 'Use the LG remote to begin pairing.'
        self.adapter = None; self.target = None; self.known = {}; self.candidates = {}
        self.selected = 0; self.evidence = []; self.was_paired = False
        self.auto_pair = False; self.serial = None; self.confirmed = False; self.pair_ended = False
        self.save()

    def save(self):
        self.record({'phase': self.phase, 'message': self.message, 'adapter': self.adapter,
                     'target': self.target, 'serialVerified': self.serial is not None, 'wasPaired': self.was_paired,
                     'candidates': list(self.candidates.values()), 'evidence': self.evidence})

    def note(self, kind, value):
        self.evidence.append({'kind': kind, 'value': value})
        self.evidence = self.evidence[-512:]; self.save()

    def send(self, tag, method, params, **kw):
        self.note('request', {'tag': tag, 'method': method})
        self.bus.request(tag, method, params, **kw)

    def fail(self, message):
        self.phase = 'failed'; self.message = str(message)[:160]
        self.save()
        for tag in list(self.bus.jobs):
            try: self.bus.cancel(tag)
            except Exception: pass
        self.save()

    def inspect(self, target=None):
        if self.phase not in ('idle', 'ready'): return
        if target is not None: self.target = address(target)
        self.phase = 'checking'; self.message = 'Reading TV Bluetooth state...'
        self.send('adapter', 'adapter/getStatus', {'subscribe': False})

    def scan_and_pair(self):
        if not self.target or self.was_paired: raise ValueError('A known unpaired target is required')
        self.auto_pair = True
        self.scan()

    def scan(self):
        if self.phase not in ('ready', 'scanned'): return
        self.candidates = {}; self.selected = 0
        self.phase = 'scanning'; self.message = 'Hold MENU + Volume Up for 5 seconds. Searching for 45 seconds...'
        self.send('scan', 'le/startScan', {'subscribe': True}, timeout=45, subscription=True)

    def pair(self):
        if self.phase != 'scanned' or not self.candidates: return
        chosen = list(self.candidates.values())[self.selected]
        if self.target and chosen['address'] != self.target: raise ValueError('Unexpected remote')
        self.target = chosen['address']
        if chosen.get('paired'): raise ValueError('This remote is already paired. Reopen settings.')
        self.phase = 'pair-preflight'; self.message = 'Checking that the main app remains stopped...'
        self.send('pair-idle', 'main/status', {})

    def stop_scan(self):
        if self.phase == 'scanning':
            self.bus.cancel('scan'); self.phase = 'scanned'
            self.message = 'Select the remote, then Pair.' if self.candidates else 'No matching remote. Scan again.'
            self.save()

    def profile_ok(self, value):
        return (address(value.get('address', '')) == self.target
                and address(value.get('adapterAddress', '')) == self.adapter
                and value.get('connected') is True and value.get('connecting') is False)

    def on_reply(self, tag, value):
        # No raw advertising payloads, link keys, PINs or input packets are logged.
        if tag != 'scan' or value.get('returnValue') is not True: self.note(tag, {k: value[k] for k in ('returnValue', 'errorCode', 'errorText', 'request',
                   'address', 'adapterAddress', 'connected', 'connecting') if k in value})
        if tag == 'scan' and value.get('returnValue') is not True:
            if 'timed out' in value.get('errorText', ''): self.stop_scan(); return
        if value.get('returnValue') is not True:
            raise RuntimeError(value.get('errorText', 'TV rejected ' + tag))
        if tag == 'adapter':
            adapters = [a for a in value.get('adapters', []) if a.get('powered') is True]
            if len(adapters) != 1 or adapters[0].get('pairing'): raise ValueError('TV adapter is not idle')
            self.adapter = address(adapters[0]['adapterAddress'])
            self.send('devices', 'device/getStatus', {'subscribe': False})
        elif tag == 'devices':
            self.known = {address(d['address']): d for d in value.get('devices', [])}
            self.candidates = {a: {'address': a, 'name': str(d.get('name', 'Unnamed remote'))[:48],
                                   'paired': d.get('paired', False)}
                               for a, d in self.known.items() if a == self.target or (not self.target and plausible(d))}
            self.phase = 'ready'; self.message = 'Ready to pair.'
            if self.target:
                self.was_paired = self.known.get(self.target, {}).get('paired') is True
        elif tag == 'pair-idle':
            if value.get('cleanStop') is not True or value.get('startup', {}).get('enabled') is not False:
                raise RuntimeError('Stop the main app and its automatic startup before pairing')
            self.phase = 'pairing'; self.message = 'Pairing with the selected remote...'
            self.send('pair', 'adapter/pair', {'address': self.target, 'subscribe': True},
                      timeout=45, subscription=True)
        elif tag == 'scan':
            # Commercial TVs may return only a devices list. Keep its provenance:
            # a listed candidate is not proof of fresh advertising or first pairing.
            device = value.get('device')
            rows = [(device, 'device-event')] if type(device) is dict else []
            if type(value.get('devices')) is list:
                rows += [(d, 'scan-list') for d in value['devices'] if type(d) is dict]
            for device, provenance in rows:
                if not device.get('address'): continue
                addr = address(device['address'])
                if (self.target == addr) or (not self.target and plausible(device)):
                    candidate = {'address': addr, 'name': str(device.get('name') or advertising(device).get('name') or 'Apple HID device')[:48],
                                 'paired': device.get('paired', False), 'rssi': device.get('rssi'),
                                 'source': provenance}
                    if self.candidates.get(addr) != candidate:
                        self.candidates[addr] = candidate
                        self.note('candidate', candidate)
                    if self.auto_pair and addr == self.target and candidate['paired'] is False:
                        self.auto_pair = False
                        self.stop_scan(); self.pair(); break
        elif tag == 'pair':
            if value.get('address') and address(value['address']) != self.target: raise ValueError('Wrong pairing peer')
            event = value.get('request')
            if event == 'confirmPasskey':
                if self.confirmed: raise ValueError('Repeated authentication request')
                self.confirmed = True
                self.send('confirm', 'adapter/supplyPasskeyConfirmation', {'address': self.target, 'accept': True})
            elif event in ('enterPinCode', 'enterPasskey', 'displayPinCode', 'displayPasskey'):
                raise RuntimeError('Authentication requires user input; no code was guessed')
            elif event == 'endPairing':
                self.pair_ended = True; self.bus.cancel('pair', completed=True)
                self.send('paired-check', 'device/getStatus', {'subscribe': False})
        elif tag == 'confirm': pass
        elif tag == 'paired-check':
            matches = [d for d in value.get('devices', []) if address(d['address']) == self.target]
            if len(matches) != 1 or matches[0].get('paired') is not True or matches[0].get('pairing') is True:
                raise ValueError('Remote pairing was not confirmed')
            self.known[self.target] = matches[0]
            self.phase = 'connecting'; self.message = 'Pairing complete. Establishing HID input...'
            self.send('hid-check', 'hid/getStatus', {'address': self.target})
        elif tag == 'hid-check':
            if self.profile_ok(value): self.initialize()
            else: self.send('connect', 'hid/connect', {'address': self.target}, timeout=35)
        elif tag == 'connect': self.send('connected-check', 'hid/getStatus', {'address': self.target})
        elif tag == 'connected-check':
            if not self.profile_ok(value): raise ValueError('HID connection not confirmed')
            self.initialize()
        elif tag == 'initialize':
            self.phase = 'identity'
            self.message = 'Reading the paired remote identity...'
            self.send('identity-client', 'gatt/connect', {'address': self.target, 'subscribe': False})
        elif tag == 'identity-client':
            if address(value.get('address', '')) != self.target or address(value.get('adapterAddress', '')) != self.adapter:
                raise ValueError('Wrong identity connection')
            client = value.get('clientId')
            if type(client) is not str or not re.fullmatch(r'[0-9]{1,5}', client) or not 0 < int(client) <= 65535:
                raise ValueError('Missing identity connection')
            self.identity_client = client
            self.send('identity-services', 'gatt/discoverServices', {'address': self.target})
        elif tag == 'identity-services':
            self.send('identity-inventory', 'gatt/getServices', {'address': self.target, 'subscribe': False})
        elif tag == 'identity-inventory':
            if address(value.get('address', '')) != self.target or address(value.get('adapterAddress', '')) != self.adapter:
                raise ValueError('Wrong service inventory')
            services = [s for s in value.get('services', []) if s.get('service') == '0000180a-0000-1000-8000-00805f9b34fb']
            if len(services) != 1: raise ValueError('Device Information service missing')
            chars = [c.get('characteristic') for c in services[0].get('characteristics', [])]
            for uuid in ('00002a25-0000-1000-8000-00805f9b34fb', '00002a26-0000-1000-8000-00805f9b34fb'):
                if chars.count(uuid) != 1: raise ValueError('Remote identity is incomplete')
            self.send('identity-serial', 'gatt/readCharacteristicValues', {
                'clientId': self.identity_client, 'service': '0000180a-0000-1000-8000-00805f9b34fb',
                'characteristics': ['00002a25-0000-1000-8000-00805f9b34fb']})
        elif tag in ('identity-serial', 'identity-firmware'):
            if address(value.get('address', '')) != self.target or address(value.get('adapterAddress', '')) != self.adapter:
                raise ValueError('Wrong identity response')
            if value.get('service') != '0000180a-0000-1000-8000-00805f9b34fb': raise ValueError('Wrong identity service')
            entries = value.get('values', [])
            def read(uuid):
                found = [e.get('value', {}).get('bytes') for e in entries if e.get('characteristic') == uuid]
                if len(found) != 1 or type(found[0]) is not list or any(type(b) is not int or not 0 <= b <= 255 for b in found[0]):
                    raise ValueError('Incomplete remote identity')
                return bytes(found[0])
            if tag == 'identity-serial':
                serial = read('00002a25-0000-1000-8000-00805f9b34fb').decode('ascii')
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', serial): raise ValueError('Invalid remote serial')
                self.pending_serial = serial
                self.send('identity-firmware', 'gatt/readCharacteristicValues', {
                    'clientId': self.identity_client, 'service': '0000180a-0000-1000-8000-00805f9b34fb',
                    'characteristics': ['00002a26-0000-1000-8000-00805f9b34fb']})
            else:
                firmware = read('00002a26-0000-1000-8000-00805f9b34fb')
                if firmware != b'01004102200070033000070131001800B000410240001508':
                    raise ValueError('This remote firmware has not been validated')
                self.serial = self.pending_serial
                self.phase = 'success'; self.message = 'Pairing verified. Starting remote control...'
        self.save()

    def initialize(self):
        self.phase = 'initializing'; self.message = 'Sending the input-start request (no IR or sensor changes)...'
        self.send('initialize', 'hid/internal/setReport',
                  {'address': self.target, 'reportType': 'feature', 'reportData': [240, 175]})

    def tick(self):
        try:
            for tag, value in self.bus.events(): self.on_reply(tag, value)
        except Exception as error: self.fail(error)
