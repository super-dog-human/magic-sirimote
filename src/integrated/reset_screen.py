"""Confirmed full reset, with progress and explicit continuation after failure."""
import fcntl
import os
import queue
import stat
import threading
import time
from pathlib import Path
import reset_remote
import settings


class ResetScreen:
    def __init__(self, app):
        self.app = app; self.visible = True; self.busy = False
        self.focus = 0; self.boxes = []; self.phase = 'confirm'; self.lock = None
        self.results = queue.Queue(); self.next_check = 0; self.deadline = 0
        self.message = ''; self.value = None; self.can_resume = False
        self.recovery = None; self.recovery_bus = None
        try:
            self.value = reset_remote.load(app.state)
            self.phase = 'failed'; self.message = self.value['message'] or 'A previous reset did not finish.'
            self.can_resume = self.value['phase'] == 'stopping'
        except FileNotFoundError:
            pass

    def release(self):
        if self.lock is not None: os.close(self.lock); self.lock = None

    def begin(self):
        if self.busy: return
        try:
            self.lock = os.open(self.app.state / 'reset.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            info = os.fstat(self.lock)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                raise RuntimeError('Reset lock unavailable')
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.value = reset_remote.create(self.app.state)
            if self.app.pairing is not None:
                self.app.pairing.close(); self.app.pairing = None
            self.app.done = False
            self.busy = True; self.phase = 'preparing'; self.deadline = time.monotonic() + 30
            self.next_check = 0; self.message = 'Stopping remote control. Keep Siri Remote awake...'
        except Exception as error:
            self.fail(error)

    def close_recovery(self):
        if self.recovery_bus is not None:
            self.recovery_bus.__exit__(None, None, None)
            self.recovery_bus = None
        self.recovery = None

    def start_work(self):
        # Keep the verified GATT client alive until IR deletion has finished.
        # Dropping it here could undo the connection just restored for reset.
        self.phase = 'working'
        threading.Thread(target=self.worker, name='reset-remote', daemon=False).start()

    def start_recovery(self):
        from pairing_transport import BluetoothBus
        from reset_recovery import ResetRecovery
        self.recovery_bus = BluetoothBus().__enter__()
        self.recovery = ResetRecovery(self.recovery_bus, self.app.state, self.value)
        self.phase = 'reconnecting'
        self.message = self.recovery.message

    def fail(self, error):
        self.close_recovery()
        self.phase = 'failed'; self.busy = False
        self.can_resume = self.value is not None and self.value['phase'] == 'stopping'
        self.message = str(error)[:240]
        if self.value is not None:
            from reset_state import write
            self.value['message'] = self.message
            try: write(self.app.state / reset_remote.FILE, self.value)
            except (OSError, ValueError, RuntimeError):
                self.message = (self.message[:180] + ' Progress could not be saved; reopen the app.')
            finally: self.release()
        else: self.release()

    def worker(self):
        try:
            from control_processes import require_no_other_input, clean_state
            from ir_programmer import execute, runtime_idle
            from native_luna import Luna
            def idle():
                require_no_other_input()
                if not clean_state(): raise RuntimeError('Input cleanup is not confirmed')
                runtime_idle(allow_idle_service=True)
            def program(*args): return execute(*args, idle=idle)
            with Luna() as call:
                value = reset_remote.run(self.app.state, self.value, program, call, idle,
                                         lambda message: self.results.put(('progress', message)))
            self.results.put(('result', value))
        except Exception as error:
            self.results.put(('error', str(error)))

    def finish(self):
        self.close_recovery()
        from native_manager import accepted
        values = self.value['settings']
        reply = accepted(self.app.bus.request('reset', {'resetId': self.value['id'],
                         'remoteAddress': values['remoteAddress'], 'adapterAddress': values['adapterAddress']}))
        if reply.get('status') != 'reset': raise RuntimeError('App reset was not confirmed')
        reset_remote.finish_local(self.app.state, self.value)
        self.release(); self.busy = self.visible = False
        self.app.values = {**dict.fromkeys(settings.FIELDS, ''), 'gyroEnabled': True, 'gyroSensitivity': 3}
        self.app.saved_values = dict(self.app.values); self.app.paired_serial = None
        self.app.button_drafts.clear(); self.app.pending_assignments = {}
        self.app.resume_after_settings = False; self.app.save_in_progress = False
        self.app.reset = None
        if self.app.pairing is not None: self.app.pairing.close()
        self.app.pairing = None; self.app.refresh_pairing()
        if self.app.pairing is not None:
            self.app.pairing.flow.message = 'Reset complete. Pair Siri Remote and set up its buttons again.'

    def tick(self):
        if not self.visible or not self.busy: return False
        try:
            if self.phase == 'preparing':
                from native_manager import accepted
                value = accepted(self.app.bus.request('status', {}))
                # An interrupted reset may already have stopped everything.
                # Do not restart reception or send another stop in that case.
                clean = (value.get('cleanStop') is True and not value.get('processes', {}).get('legacy')
                         and value.get('startup', {}).get('enabled') is False)
                if not clean: self.app.stop_runtime(reset=self)
                self.app.stop_requested = True
                self.phase = 'stopping'
                return True
            if self.phase == 'reconnecting':
                before = self.message
                self.recovery.tick()
                self.message = self.recovery.message
                if self.recovery.phase == 'success': self.start_work(); return True
                if self.recovery.phase in ('failed', 'scanned'):
                    self.fail(self.message + ' Choose Continue reset to try again.'); return True
                return self.message != before
            if self.phase == 'stopping' and time.monotonic() >= self.next_check:
                from native_manager import accepted
                self.next_check = time.monotonic() + 1
                value = accepted(self.app.bus.request('status', {}))
                if value.get('cleanStop') is True and not value.get('processes', {}).get('legacy') and value.get('startup', {}).get('enabled') is False:
                    if self.value['unpaired']:
                        self.finish(); return True
                    if len(self.value['completed']) < len(reset_remote.SLOTS): self.start_recovery()
                    else: self.start_work()
                    return True
                elif time.monotonic() >= self.deadline:
                    raise RuntimeError('Input cleanup did not finish. Resume remote control, wake Siri Remote, and try again.')
            changed = False
            while True:
                try: kind, value = self.results.get_nowait()
                except queue.Empty: break
                changed = True
                if kind == 'progress': self.message = value
                elif kind == 'error': self.fail(value)
                elif kind == 'result':
                    self.value = value
                    if value['phase'] == 'clear': self.finish()
                    else: self.fail(value['message'])
            return changed
        except Exception as error:
            self.fail(error); return True

    def choose(self, index):
        if self.busy: return
        if index == 1: self.begin(); return
        if self.phase == 'confirm':
            self.visible = False; self.app.reset = None
        elif self.can_resume:
            try:
                from reset_state import retire
                retire(self.app.state, self.value['id'], [reset_remote.FILE])
                self.visible = False; self.app.reset = None
                self.app.start_saved()
            except Exception as error:
                self.app.reset = self; self.visible = True; self.fail(error)
        else:
            self.app.done = True

    def handle(self, event):
        if self.busy: return
        kind, value = event
        if kind == 'close' or kind == 'key' and value in (27, 461, 1073742094): self.choose(0)
        elif kind == 'key':
            if value in (1073741904,1073741903,1073741906,1073741905): self.focus = 1-self.focus
            elif value in (13,1073741912): self.choose(self.focus)
        elif kind == 'click':
            for i,(x,y,w,h) in enumerate(self.boxes):
                if x<=value[0]<x+w and y<=value[1]<y+h: self.choose(i); break

    def draw(self, canvas):
        canvas.clear()
        canvas.text('Reset Magic Sirimote?', 64, 70, 36)
        lines = ['Delete all short- and long-press infrared assignments on Siri Remote.',
                 'Remove this remote\'s TV pairing and reset all Magic Sirimote settings.',
                 'Power and volume IR control will stop. Pair and configure the remote again.',
                 'Other TV settings and other Bluetooth devices are not reset.',
                 'Keep Siri Remote awake and disconnect it from the Mac. Use the LG remote.']
        for i,line in enumerate(lines): canvas.text(line,66,150+i*45,23,max_width=1148)
        if self.phase == 'reconnecting':
            canvas.text('If searching: hold Siri Remote MENU + Volume Up for about 5 seconds.',66,370,21,max_width=1148)
        if self.message: canvas.text(self.message,66,410,21,max_width=1148)
        canvas.text('IR deletion uses delivery acknowledgements; the remote cannot read back its saved entries.',66,453,19,max_width=1148)
        labels = ('Cancel', 'Reset everything') if self.phase == 'confirm' else (
            'Resume remote control' if self.can_resume else 'Close', 'Continue reset')
        self.boxes=[] if self.busy else [(64,535,552,70),(640,535,552,70)]
        for i,label in enumerate(labels):
            box=(64+i*576,535,552,70)
            color=(27,34,44) if self.busy else (140,52,52) if i==1 and self.focus==1 else (30,113,156) if i==self.focus else (36,48,65)
            canvas.rectangle(box,color)
            canvas.text('Please wait...' if self.busy else label,box[0]+24,box[1]+21,25)
        canvas.present()
