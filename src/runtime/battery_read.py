"""Read battery level on screen requests without blocking remote input."""
from pathlib import Path
import json
from pumping_luna_client import PumpingLunaClient
from borrowed_gatt_view import valid_client
from runtime_device import identity
import runtime_bundle as bundle


class ScreenRefresh:
    """One asynchronous battery read per request from our native parent pipe.

    The receiver keeps pumping input and connection checks while the read runs.
    This never opens a new Bluetooth connection or changes remote settings.
    """
    def __init__(self, client_id, guard, *, fd=0, state=None, spawn=None, clock=None):
        import os, time, subprocess, stat
        self.fd = fd if stat.S_ISFIFO(os.fstat(fd).st_mode) else None
        if self.fd is not None: os.set_blocking(fd, False)
        self.client_id = client_id; self.guard = guard
        self.state = state or Path('/media/developer/apps/usr/palm/applications') / bundle.APP / 'state'
        self.spawn = spawn or subprocess.Popen; self.clock = clock or time.monotonic
        self.pending = b''; self.child = None; self.nonce = None; self.raw = b''
        self.deadline = 0; self.last_request = None

    def finish(self, level=None):
        from battery_status import save
        child, self.child = self.child, None
        if child is not None:
            PumpingLunaClient._stop_child(child)
            child.stdout.close()
        if self.nonce is not None:
            device = identity()
            try: save(self.state, device.remote, device.adapter, level, request_id=self.nonce)
            except (OSError, ValueError): pass
        self.nonce = None; self.raw = b''

    def start(self, nonce):
        import os, subprocess
        from battery_status import SERVICE, LEVEL
        from native_app_identity import verify_self
        self.finish()
        self.nonce = nonce
        try:
            if not valid_client(self.client_id) or verify_self() is not True or self.guard() is not True:
                raise RuntimeError('Battery link unavailable')
            params = {'clientId': self.client_id, 'service': SERVICE, 'characteristics': [LEVEL]}
            self.child = self.spawn(['/usr/bin/luna-send-pub', '-i', '-f',
                'luna://com.webos.service.bluetooth2/gatt/readCharacteristicValues', json.dumps(params)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True)
            os.set_blocking(self.child.stdout.fileno(), False)
            self.deadline = self.clock() + 2
        except Exception: self.finish()

    def tick(self):
        import os, re
        try:
            if self.fd is not None:
                try: data = os.read(self.fd, 4096)
                except BlockingIOError: data = None
                if data == b'': self.fd = None
                elif data:
                    self.pending += data
                    if len(self.pending) > 4096: self.pending = b''; self.fd = None
                    else:
                        lines = self.pending.split(b'\n'); self.pending = lines.pop()
                        requests = [line.decode('ascii') for line in lines if re.fullmatch(b'[a-f0-9]{32}', line)]
                        if requests and requests[-1] != self.last_request:
                            self.last_request = requests[-1]; self.start(self.last_request)
            if self.child is None: return
            if self.guard() is not True or self.clock() >= self.deadline:
                self.finish(); return
            for _ in range(4):
                try: data = os.read(self.child.stdout.fileno(), 8192)
                except BlockingIOError: break
                if not data: break
                self.raw += data
                if len(self.raw) > 65536: self.finish(); return
            if self.raw:
                try:
                    text = self.raw.decode('utf-8').lstrip()
                    reply, end = json.JSONDecoder().raw_decode(text)
                except (ValueError, UnicodeError): pass
                else:
                    from battery_status import percentage
                    device = identity()
                    if text[end:].strip() or self.guard() is not True: raise ValueError('Battery link changed')
                    self.finish(percentage(reply, device.remote, device.adapter, self.client_id)); return
            if self.child.poll() is not None: self.finish()
        except Exception: self.finish()

    def close(self):
        self.finish()
