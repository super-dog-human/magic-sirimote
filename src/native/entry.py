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
    save_label = 'Save'
    show_device_fields = True
    show_reset = False

    @property
    def main_focus(self):
        focus = settings.MAIN_FOCUS if self.show_device_fields else tuple(i for i in settings.MAIN_FOCUS if i != 0)
        return focus[:-2] + (9,) + focus[-2:] if self.show_reset else focus

    def __init__(self, state):
        self.state = state
        self.values = {**dict.fromkeys(settings.FIELDS, ''), 'gyroEnabled': True, 'gyroSensitivity': 3}
        self.focus = 0
        self.editing = None
        self.key_focus = 0
        self.keys = []
        self.message = 'Enter the paired Siri Remote Bluetooth address. Other identities are detected.'
        self.done = False
        self.boxes = []
        self.infrared = None
        self.button_drafts = {}
        try:
            self.values.update({key: value for key, value in settings.load(state).items() if key in (*settings.FIELDS, *settings.PREFERENCES)})
            self.message = 'Saved identities loaded. This preview does not start remote control.'
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            self.message = 'Saved settings could not be read. Check and save the fields again.'

    def detect_tv(self, values):
        adapter = settings.read_tv_address()
        saved = values.get('adapterAddress')
        if saved and (type(saved) is not str or saved.strip().lower() != adapter):
            raise ValueError('The saved TV identity does not match this TV. Settings were not changed.')
        remote = values.get('remoteAddress', '')
        if type(remote) is not str:
            raise ValueError('Enter the remote Bluetooth address first.')
        remote = remote.strip().lower()
        name = settings.read_remote_name(remote, adapter)
        return settings.validate({**values, 'remoteAddress': remote, 'adapterAddress': adapter, 'remoteName': name})

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
        if index == 0:
            if not self.show_device_fields: return
            self.editing = index
            alphabet = '0123456789abcdef:' if index != 1 else 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-'
            self.keys = list(alphabet) + (['Case'] if index == 1 else []) + ['Delete', 'Clear', 'Done']
            self.key_focus = 0
        elif index in (1, 2):
            return  # Device identifiers are detected, never edited.
        elif index == 3:
            self.values['gyroEnabled'] = not self.values['gyroEnabled']
            self.message = 'Gyro preference changed. Choose ' + self.save_label + '; runtime integration is pending.'
        elif index == 4:
            self.values['gyroSensitivity'] = self.values['gyroSensitivity'] % 5 + 1
        elif index == 8:
            self.message = 'Use the integrated app to reset cursor orientation.'
        elif index == 5:
            if self.button_drafts:
                self.message = 'Use the integrated app to save button assignments.'
                return
            try:
                values = self.detect_tv({'schema': 1, **self.values})
                settings.save(self.state, values)
                self.values.update({key: values[key] for key in settings.FIELDS})
                self.message = 'Settings saved. Gyro preference is not active until runtime integration is complete.'
            except (OSError, ValueError, RuntimeError) as error:
                self.message = str(error) if isinstance(error, (ValueError, RuntimeError)) else 'Could not save settings.'
        elif index == 6:
            from ir_screen import InfraredScreen
            self.infrared = InfraredScreen(self.state, drafts=self.button_drafts, save_label=self.save_label)
        else:
            self.done = True

    def handle(self, event, canvas):
        if event[0] == 'close':
            if self.infrared is None or not self.infrared.busy:
                canvas.stop_text()
                self.done = True
            return
        if self.infrared is not None:
            self.infrared.handle(event)
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
                    if index == 4 and self.editing is None:
                        self.values['gyroSensitivity'] = max(1, min(5, round((value[0] - 100) / 160) + 1))
                    else:
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
                if self.editing is None and self.focus == 4 and value in (1073741904, 1073741903):
                    self.values['gyroSensitivity'] = max(1, min(5, self.values['gyroSensitivity'] + ARROWS[value]))
                elif self.editing is None:
                    self.focus = self.main_focus[(self.main_focus.index(self.focus) + ARROWS[value]) % len(self.main_focus)]
                else:
                    step = ARROWS[value] * (10 if value in (1073741906, 1073741905) else 1)
                    self.key_focus = (self.key_focus + step) % len(self.keys)
            elif value in (13, 1073741912):
                self.choose(self.focus if self.editing is None else self.key_focus, canvas)
            elif value == 8 and self.editing is not None:
                field = settings.FIELDS[self.editing]
                self.values[field] = self.values[field][:-1]

    @property
    def controls_disabled(self):
        return False

    def draw(self, canvas):
        if self.infrared is not None:
            self.infrared.draw(canvas)
            return
        canvas.clear()
        canvas.text('Magic Sirimote', 64, 42, 40)
        canvas.text('Remote settings and button assignments', 66, 94, 23, (114, 191, 227))
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
            canvas.text('Back closes the keyboard. Choose ' + self.save_label + ' on the previous screen.', 66, 665, 20, (155, 170, 190))
        else:
            disabled = self.controls_disabled
            fill = lambda selected: (27, 34, 44) if disabled else (30, 113, 156) if selected else (36, 48, 65)
            ink = (105, 115, 130) if disabled else (226, 234, 243)
            shift = 0 if self.show_device_fields else -94
            for index, field in enumerate(settings.EDITABLE_FIELDS if self.show_device_fields else ()):
                y = 150 + index * 76
                box = (64, y, 1152, 62)
                canvas.rectangle(box, fill(self.focus == index))
                canvas.text(settings.LABELS[index], 82, y + 19, 22, ink, max_width=340)
                canvas.text(self.values[field] or 'Select to enter', 448, y + 17, 25, ink, max_width=742)
                if not disabled: self.boxes.append((index, box))
            box = (64, 244 + shift, 1152, 54)
            canvas.rectangle(box, fill(self.focus == 3))
            canvas.text('Gyro cursor: ' + ('On' if self.values['gyroEnabled'] else 'Off') + '  (OK to toggle)', 82, 258 + shift, 25, ink)
            if not disabled: self.boxes.append((3, box))
            box = (64, 312 + shift, 742, 82)
            canvas.rectangle(box, fill(self.focus == 4))
            canvas.text('Cursor sensitivity: ' + str(self.values['gyroSensitivity']) + ' / 5', 82, 322 + shift, 23, ink)
            canvas.rectangle((100, 372 + shift, 640, 3), ink)
            for step in range(1, 6):
                x = 100 + (step - 1) * 160
                canvas.rectangle((x - 7, 365 + shift, 14, 17), ink)
            x = 100 + (self.values['gyroSensitivity'] - 1) * 160
            canvas.rectangle((x - 11, 361 + shift, 22, 25), (105, 115, 130) if disabled else (114, 191, 227))
            if not disabled: self.boxes.append((4, box))
            box = (826, 312 + shift, 390, 82)
            canvas.rectangle(box, fill(self.focus == 8))
            canvas.text('Reset cursor orientation', 842, 337 + shift, 23, ink, max_width=358)
            if not disabled: self.boxes.append((8, box))
            for index, title, box in ((6, 'Button Assignments', (64, 418 + shift, 1152, 61)),
                                      (5, self.save_label, (454, 500 + shift, 372, 61)),
                                      (7, 'Close', (844, 500 + shift, 372, 61))):
                canvas.rectangle(box, fill(self.focus == index))
                canvas.text(title, box[0] + 25, box[1] + 17, 25, ink, max_width=322)
                if not disabled: self.boxes.append((index, box))
            if self.show_reset:
                box = (64, 500 + shift, 372, 61)
                canvas.rectangle(box, fill(self.focus == 9))
                canvas.text('Reset app', box[0]+25, box[1]+17, 25, ink, max_width=322)
                if not disabled: self.boxes.append((9, box))
            if self.message:
                canvas.text(self.message, 66, 590 + shift, 22, max_width=1148)
            if self.button_drafts and not disabled:
                canvas.text(str(len(self.button_drafts)) + ' button changes pending. Choose ' + self.save_label + ' to apply.', 66, 628 + shift, 21, (114, 191, 227))
            self.draw_footer(canvas)
        canvas.present()

    def draw_footer(self, canvas):
        # Compose the entire frame before presenting it. SDL does not promise
        # that any backbuffer content survives a presentation.
        canvas.text('Use the integrated app to save button assignments; input startup is separate.', 66, 630, 21, (155, 170, 190))
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
