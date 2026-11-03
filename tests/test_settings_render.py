"""Each UI redraw publishes one complete frame, with no retained backbuffer."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/integrated'), str(ROOT / 'src/native'), str(ROOT / 'src')]
from native_manager import RuntimeSetup
from entry import Setup
from ir_screen import InfraredScreen

class DiscardingCanvas:
    def __init__(self): self.frame = []; self.frames = []
    def clear(self): self.frame = []
    def text(self, value, *args, **kwargs): self.frame.append(value)
    def rectangle(self, *args): pass
    def present(self):
        self.frames.append(self.frame[:])
        self.frame = []  # SDL does not preserve the backbuffer after presentation.

class SettingsRenderTests(unittest.TestCase):
    def test_runtime_main_frame_keeps_controls_and_battery_together_on_every_redraw(self):
        with tempfile.TemporaryDirectory() as d:
            app = RuntimeSetup(Path(d), Mock()); canvas = DiscardingCanvas()
            for level in ('Battery: reading...', 'Battery: 75%', 'Battery: unavailable'):
                app.battery.text = Mock(return_value=level)
                before = len(canvas.frames); app.draw(canvas)
                self.assertEqual(len(canvas.frames) - before, 1)
                for title in ('Magic Sirimote', 'Save settings', 'Buttons', level):
                    self.assertIn(title, canvas.frames[-1])
                self.assertTrue(any('runs automatically' in text for text in canvas.frames[-1]))
                self.assertFalse(any('input startup is separate' in text for text in canvas.frames[-1]))
                self.assertEqual([i for i, _ in app.boxes], [0,1,3,4,5,6,7])

    def test_keyboard_and_button_editor_still_present_one_complete_frame(self):
        with tempfile.TemporaryDirectory() as d:
            app = RuntimeSetup(Path(d), Mock()); canvas = DiscardingCanvas()
            app.editing = 0; app.keys = ['0', 'Done']; app.draw(canvas)
            self.assertEqual(len(canvas.frames), 1)
            self.assertIn('Magic Sirimote', canvas.frames[-1])
            self.assertIn('Done', canvas.frames[-1])
            app.editing = None; app.infrared = InfraredScreen(Path(d)); app.draw(canvas)
            self.assertEqual(len(canvas.frames), 2)
            self.assertIn('Button assignments', canvas.frames[-1])
            self.assertFalse(any(text.startswith('Battery:') for text in canvas.frames[-1]))

    def test_standalone_setup_preserves_its_footer_and_single_presentation(self):
        with tempfile.TemporaryDirectory() as d:
            app = Setup(Path(d)); canvas = DiscardingCanvas(); app.draw(canvas)
            self.assertEqual(len(canvas.frames), 1)
            self.assertIn('Buttons', canvas.frames[0])
            self.assertTrue(any('input startup is separate' in text for text in canvas.frames[0]))

if __name__ == '__main__': unittest.main()
