"""First-run routing and cable-free pairing in the existing native window."""
import json
import os
import time
import uuid
from pairing_flow import PairingFlow, paired_route, address
from pairing_transport import BluetoothBus


class PairingScreen:
    def __init__(self, app):
        self.app = app; self.route = 'checking'; self.focus = 0; self.boxes = []
        self.bus = BluetoothBus().__enter__(); self.closed = False
        self.deadline = None; self.next_check = 0; self.finish_attempted = False
        self.session = uuid.uuid4().hex
        self.flow = PairingFlow(self.bus, self.record)
        saved = app.values.get('remoteAddress', '')
        try: target = address(saved) if saved else None
        except ValueError: target = None
        self.flow.inspect(target)

    @property
    def visible(self): return self.route != 'settings'

    @property
    def busy(self):
        return self.route == 'stopping' or self.flow.phase in ('pair-preflight', 'pairing', 'connecting', 'initializing', 'identity', 'rejecting')

    def record(self, value):
        value.update(session=self.session, purpose='integrated-pairing')
        target = self.app.state / 'pairing-status.json'
        temp = target.with_suffix('.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640)
        try: os.write(fd, (json.dumps(value) + '\n').encode())
        finally: os.close(fd)
        os.replace(temp, target)

    def close(self):
        if not self.closed:
            self.bus.__exit__(None, None, None); self.closed = True

    def route_existing(self):
        selected = paired_route(list(self.flow.known.values()), self.app.values.get('remoteAddress', '').lower())
        if selected is None:
            self.route = 'start'
            self.flow.message = 'No paired Siri Remote was found. Use the LG remote to begin.'
            return
        # Saved identities are checked again by the receiver's exact HID
        # vendor/product/address guard. Never adopt an unknown paired device
        # on its advertisement alone.
        if not self.app.values.get('remoteAddress') and self.flow.phase != 'existing-verified':
            self.flow.target = address(selected['address'])
            self.flow.was_paired = True
            self.flow.verify_identity(existing=True)
            return
        self.app.values.update(remoteAddress=address(selected['address']),
                               adapterAddress=self.flow.adapter, remoteName=selected.get('name') or self.app.values.get('remoteName', ''))
        self.app.paired_serial = self.flow.serial
        self.route = 'settings'; self.close()

    def start(self):
        # Even a configured but unpaired remote may have a controller retrying.
        # Stop it cooperatively before discovery can lead to a pairing request.
        self.app.stop_runtime()
        self.route = 'stopping'; self.deadline = time.monotonic() + 25; self.next_check = 0
        self.flow.message = 'Preparing Bluetooth pairing. Please wait...'

    def tick(self):
        if not self.visible or self.closed: return False
        before = (self.route, self.flow.phase, self.flow.message, len(self.flow.candidates))
        try:
            self.flow.tick()
            if self.route == 'checking' and self.flow.phase in ('ready', 'existing-verified'): self.route_existing()
            if self.route == 'stopping' and time.monotonic() >= self.next_check:
                self.next_check = time.monotonic() + 1
                value = self.app.bus.request('status', {})
                if value.get('returnValue') is not True: raise RuntimeError('Unable to verify input cleanup')
                if value.get('cleanStop') is True and value.get('startup', {}).get('enabled') is False:
                    self.route = 'pairing'
                    if self.flow.target and not self.flow.was_paired: self.flow.scan_and_pair()
                    else: self.flow.target = None; self.flow.scan()
                elif time.monotonic() >= self.deadline:
                    raise RuntimeError('Input cleanup is not confirmed. Wake Siri Remote and reopen this app.')
            if self.flow.phase == 'success' and not self.finish_attempted:
                self.finish_attempted = True
                # Pairing saves device identity and activates input only. Button
                # assignments and the remote's IR memory are not written here.
                values = {'schema': 1, **self.app.values, 'remoteAddress': self.flow.target,
                          'adapterAddress': self.flow.adapter}
                self.app.paired_serial = self.flow.serial
                self.app.apply(values)
                self.route = 'settings'; self.close()
        except (OSError, ValueError, RuntimeError) as error:
            self.flow.fail(error); self.route = 'error'
        return before != (self.route, self.flow.phase, self.flow.message, len(self.flow.candidates))

    def labels(self):
        if self.route == 'start': return ['Start pairing', 'Close']
        if self.route == 'checking' or self.route == 'stopping': return ['Close']
        if self.flow.phase in ('scanning', 'scanned'):
            return (['Pair selected remote', 'Close'] if self.flow.candidates else ['Search again', 'Close'])
        return ['Close']

    def choose(self, label):
        try:
            if label == 'Close':
                if self.busy:
                    self.flow.message = 'Please wait for pairing to finish, or close the app from Home.'
                else:
                    self.close(); self.app.done = True
            elif label == 'Start pairing': self.start()
            elif label == 'Search again':
                if self.flow.phase == 'scanning': self.flow.stop_scan()
                self.flow.scan()
            elif label == 'Pair selected remote':
                if self.flow.phase == 'scanning': self.flow.stop_scan()
                self.flow.pair()
            self.focus = 0
        except (OSError, ValueError, RuntimeError) as error:
            self.flow.fail(error); self.route = 'error'

    def handle(self, event):
        kind, value = event; labels = self.labels()
        self.focus = min(self.focus, len(labels) - 1)
        if kind == 'close' or kind == 'key' and value in (27, 461, 1073742094): self.choose('Close')
        elif kind == 'key':
            if value in (1073741904, 1073741903): self.focus = (self.focus + 1) % len(labels)
            elif value in (1073741906, 1073741905) and self.flow.candidates:
                self.flow.selected = (self.flow.selected + (1 if value == 1073741905 else -1)) % min(4, len(self.flow.candidates))
            elif value in (13, 1073741912): self.choose(labels[self.focus])
        elif kind == 'click':
            x, y = value
            if 300 <= y < 508 and self.flow.candidates:
                index = (y - 300) // 52
                if index < min(4, len(self.flow.candidates)): self.flow.selected = index
            for index, (bx, by, w, h) in enumerate(self.boxes):
                if bx <= x < bx + w and by <= y < by + h: self.choose(labels[index]); break

    def draw(self, canvas):
        canvas.clear()
        canvas.text('Pair a Siri Remote', 64, 60, 38)
        canvas.text('Use your LG remote for this setup. A diagnostic cable is not needed.', 66, 122, 25)
        canvas.text(self.flow.message, 66, 180, 24)
        if self.route in ('pairing', 'start'):
            canvas.text('Keep Siri Remote nearby. Hold MENU + Volume Up for about 5 seconds.', 66, 236, 23)
        if self.route == 'pairing' and self.flow.phase in ('scanning', 'scanned'):
            for i, d in enumerate(list(self.flow.candidates.values())[:4]):
                y = 300 + 52 * i
                canvas.rectangle((64, y, 1128, 46), (30, 113, 156) if i == self.flow.selected else (36, 48, 65))
                canvas.text(d['name'] + '   ' + d['address'], 82, y + 8, 23)
        labels = self.labels(); self.focus = min(self.focus, len(labels) - 1)
        self.boxes = [(64 + i * 576, 582, 552, 68) for i in range(len(labels))]
        for i, label in enumerate(labels):
            box = self.boxes[i]
            canvas.rectangle(box, (30, 113, 156) if i == self.focus else (36, 48, 65))
            canvas.text(label, box[0] + 24, box[1] + 20, 26)
        canvas.text('Pairing keeps your infrared button assignments unchanged.', 66, 678, 20, (155, 170, 190))
        canvas.present()
