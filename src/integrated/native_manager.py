"""Native settings window and an independently attested input worker."""
import json
import os
import re
import signal
import stat
import subprocess
import time
from pathlib import Path
from entry import Setup, ARROWS
from graphics import Canvas
from native_bus import APP, NativeBus
import settings

SERVICE = Path('/media/developer/apps/usr/palm/services') / (APP + '.service')
STATE = Path('/media/developer/apps/usr/palm/applications') / APP / 'state'


def accepted(reply):
    if type(reply) is not dict or reply.get('returnValue') is not True:
        raise RuntimeError(reply.get('errorText', reply.get('status', 'Operation unavailable')) if type(reply) is dict else 'Operation unavailable')
    return reply


def write_status(name, value):
    raw = (json.dumps(value, separators=(',', ':')) + '\n').encode()
    temp = STATE / ('.' + name + '-' + str(os.getpid()))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640)
    try:
        os.fchmod(fd, 0o640); os.write(fd, raw); os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, STATE / name)


def consume_installer(params, apply):
    """An SSH installer stages a bounded data file and passes its random name."""
    if type(params) is not dict or 'installerRequest' not in params:
        return False
    nonce = params['installerRequest']
    if type(nonce) is not str or not re.fullmatch('[a-f0-9]{32}', nonce):
        raise ValueError('Invalid installer request')
    result = 'install-result-' + nonce + '.json'
    if (STATE / result).exists():
        return False  # An uncertain operation is never replayed on relaunch.
    source = STATE / ('install-request-' + nonce + '.json')
    fd = os.open(source, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid <= 0 or before.st_gid != 5000 or stat.S_IMODE(before.st_mode) != 0o640 or not 0 < before.st_size <= 8192:
            raise ValueError('Installer request file is unavailable')
        raw = os.read(fd, 8193); after = os.fstat(fd)
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(raw) != before.st_size:
            raise RuntimeError('Installer request changed')
    finally:
        os.close(fd)
    value = json.loads(raw, object_pairs_hook=settings._unique)
    if type(value) is not dict or set(value) != {'nonce', 'settings', 'action'} or value['nonce'] != nonce or value['action'] not in ('configure', 'start'):
        raise ValueError('Invalid installer data')
    values = settings.validate(value['settings'])
    write_status(result, {'status': 'pending'})
    try:
        apply(values, value['action'] == 'start')
    except Exception as error:
        write_status(result, {'status': 'attention', 'errorType': type(error).__name__, 'errorText': str(error)[:180]})
        raise
    write_status(result, {'status': 'accepted', 'action': value['action']})
    return True


class RuntimeSetup(Setup):
    def __init__(self, state, bus):
        super().__init__(state)
        self.bus = bus
        self.stop_requested = False
        self.worker = None
        self.message = 'Save device settings, then choose Start. Stop before programming infrared.'

    def apply(self, values, start=False):
        accepted(self.bus.request('configure', {'settings': values}))
        settings.save(self.state, values)
        self.values.update({key: values[key] for key in (*settings.FIELDS, 'gyroEnabled')})
        if start:
            accepted(self.bus.request('start', {}))
            self.message = 'Starting remote control.'
            self.done = True  # A fresh post-HID launch must inherit fresh input nodes.
        else:
            self.message = 'Settings saved to the input service.'

    def choose(self, index, canvas):
        if self.editing is not None:
            return super().choose(index, canvas)
        try:
            if index in (5, 8):
                self.apply(settings.validate({'schema': 1, **self.values}), index == 8)
            elif index == 9:
                self.stop_requested = True
                reply = accepted(self.bus.request('stop', {}))
                self.message = 'Stopping input safely.' if reply['status'] == 'stop-requested' else reply['status']
            elif index == 6:
                reply = accepted(self.bus.request('status', {}))
                if not reply.get('cleanStop') or reply['processes']['legacy']:
                    raise RuntimeError('Stop the input runtime before programming infrared.')
                super().choose(index, canvas)
            else:
                super().choose(index, canvas)
        except (OSError, ValueError, RuntimeError) as error:
            self.message = str(error)[:160]
            self.done = False

    def handle(self, event, canvas):
        if self.editing is None and self.infrared is None and event[0] == 'key' and event[1] in ARROWS:
            self.focus = (self.focus + ARROWS[event[1]]) % 10
        else:
            super().handle(event, canvas)

    def draw(self, canvas):
        super().draw(canvas)
        if self.editing is not None or self.infrared is not None:
            return
        canvas.rectangle((64, 605, 1152, 108), (14, 22, 34))
        for index, title in ((8, 'Start remote control'), (9, 'Stop remote control')):
            box = (64 + (index - 8) * 584, 612, 564, 58)
            canvas.rectangle(box, (30, 113, 156) if self.focus == index else (36, 48, 65))
            canvas.text(title, box[0] + 20, box[1] + 16, 24)
            self.boxes.append((index, box))
        canvas.text('Start closes this window while the input connection is prepared.', 66, 682, 19, (155, 170, 190))
        canvas.present()


def pending_worker():
    import runtime_bundle as bundle
    bundle.select('receiver')
    state = SERVICE / 'roles/receiver/state'
    if not any((state / name).exists() for name in ('request.json', 'recovery-request.json')):
        return False
    from bundle_boot import receiver_settings
    receiver_settings()  # Pins, live controller PID/start ticks and snapshot owner.
    return True


def main():
    worker = None; canvas = None; closing = False; log = None; logged = 0
    stop_signal = [False]
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop_signal.__setitem__(0, True))
    try:
        with NativeBus() as bus:
            app = RuntimeSetup(STATE, bus)
            try:
                handoff = pending_worker()
            except (OSError, ValueError, RuntimeError):
                handoff = False; app.message = 'Input handoff needs attention. Existing recovery records were retained.'
            canvas = Canvas(APP); app.draw(canvas)
            if handoff:
                worker = subprocess.Popen(['/usr/bin/python3', '-I', '-B', str(SERVICE / 'roles/receiver/native_probe.py')],
                                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                os.set_blocking(worker.stdout.fileno(), False)
                log = os.open(STATE / ('receiver-output-' + str(os.getpid()) + '.log'), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
                app.worker = worker; canvas.minimize()
                write_status('native-status.json', {'status': 'worker-starting', 'pid': os.getpid(), 'workerPid': worker.pid})
            while True:
                for event, params in bus.events():
                    if event == 'relaunch':
                        canvas.restore()
                        try: consume_installer(params, app.apply)
                        except (OSError, ValueError, RuntimeError) as error: app.message = str(error)[:160]
                        app.draw(canvas)
                    elif event == 'close':
                        stop_signal[0] = True
                if stop_signal[0] and not closing:
                    closing = True
                    if worker is not None and worker.poll() is None:
                        try: accepted(bus.request('stop', {}))
                        except (OSError, ValueError, RuntimeError): worker.terminate()
                    else:
                        break
                    canvas.minimize()
                if worker is not None:
                    for _ in range(8):
                        try: data = os.read(worker.stdout.fileno(), 8192)
                        except BlockingIOError: break
                        if not data: break
                        count = min(len(data), max(0, 65536 - logged))
                        if count: os.write(log, data[:count]); logged += count
                    code = worker.poll()
                    if code is not None:
                        write_status('native-status.json', {'status': 'worker-ended', 'exitCode': code, 'pid': os.getpid(), 'workerPid': worker.pid})
                        worker.stdout.close(); worker = None; app.worker = None
                        if closing or not app.stop_requested:
                            break  # Next connection requires a fresh native jail.
                        app.message = 'Input worker stopped. Wait for the controller to finish before changing settings.'
                        app.draw(canvas)
                if app.infrared is not None and app.infrared.tick(): app.draw(canvas)
                for event in canvas.events():
                    app.handle(event, canvas)
                    if app.done: break
                    app.draw(canvas)
                if app.done:
                    if worker is not None:
                        app.done = False; canvas.minimize()
                    else:
                        break
                time.sleep(.02)
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()  # Exact child handles SIGTERM and performs sensor cleanup.
            try: worker.wait(timeout=12)
            except subprocess.TimeoutExpired:
                # Never SIGKILL an uncertain sensor session. Controller retains its journal.
                pass
        if log is not None: os.close(log)
        if canvas is not None: canvas.close()
