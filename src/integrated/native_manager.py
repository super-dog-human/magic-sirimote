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


def consume_installer(params, apply, stop=None):
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
    if type(value) is not dict or set(value) != {'nonce', 'settings', 'action'} or value['nonce'] != nonce or value['action'] not in ('configure', 'start', 'stop'):
        raise ValueError('Invalid installer data')
    values = settings.validate(value['settings'])
    write_status(result, {'status': 'pending'})
    try:
        if value['action'] == 'stop':
            if stop is None: raise RuntimeError('Stop handler unavailable')
            stop()
        else:
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
        self.pending_settings = None
        self.resume_after_settings = False
        self.next_settings_check = 0
        from battery_status import ScreenReading
        self.battery = ScreenReading(state)
        self.message = 'Remote control starts automatically after device settings are saved.'

    def enable_startup(self):
        reply = accepted(self.bus.request('startupPrepare', {}))
        if reply.get('status') == 'registered':
            accepted(self.bus.request('startupRepair', {})); return
        if reply.get('status') != 'create-required': raise RuntimeError('Automatic startup is unavailable')
        created = accepted(self.bus.create_startup(reply['token']))
        activity_id = created.get('activityId')
        if type(activity_id) is not int or activity_id <= 0: raise RuntimeError('Automatic startup registration is unconfirmed')
        accepted(self.bus.request('startupBind', {'token': reply['token'], 'activityId': activity_id}))

    def apply(self, values, start=True):
        if self.infrared is not None:
            raise RuntimeError('Close button settings before updating device settings or starting input.')
        accepted(self.bus.request('configure', {'settings': values}))
        settings.save(self.state, values)
        self.values.update({key: values[key] for key in (*settings.FIELDS, 'gyroEnabled')})
        # Both installer configure and the TV Save action activate reception.
        # Keep the old argument for staged installer requests from earlier builds.
        self.enable_startup()
        accepted(self.bus.request('start', {}))
        self.message = 'Settings saved. Remote control starts automatically.'
        self.resume_after_settings = False
        self.done = True  # A fresh post-HID launch must inherit fresh input nodes.

    def stop_runtime(self):
        """Installer maintenance only; never exposed as a settings choice."""
        self.pending_settings = None
        self.resume_after_settings = False
        self.stop_requested = True
        reply = accepted(self.bus.request('stop', {}))
        self.message = 'Stopping input; automatic startup disabled.' if reply['status'] == 'stop-requested' else reply['status']

    def prepare_settings(self, action, values=None):
        if self.pending_settings is not None:
            return
        accepted(self.bus.request('drain', {}))
        self.stop_requested = True  # Keep the window after the worker finishes.
        self.resume_after_settings = True
        self.pending_settings = (action, values, time.monotonic() + 20)
        self.next_settings_check = 0
        self.message = 'Preparing settings. Use the original LG remote while input pauses.'

    def settings_tick(self, canvas):
        if self.pending_settings is None or time.monotonic() < self.next_settings_check:
            return False
        self.next_settings_check = time.monotonic() + 1
        action, values, deadline = self.pending_settings
        try:
            reply = accepted(self.bus.request('status', {}))
            if not reply.get('cleanStop') or reply['processes']['legacy']:
                if time.monotonic() < deadline:
                    return False
                raise RuntimeError('Input cleanup is not confirmed. Settings were not changed.')
            self.pending_settings = None
            if action == 'save':
                self.apply(values)
            else:
                super().choose(6, canvas)
                self.infrared.submit = self.program_ir
        except (OSError, ValueError, RuntimeError) as error:
            self.pending_settings = None
            self.message = str(error)[:160]
        return True

    def resume_settings(self):
        if self.resume_after_settings:
            accepted(self.bus.request('resume', {}))
            self.resume_after_settings = False
        self.done = True  # Close the stale input namespace before reconnecting.

    def program_ir(self, *args):
        from ir_programmer import execute, runtime_idle
        from control_processes import require_no_other_input, clean_state
        def idle():
            require_no_other_input()
            if not clean_state():
                raise RuntimeError('Input cleanup must finish before programming infrared.')
            runtime_idle(allow_idle_service=True)
        idle()
        return execute(*args, idle=idle)

    def choose(self, index, canvas):
        if self.editing is not None:
            return super().choose(index, canvas)
        try:
            if index == 5:
                self.prepare_settings('save', settings.validate({'schema': 1, **self.values}))
            elif index == 6:
                self.prepare_settings('buttons')
            elif index == 3:
                self.values['gyroEnabled'] = not self.values['gyroEnabled']
                self.message = 'Choose Save settings to save this preference.'
            else:
                super().choose(index, canvas)
        except (OSError, ValueError, RuntimeError) as error:
            self.message = str(error)[:160]
            self.done = False

    def handle(self, event, canvas):
        was_infrared = self.infrared is not None
        if self.pending_settings is not None:
            return  # Wait for cooperative cleanup; never edit a live session.
        super().handle(event, canvas)
        if self.done or (was_infrared and self.infrared is None):
            try:
                self.resume_settings()
            except (OSError, ValueError, RuntimeError) as error:
                self.done = False
                self.message = str(error)[:160]

    def draw_footer(self, canvas):
        canvas.text('Remote control runs automatically. No Start or Stop action is needed.', 66, 630, 21, (155, 170, 190))
        canvas.text(self.battery.text(self.values['remoteAddress'], self.values['adapterAddress']), 66, 682, 19, (155, 170, 190))


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
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                os.set_blocking(worker.stdout.fileno(), False)
                log = os.open(STATE / ('receiver-output-' + str(os.getpid()) + '.log'), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
                app.worker = worker; canvas.minimize()
                write_status('native-status.json', {'status': 'worker-starting', 'pid': os.getpid(), 'workerPid': worker.pid})
            if not handoff: app.battery.refresh(worker)
            battery_text = None
            while True:
                for event, params in bus.events():
                    if event == 'relaunch':
                        canvas.restore()
                        app.battery.refresh(worker)
                        try: consume_installer(params, app.apply, stop=app.stop_runtime)
                        except (OSError, ValueError, RuntimeError) as error: app.message = str(error)[:160]
                        app.draw(canvas)
                    elif event == 'close':
                        stop_signal[0] = True
                current_battery = app.battery.text(app.values['remoteAddress'], app.values['adapterAddress'])
                if current_battery != battery_text:
                    battery_text = current_battery; app.draw(canvas)
                programming = app.infrared is not None and app.infrared.busy
                if stop_signal[0] and not closing and not programming:
                    closing = True
                    # A system close may terminate the native receiver window.
                    # Permit one replacement after it exits, without undoing an
                    # installer's maintenance stop or bypassing the power gate.
                    try: accepted(bus.request('resume', {}))
                    except (OSError, ValueError, RuntimeError): pass
                    if worker is not None and worker.poll() is None:
                        try: accepted(bus.request('drain', {}))
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
                        worker.stdout.close(); worker.stdin.close(); worker = None; app.worker = None
                        if closing or not app.stop_requested:
                            break  # Next connection requires a fresh native jail.
                        app.message = 'Finishing input cleanup before opening settings.'
                        app.draw(canvas)
                if app.settings_tick(canvas): app.draw(canvas)
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
        if worker is not None and worker.stdin is not None: worker.stdin.close()
        if log is not None: os.close(log)
        if canvas is not None: canvas.close()
