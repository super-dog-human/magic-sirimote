"""Exercise real SDL event decoding through both native settings screens."""
import ctypes
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src/native'), str(ROOT/'src/integrated'), str(ROOT/'src')]
from graphics import Canvas
from native_manager import RuntimeSetup
from ir_screen import InfraredScreen


def decode(pairs):
    frames = []
    for key, repeat in pairs:
        raw = bytearray(64); raw[:4] = (0x300).to_bytes(4, 'little')
        raw[16] = 1; raw[17] = repeat; raw[24:28] = key.to_bytes(4, 'little', signed=True)
        frames.append(bytes(raw))
    canvas = Canvas.__new__(Canvas)
    def poll(buffer):
        if not frames: return 0
        ctypes.memmove(buffer, frames.pop(0), 64); return 1
    canvas.poll = poll
    return list(canvas.events())

class RemoteNavigationTests(unittest.TestCase):
    def test_keyboard_layout_matches_the_tv_capture(self):
        from graphics import KeyboardEvent, Keysym, TextInputEvent
        self.assertEqual(KeyboardEvent.keysym.offset, 20)
        self.assertEqual(KeyboardEvent.keysym.offset + Keysym.sym.offset, 24)
        self.assertEqual(KeyboardEvent.repeat.offset, 17)
        self.assertEqual(TextInputEvent.text.offset, 16)
        frames = []
        for scan, key in ((82,1073741906),(81,1073741905),(80,1073741904),(79,1073741903),(40,13)):
            raw = bytearray(64); raw[:4] = (0x300).to_bytes(4,'little')
            raw[12:16] = (256).to_bytes(4,'little')  # Must not be mistaken for repeat.
            raw[16:20] = bytes([1,0,228,255])  # Padding observed on this TV.
            raw[20:24] = scan.to_bytes(4,'little')
            raw[24:28] = key.to_bytes(4,'little',signed=True)
            frames.append(bytes(raw))
        canvas = Canvas.__new__(Canvas)
        def poll(buffer):
            if not frames: return 0
            ctypes.memmove(buffer,frames.pop(0),64); return 1
        canvas.poll=poll
        self.assertEqual(list(canvas.events()), [('key',k) for k in (1073741906,1073741905,1073741904,1073741903,13)])

    def test_text_skips_the_webos_input_source_field(self):
        raw=bytearray(64);raw[:4]=(0x303).to_bytes(4,'little')
        raw[12:16]=b'NOPE';raw[16:19]=b'4D\0'
        frames=[bytes(raw)];canvas=Canvas.__new__(Canvas)
        def poll(buffer):
            if not frames:return 0
            ctypes.memmove(buffer,frames.pop(),64);return 1
        canvas.poll=poll
        self.assertEqual(list(canvas.events()), [('text','4D')])

    def test_remote_arrow_repeat_is_kept_but_ok_repeat_is_suppressed(self):
        self.assertEqual(decode([(1073741905,1), (13,0), (13,1)]), [('key',1073741905), ('key',13)])

    def test_main_and_buttons_receive_navigation_and_ok(self):
        with tempfile.TemporaryDirectory() as d:
            app=RuntimeSetup(Path(d),Mock());canvas=Mock()
            for event in decode([(1073741905,0),(1073741905,0),(1073741906,0)]):app.handle(event,canvas)
            self.assertEqual(app.focus,1)
            app.infrared=InfraredScreen(Path(d))
            for event in decode([(1073741905,0),(1073741903,0),(13,0)]):app.handle(event,canvas)
            self.assertEqual(app.infrared.button,1);self.assertEqual(app.infrared.delay,2)
            self.assertTrue(app.infrared.picking)
            app.handle(('key',27),canvas);self.assertIsNone(app.infrared);self.assertFalse(app.done)


    def test_hex_picker_keeps_grid_step_for_remote_up_down(self):
        with tempfile.TemporaryDirectory() as d:
            app = RuntimeSetup(Path(d), Mock()); canvas = Mock()
            app.infrared = InfraredScreen(Path(d)); app.infrared.editing = True
            for event in decode([(1073741905,0),(13,0),(1073741906,0),(13,0)]): app.handle(event, canvas)
            self.assertEqual(app.infrared.draft, '60')

if __name__ == '__main__': unittest.main()
