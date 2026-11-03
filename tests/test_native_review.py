"""Regression checks for actual event ordering, storage and cleanup failures."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/native'), str(ROOT / 'src'), str(ROOT / 'tests')]
from entry import Setup
from graphics import Canvas
from ir_screen import InfraredScreen, PRESETS
import settings
import tv_assignments
import ir_programmer as ir
from test_native_ir import TV, VALUES


class Screen:
    def __init__(self): self.text_active = False; self.labels = []
    def start_text(self): self.text_active = True
    def stop_text(self): self.text_active = False
    def clear(self): self.labels = []
    def rectangle(self, *args): pass
    def text(self, value, *args, **kwargs): self.labels.append(value)
    def present(self): pass


class ReviewTests(unittest.TestCase):
    def test_hex_keyboard_up_down_preserves_column(self):
        app = InfraredScreen(Path('/unused'))
        app.choose(2); app.choose(len(PRESETS)+1)
        app.handle(('key', 1073741905))
        self.assertEqual(app.focus, 6)
        app.handle(('key', 13))
        app.handle(('key', 1073741906))
        self.assertEqual(app.focus, 0)
        app.handle(('key', 13))
        self.assertEqual(app.draft, '60')

    def test_ir_keyboard_enables_and_disables_sdl_text_input(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Setup(Path(folder)); canvas = Screen()
            app.choose(0, canvas); app.handle(('key', 27), canvas)
            self.assertFalse(canvas.text_active)
            app.choose(6, canvas)
            app.infrared.focus = 2
            app.handle(('key', 13), canvas)
            app.infrared.focus = len(PRESETS)+1
            app.handle(('key', 13), canvas)
            self.assertTrue(canvas.text_active)
            app.handle(('text', '4D'), canvas)
            app.handle(('key', 27), canvas)
            self.assertFalse(canvas.text_active)
            self.assertEqual(app.infrared.code, '')

    def test_key_repeat_does_not_retrigger_confirm_or_gyro_toggle(self):
        frames = []
        for key, repeat in ((13, 0), (13, 1), (27, 1), (1073741905, 1)):
            event = bytearray(64); event[:4] = (0x300).to_bytes(4, 'little')
            event[17] = repeat; event[24:28] = key.to_bytes(4, 'little', signed=True)
            frames.append(bytes(event))
        canvas = Canvas.__new__(Canvas)
        def poll(buffer):
            if not frames: return 0
            ctypes.memmove(buffer, frames.pop(0), 64); return 1
        canvas.poll = poll
        self.assertEqual(list(canvas.events()), [('key', 13), ('key', 1073741905)])

    def test_fifo_settings_fail_promptly_instead_of_hanging(self):
        for module, name in (('settings', 'settings.json'), ('tv_assignments', 'tv-assignments.json')):
            with tempfile.TemporaryDirectory() as folder:
                os.mkfifo(Path(folder) / name)
                script = "import sys;sys.path[:0]=sys.argv[1:3];import importlib;importlib.import_module(sys.argv[3]).load(sys.argv[4])"
                result = subprocess.run([sys.executable, '-c', script, str(ROOT/'src/native'),
                                         str(ROOT/'src'), module, folder], capture_output=True, timeout=2)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b'ValueError', result.stderr)

    def test_saved_tv_assignment_is_visible_after_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            tv_assignments.execute(folder, 'set', 16, 2)
            app = InfraredScreen(Path(folder)); canvas = Screen()
            app.choose(0); app.choose(4); app.choose(1); app.choose(1)
            app.draw(canvas)
            self.assertTrue(any('Saved TV' in t and 'Screen off / restore' in t for t in canvas.labels))
            app.choose(1); app.choose(0); app.draw(canvas)
            self.assertTrue(any('Saved TV' in t and 'None' in t for t in canvas.labels))

    def test_owned_gatt_client_is_released_even_if_runtime_starts(self):
        tv = TV()
        def idle():
            if tv.writes(): raise RuntimeError('another runtime started')
        result = ir.program(VALUES, 'set', 1, 2, '08', tv, lambda r: None, idle=idle)
        self.assertEqual(len(tv.writes()), 1)
        self.assertTrue(result['clientReleased'])
        self.assertIn(('gatt/disconnect', {'clientId': '005'}), tv.calls)

    def test_final_receipt_failure_keeps_delivery_result_and_does_not_repeat(self):
        tv = TV()
        def record(value):
            if value['status'] == 'submitted': raise OSError('disk full')
        result = ir.program(VALUES, 'set', 1, 2, '08', tv, record, idle=lambda: None)
        self.assertEqual(result['status'], 'submitted')
        self.assertFalse(result['receiptSaved'])
        self.assertTrue(result['clientReleased'])
        self.assertEqual(len(tv.writes()), 1)

    def test_each_queued_pointer_event_uses_the_visible_screen(self):
        import entry
        with tempfile.TemporaryDirectory() as folder:
            app = Setup(Path(folder))
            class Events(Screen):
                def events(self):
                    # The first click enters the name editor. For the next click,
                    # its old setup hitbox maps to F, while the visible key is 6.
                    yield ('click', (80, 280))
                    yield ('click', (400, 520))
                    yield ('close', None)
                def close(self): pass
            canvas = Events()
            with patch.object(entry, 'Setup', return_value=app), patch.object(entry, 'Canvas', return_value=canvas):
                entry.main()
            self.assertEqual(app.values['remoteName'], '6')


if __name__ == '__main__': unittest.main()
