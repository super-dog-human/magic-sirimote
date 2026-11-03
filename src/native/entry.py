"""Native setup and explicit infrared programming; no automatic input runtime."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import settings
from graphics import Canvas

APP_ID = 'org.magicsirimote.app'
ARROWS = {1073741906: -1, 1073741905: 1, 1073741904: -1, 1073741903: 1}
BACK = (27, 461, 1073742094)


class Setup:
    def __init__(self, state):
        self.state = state
        self.values = {**dict.fromkeys(settings.FIELDS, ''), 'gyroEnabled': True}
        self.focus = 0
        self.editing = None
        self.key_focus = 0
        self.keys = []
        self.message = 'Use the original LG remote to enter your device identities.'
        self.done = False
        self.boxes = []
        self.infrared = None
        try:
            self.values.update({key: value for key, value in settings.load(state).items() if key in (*settings.FIELDS, 'gyroEnabled')})
            self.message = 'Saved identities loaded. This preview does not start remote control.'
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            self.message = 'Saved settings could not be read. Check and save the fields again.'

    def choose(self, index, canvas):
        if self.editing is not None:
            key = self.keys[index]
            field = settings.FIELDS[self.editing]
            if key == 'Done':
                self.editing = None
                canvas.stop_text()
            elif key == 'Delete':
                self.values[field] = self.values[field][:-1]
            elif key == 'Clear':
                self.values[field] = ''
            elif key == 'Case':
                self.keys = [k.swapcase() if len(k) == 1 and k.isalpha() else k for k in self.keys]
            elif len(self.values[field]) < settings.LIMITS[self.editing]:
                self.values[field] += key
            return
        if index < 3:
            self.editing = index
            alphabet = '0123456789abcdef:' if index != 1 else 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-'
            self.keys = list(alphabet) + (['Case'] if index == 1 else []) + ['Delete', 'Clear', 'Done']
            self.key_focus = 0
            canvas.start_text()
        elif index == 3:
            self.values['gyroEnabled'] = not self.values['gyroEnabled']
            self.message = 'Gyro preference changed. Choose Save settings; runtime integration is pending.'
        elif index == 4:
            from device_check import inspect
            try:
                result = inspect()
                self.message = ('Native input access is available. Pairing and runtime still need verification.'
                                if result['compatibleInputAccess'] else 'Required native input access is unavailable on this TV.')
                # Only process/device capability flags; no identities or input reports.
                (self.state / 'capabilities.json').write_text(json.dumps(result) + '\n')
            except (OSError, ValueError):
                self.message = 'The compatibility check could not finish.'
        elif index == 5:
            try:
                settings.save(self.state, {'schema': 1, **self.values})
                self.message = 'Settings saved. Gyro preference is not active until runtime integration is complete.'
            except (OSError, ValueError) as error:
                self.message = str(error) if isinstance(error, ValueError) else 'Could not save settings.'
        elif index == 6:
            from ir_screen import InfraredScreen
            self.infrared = InfraredScreen(self.state)
        else:
            self.done = True

    def handle(self, event, canvas):
        if event[0] == 'close':
            if self.infrared is None or not self.infrared.busy:
                canvas.stop_text()
                self.done = True
            return
        if self.infrared is not None:
            was_editing = self.infrared.editing
            self.infrared.handle(event)
            if was_editing != self.infrared.editing:
                (canvas.start_text if self.infrared.editing else canvas.stop_text)()
            if self.infrared.done:
                self.infrared = None
            return
        kind, value = event
        if kind == 'close':
            self.done = True
        elif kind == 'click':
            for index, box in self.boxes:
                x, y, width, height = box
                if x <= value[0] < x + width and y <= value[1] < y + height:
                    self.choose(index, canvas)
                    break
        elif kind == 'text' and self.editing is not None:
            field = settings.FIELDS[self.editing]
            allowed = '0123456789abcdefABCDEF:' if self.editing != 1 else 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-'
            self.values[field] = (self.values[field] + ''.join(c for c in value if c in allowed))[:settings.LIMITS[self.editing]]
        elif kind == 'key':
            if value in BACK:
                if self.editing is None:
                    self.done = True
                else:
                    self.editing = None
                    canvas.stop_text()
            elif value in ARROWS:
                if self.editing is None:
                    self.focus = (self.focus + ARROWS[value]) % 8
                else:
                    step = ARROWS[value] * (10 if value in (1073741906, 1073741905) else 1)
                    self.key_focus = (self.key_focus + step) % len(self.keys)
            elif value in (13, 1073741912):
                self.choose(self.focus if self.editing is None else self.key_focus, canvas)
            elif value == 8 and self.editing is not None:
                field = settings.FIELDS[self.editing]
                self.values[field] = self.values[field][:-1]

    def draw(self, canvas):
        if self.infrared is not None:
            self.infrared.draw(canvas)
            return
        canvas.clear()
        canvas.text('Magic Sirimote', 64, 42, 40)
        canvas.text('Device setup and button assignments', 66, 94, 23, (114, 191, 227))
        self.boxes = []
        if self.editing is not None:
            canvas.text(settings.LABELS[self.editing], 66, 160, 27)
            canvas.rectangle((64, 207, 1152, 66), (36, 48, 65))
            canvas.text(self.values[settings.FIELDS[self.editing]] + '|', 82, 226, 29, max_width=1110)
            for index, key in enumerate(self.keys):
                row, column = divmod(index, 10)
                box = (64 + column * 116, 300 + row * 64, 106, 54)
                canvas.rectangle(box, (30, 113, 156) if index == self.key_focus else (36, 48, 65))
                canvas.text(key, box[0] + 13, box[1] + 13, 23, max_width=82)
                self.boxes.append((index, box))
            canvas.text('Select characters with arrows and OK, or use a USB keyboard.', 66, 632, 22)
            canvas.text('Back closes the keyboard. Choose Save settings on the previous screen.', 66, 665, 20, (155, 170, 190))
        else:
            for index, field in enumerate(settings.FIELDS):
                y = 140 + index * 91
                canvas.text(settings.LABELS[index], 66, y, 21, (155, 170, 190))
                box = (64, y + 31, 1152, 57)
                canvas.rectangle(box, (30, 113, 156) if self.focus == index else (36, 48, 65))
                canvas.text(self.values[field] or 'Select to enter', 82, y + 44, 25, max_width=1110)
                self.boxes.append((index, box))
            box = (64, 416, 1152, 54)
            canvas.rectangle(box, (30, 113, 156) if self.focus == 3 else (36, 48, 65))
            canvas.text('Gyro cursor: ' + ('On' if self.values['gyroEnabled'] else 'Off') + '  (OK to toggle)', 82, 430, 25)
            self.boxes.append((3, box))
            for index, title in enumerate(('Check this TV', 'Save settings', 'Buttons', 'Close'), 4):
                box = (64 + (index - 4) * 292, 492, 274, 61)
                canvas.rectangle(box, (30, 113, 156) if self.focus == index else (36, 48, 65))
                canvas.text(title, box[0] + 25, box[1] + 17, 25)
                self.boxes.append((index, box))
            canvas.text(self.message, 66, 568, 22, max_width=1148)
            self.draw_footer(canvas)
        canvas.present()

    def draw_footer(self, canvas):
        # Compose the entire frame before presenting it. SDL does not promise
        # that any backbuffer content survives a presentation.
        canvas.text('IR programs the remote. TV assignments are saved only; input startup is separate.', 66, 630, 21, (155, 170, 190))
        canvas.text('Developer Mode expiry is managed separately using your usual tools.', 66, 663, 20, (155, 170, 190))


def main(state=None, bus=None):
    state = ROOT / 'state' if state is None else Path(state)
    app = Setup(state)
    canvas = Canvas(APP_ID)
    try:
        app.draw(canvas)
        while not app.done:
            if bus is not None:
                for event, _params in bus.events():
                    if event == 'relaunch':
                        canvas.restore()
                        app.draw(canvas)
                    elif event == 'close':
                        app.handle(('close', None), canvas)
            if app.infrared is not None and app.infrared.tick():
                app.draw(canvas)
            for event in canvas.events():
                app.handle(event, canvas)
                if app.done:
                    break
                # Rebuild click targets before handling the next queued event.
                app.draw(canvas)
            time.sleep(.02)
    finally:
        canvas.close()


if __name__ == '__main__':
    main()
