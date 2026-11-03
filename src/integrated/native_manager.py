"""Native settings window and an independently attested input worker."""
import json
import queue
import threading
import os
import re
import signal
import stat
import subprocess
import time
from pathlib import Path
from entry import Setup, ARROWS, BACK
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
    values = value['settings']
    if value['action'] == 'stop':
        values = settings.validate(values)
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
    save_label = 'Save and restart'
    show_device_fields = False

    def __init__(self, state, bus):
        super().__init__(state)
        self.bus = bus
        self.pairing = None
        self.focus = 3
        self.stop_requested = False
        self.worker = None
        self.pending_settings = None
        self.resume_after_settings = False
        self.next_settings_check = 0
        self.saving_assignments = False
        self.save_in_progress = False
        self.assignment_results = queue.Queue()
        self.pending_assignments = {}
        self.saved_values = dict(self.values)
        self.confirm_action = None
        self.confirm_focus = 0
        self.confirm_boxes = []
        from battery_status import ScreenReading
        self.battery = ScreenReading(state)
        if self.message in ('Saved identities loaded. This preview does not start remote control.',
                            'Enter the paired Siri Remote Bluetooth address. Other identities are detected.'):
            self.message = ''

    def refresh_pairing(self):
        if self.controls_disabled or self.infrared is not None or self.editing is not None:
            return
        if self.pairing is not None:
            if self.pairing.visible: return
            self.pairing.close()
        from pairing_screen import PairingScreen
        self.pairing = PairingScreen(self)

    def enable_startup(self):
        reply = accepted(self.bus.request('startupPrepare', {}))
        if reply.get('status') == 'repair-required':
            self.repair_startup()
            reply = accepted(self.bus.request('startupPrepare', {}))
            if reply.get('status') == 'registered': return
        if reply.get('status') == 'registered':
            repaired = self.repair_startup()
            if not repaired: return
            reply = accepted(self.bus.request('startupPrepare', {}))
        if reply.get('status') != 'create-required': raise RuntimeError('Automatic startup is unavailable')
        created = accepted(self.bus.create_startup(reply['token']))
        activity_id = created.get('activityId')
        if type(activity_id) is not int or activity_id <= 0: raise RuntimeError('Automatic startup registration is unconfirmed')
        accepted(self.bus.request('startupBind', {'token': reply['token'], 'activityId': activity_id}))

    def repair_startup(self):
        reply = accepted(self.bus.request('startupRepair', {}))
        if reply.get('status') != 'cancel-required': return False
        accepted(self.bus.cancel_startup(reply['activityId']))
        accepted(self.bus.request('startupCancelled', {'activityId': reply['activityId'], 'resetToken': reply['resetToken']}))
        return True

    def detect_tv(self, values):
        if type(values) is not dict:
            raise ValueError('Invalid device settings.')
        adapter = self.bus.tv_address()
        saved = values.get('adapterAddress')
        if saved and (type(saved) is not str or saved.strip().lower() != adapter):
            raise ValueError('The saved TV identity does not match this TV. Settings were not changed.')
        remote = values.get('remoteAddress', '')
        if type(remote) is not str:
            raise ValueError('Enter the remote Bluetooth address first.')
        remote = remote.strip().lower()
        # A verified saved serial remains usable when webOS omits the LE display name.
        prior = self.saved_values if remote == self.saved_values.get('remoteAddress') and adapter == self.saved_values.get('adapterAddress') else {}
        verified = getattr(self, 'paired_serial', None) or prior.get('remoteName')
        name = self.bus.remote_name(remote, adapter, verified)
        return settings.validate({**values, 'remoteAddress': remote, 'adapterAddress': adapter, 'remoteName': name})

    def apply(self, values, start=True):
        if self.saving_assignments or self.pending_settings is not None:
            raise RuntimeError("Wait for settings to finish before updating.")
        if self.infrared is not None:
            raise RuntimeError('Close button settings before updating device settings or starting input.')
        values = self.detect_tv(values)
        self.persist_device(values)
        self.activate_settings()

    def persist_device(self, values):
        accepted(self.bus.request('configure', {'settings': values}))
        settings.save(self.state, values)
        self.values.update({key: values[key] for key in (*settings.FIELDS, *settings.PREFERENCES)})
        self.saved_values = dict(self.values)
    def activate_settings(self):
        # Both installer configure and the TV Save action activate reception.
        # Keep the old argument for staged installer requests from earlier builds.
        self.enable_startup()
        accepted(self.bus.request('start', {}))
        self.message = 'Settings saved.'
        self.resume_after_settings = False
        self.done = True  # A fresh post-HID launch must inherit fresh input nodes.

    def stop_runtime(self):
        """Installer maintenance only; never exposed as a settings choice."""
        if self.saving_assignments or self.infrared is not None and self.infrared.busy:
            raise RuntimeError('Wait for the infrared operation to finish before updating.')
        self.pending_settings = None
        self.resume_after_settings = False
        self.stop_requested = True
        reply = accepted(self.bus.request('stop', {}))
        self.message = 'Stopping input; automatic startup disabled.' if reply['status'] == 'stop-requested' else reply['status']

    @property
    def controls_disabled(self):
        return self.save_in_progress or self.saving_assignments or self.pending_settings is not None or self.done

    def prepare_settings(self, action, values=None):
        if self.pending_settings is not None:
            return
        accepted(self.bus.request('drain', {}))
        self.stop_requested = True  # Keep the window after the worker finishes.
        self.resume_after_settings = True
        self.pending_settings = (action, values, time.monotonic() + 20)
        self.next_settings_check = 0
        self.message = 'Resetting cursor orientation. Please wait...' if action == 'recenter' else 'Saving settings and restarting. Please wait...'

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
            if action == 'save' and self.pending_assignments:
                self.persist_device(values)
                self.start_assignment_batch(dict(self.pending_assignments))
            elif action == 'save':
                self.apply(values)
            elif action == 'recenter':
                self.resume_settings()
            else:
                raise RuntimeError('Unknown settings operation.')
        except (OSError, ValueError, RuntimeError) as error:
            self.pending_settings = None
            self.save_in_progress = False
            self.message = str(error)[:160]
        return True

    def start_assignment_batch(self, changes):
        from tv_assignments import plan
        ordered = plan(self.state, changes)
        self.saving_assignments = True
        self.message = 'Saving button assignments. Please wait...'
        def work():
            completed = []
            result = {'status': 'saved'}
            for key, action in ordered:
                button, delay = (int(part, 16) for part in key.split(':'))
                try:
                    result = self.program_ir(self.state, 'assign', button, delay, action)
                except Exception:
                    result = {'status': 'uncertain'}
                if result.get('status') != 'saved': break
                completed.append(key)
            self.assignment_results.put((changes, completed, result))
        threading.Thread(target=work, name='save-button-assignments', daemon=False).start()

    def assignments_tick(self):
        try: changes, completed, result = self.assignment_results.get_nowait()
        except queue.Empty: return False
        self.saving_assignments = False
        for key in completed:
            if self.button_drafts.get(key) == changes[key]: self.button_drafts.pop(key)
        self.pending_assignments = {}
        if len(completed) == len(changes):
            try: self.activate_settings()
            except (OSError, ValueError, RuntimeError) as error:
                self.save_in_progress = False
                self.message = str(error)[:160]
        else:
            self.save_in_progress = False
            self.message = '%d of %d assignments saved. ' % (len(completed), len(changes))
            self.message += result.get('message') or 'The remaining changes were not confirmed.'
            if result.get('status') in ('uncertain', 'partial'):
                self.message += ' Check the remote before retrying.'
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
        try:
            idle()
        except (OSError, ValueError, RuntimeError) as error:
            return {'status': 'not-sent', 'message': str(error)[:160]}
        from tv_assignments import assign
        return assign(*args, program=lambda *request: execute(*request, idle=idle))

    def has_unsaved(self):
        return bool(self.button_drafts) or self.values != self.saved_values

    def close_settings(self):
        if self.has_unsaved():
            self.confirm_action = "discard"
        elif self.resume_after_settings:
            self.confirm_action = "resume"
        else:
            self.done = True
        self.confirm_focus = 0

    def choose(self, index, canvas):
        if self.controls_disabled: return
        if self.editing is not None:
            return super().choose(index, canvas)
        try:
            if index == 5:
                self.confirm_action = 'save'
                self.confirm_restart(canvas)
            elif index == 7:
                self.close_settings()
            elif index == 6:
                super().choose(index, canvas)
                self.infrared.detail = 'Both remotes can browse. No change is sent until Save and restart.'
            elif index == 8:
                if self.has_unsaved():
                    self.message = 'Choose Save and restart, or discard pending changes, before resetting cursor orientation.'
                    return
                self.confirm_action = 'recenter'
                self.confirm_focus = 0
            elif index == 3:
                self.values['gyroEnabled'] = not self.values['gyroEnabled']
                self.message = 'Choose Save and restart to apply this preference.'
            else:
                super().choose(index, canvas)
        except (OSError, ValueError, RuntimeError) as error:
            self.message = str(error)[:160]
            self.done = False

    def confirm_restart(self, canvas=None):
        if self.controls_disabled: return
        action = self.confirm_action
        self.confirm_action = None
        try:
            if action == 'save':
                self.save_in_progress = True
                self.message = 'Saving settings and restarting. Please wait...'
                if canvas is not None: self.draw(canvas)
                values = self.detect_tv({'schema': 1, **self.values})
                from tv_assignments import plan, displayed_bindings
                self.pending_assignments = displayed_bindings(self.state, self.button_drafts)
                plan(self.state, self.pending_assignments)
                self.prepare_settings('save', values)
            elif action == 'recenter':
                self.save_in_progress = True
                self.prepare_settings('recenter')
            elif action == 'resume':
                self.resume_settings()
            elif action == 'discard':
                self.button_drafts.clear()
                self.values = dict(self.saved_values)
                self.resume_settings()
        except (OSError, ValueError, RuntimeError) as error:
            self.done = False
            self.save_in_progress = False
            self.message = str(error)[:160]

    def draw(self, canvas):
        if self.pairing is not None and self.pairing.visible:
            return self.pairing.draw(canvas)
        if self.confirm_action is None:
            return super().draw(canvas)
        canvas.clear()
        discard = self.confirm_action == 'discard'
        canvas.text('Discard unsaved changes?' if discard else 'Reset cursor orientation?' if self.confirm_action == 'recenter' else 'Restart remote control?', 64, 90, 36)
        canvas.text('Unsaved edits will be discarded when you close this screen.' if discard else 'Remote control will pause briefly while the app restarts.', 66, 205, 26)
        canvas.text('This screen will close. The TV may briefly show Home or reopen the app.', 66, 258, 24)
        canvas.text('Lay Siri Remote flat, top facing up and tip toward the TV. Use the LG remote to confirm.' if self.confirm_action == 'recenter' else 'Use the LG remote until Siri Remote reception resumes.', 66, 311, 22, max_width=1148)
        self.confirm_boxes = [(64, 425, 552, 70), (640, 425, 552, 70)]
        for index, title in enumerate(('Cancel', 'Discard and close' if discard else 'Restart')):
            box = self.confirm_boxes[index]
            canvas.rectangle(box, (30, 113, 156) if index == self.confirm_focus else (36, 48, 65))
            canvas.text(title, box[0]+24, box[1]+21, 27)
        canvas.text('Cancel or Back keeps this screen open without restarting.', 66, 565, 23, (155, 170, 190))
        canvas.present()

    def handle(self, event, canvas):
        if self.pairing is not None and self.pairing.visible:
            return self.pairing.handle(event)
        if self.controls_disabled:
            return
        if self.confirm_action is not None:
            kind, value = event
            if kind == 'close' or kind == 'key' and value in BACK:
                self.confirm_action = None
            elif kind == 'key' and value in ARROWS:
                self.confirm_focus = 1 - self.confirm_focus
            elif kind == 'key' and value in (13, 1073741912):
                if self.confirm_focus == 1: self.confirm_restart(canvas)
                else: self.confirm_action = None
            elif kind == 'click':
                for index, (x,y,w,h) in enumerate(self.confirm_boxes):
                    if x <= value[0] < x+w and y <= value[1] < y+h:
                        if index == 1: self.confirm_restart(canvas)
                        else: self.confirm_action = None
                        break
            return
        if (self.infrared is None and self.editing is None
                and event[0] == 'key' and event[1] in BACK):
            self.close_settings()
            return
        was_infrared = self.infrared is not None
        if self.pending_settings is not None:
            return  # Wait for cooperative cleanup; never edit a live session.
        super().handle(event, canvas)
        if was_infrared and self.infrared is None and self.resume_after_settings:
            self.message = 'Reception is paused. Choose Close to restart it; use the LG remote here.'
        if self.done:
            try:
                self.resume_settings()
            except (OSError, ValueError, RuntimeError) as error:
                self.done = False
                self.message = str(error)[:160]

    def draw_footer(self, canvas):
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
    worker = None; canvas = None; app = None; closing = False; log = None; logged = 0
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
            if not handoff: app.refresh_pairing()
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
                        try:
                            consumed = consume_installer(params, app.apply, stop=app.stop_runtime)
                            if not consumed: app.refresh_pairing()
                        except (OSError, ValueError, RuntimeError) as error: app.message = str(error)[:160]
                        app.draw(canvas)
                    elif event == 'close':
                        stop_signal[0] = True
                current_battery = app.battery.text(app.values['remoteAddress'], app.values['adapterAddress'])
                if current_battery != battery_text:
                    battery_text = current_battery; app.draw(canvas)
                programming = app.saving_assignments or app.infrared is not None and app.infrared.busy
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
                if app.pairing is not None and app.pairing.tick(): app.draw(canvas)
                if app.assignments_tick(): app.draw(canvas)
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
        if app is not None and app.pairing is not None: app.pairing.close()
        if canvas is not None: canvas.close()
