"""TV-remote friendly IR editor. Only an explicit confirmation sends a change."""
import queue
import threading
from ir_programmer import BUTTONS, execute, packet

ARROWS = {1073741906: -1, 1073741905: 1, 1073741904: -1, 1073741903: 1}
BACK = (27, 461, 1073742094)
PRESS_TYPES = (('Normal press (immediate)', 0), ('Long press (about 0.7 seconds)', 2))
# LG command bytes, not factory defaults or a readback from the remote.
PRESETS = (('Power on/off', '08'), ('Back', '28'), ('Home', '7C'),
           ('Settings', '43'), ('Volume +', '02'), ('Volume -', '03'),
           ('Mute', '09'), ('Play', 'B0'), ('Pause', 'BA'))


def action_label(code):
    name = next((name for name, value in PRESETS if value == code), 'Custom code')
    return name + ' (IR) - ' + code if code else 'Select an action or enter a code'


class InfraredScreen:
    def __init__(self, state, submit=execute):
        self.state, self.submit = state, submit
        self.button = self.delay = self.focus = 0
        self.code = ''
        self.editing = False
        self.picking = False
        self.selecting = None
        self.draft = ''
        self.review = None
        self.busy = self.done = False
        self.boxes = []
        self.results = queue.Queue()
        self.message = 'Choose a button, a press type, and an IR action or custom code.'
        self.detail = 'Current remote settings cannot be read. No assignments are loaded automatically.'

    def tick(self):
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            return False
        self.busy = False
        self.review = None
        self.focus = 5
        status = result.get('status')
        if status == 'submitted':
            self.message = 'Request sent. Test the selected button on your TV.'
            self.detail = 'The TV accepted the request; the saved remote setting has not been read back.'
        elif status == 'not-sent':
            self.message = 'No infrared assignment was sent.'
            self.detail = result.get('message', 'Check the remote connection and try again.')
        else:
            self.message = 'The result is unknown. The request was not repeated.'
            self.detail = 'Test the button before making another change. An operation record was saved if possible.'
        if result.get('clientReleased') is False:
            self.detail = 'Connection cleanup was not confirmed. Check Bluetooth before another change.'
        return True

    def choose(self, index):
        if self.busy:
            return
        if self.review is not None:
            if index != 1:
                self.review = None; self.focus = 5
                return
            action = self.review
            args = (self.state, action, BUTTONS[self.button][1], self.delay, self.code)
            self.busy = True
            self.message = 'Checking the remote and sending one request. Please wait.'
            self.detail = 'Use the original LG remote for this screen.'
            def work():
                try:
                    value = self.submit(*args)
                except Exception:
                    value = {'status': 'uncertain'}
                self.results.put(value)
            threading.Thread(target=work, name='infrared-configuration', daemon=False).start()
            return
        if self.selecting:
            options = BUTTONS if self.selecting == 'button' else PRESS_TYPES
            target = 0 if self.selecting == 'button' else 1
            if 0 <= index < len(options):
                if self.selecting == 'button':
                    self.button = index
                else:
                    self.delay = options[index][1]
            self.selecting = None; self.focus = target
            return
        if self.picking:
            if index < len(PRESETS):
                self.code = PRESETS[index][1]
                self.picking = False; self.focus = 2
            elif index == len(PRESETS):
                self.picking = False; self.editing = True
                self.draft = self.code; self.focus = 0
            else:
                self.picking = False; self.focus = 2
            return
        if self.editing:
            key = list('0123456789ABCDEF') + ['Erase', 'Done']
            if index == 16:
                self.draft = self.draft[:-1]
            elif index == 17:
                if len(self.draft) != 2:
                    self.message = 'Enter exactly two hexadecimal digits, then choose Done.'
                    return
                self.code = self.draft
                self.editing = False; self.focus = 2
            elif len(self.draft) < 2:
                self.draft += key[index]
            return
        if index == 0:
            self.selecting = 'button'; self.focus = self.button
        elif index == 1:
            self.selecting = 'press'
            self.focus = next(i for i, (_, value) in enumerate(PRESS_TYPES) if value == self.delay)
        elif index == 2:
            self.picking = True; self.focus = 0
        elif index in (3, 4):
            action = 'set' if index == 3 else 'delete'
            try:
                packet(action, BUTTONS[self.button][1], self.delay, self.code)
            except ValueError as error:
                self.message = str(error)
                return
            self.review = action; self.focus = 0
        else:
            self.done = True

    def handle(self, event):
        if self.busy:
            return  # Keep the process alive until the bounded operation finishes.
        kind, value = event
        if kind == 'close' or kind == 'key' and value in BACK:
            if self.review is not None:
                self.review = None; self.focus = 5
            elif self.selecting:
                self.focus = 0 if self.selecting == 'button' else 1
                self.selecting = None
            elif self.editing:
                self.editing = False; self.picking = True; self.focus = len(PRESETS)
            elif self.picking:
                self.picking = False; self.focus = 2
            else:
                self.done = True
        elif kind == 'key' and value in ARROWS:
            if self.selecting:
                count = len(BUTTONS if self.selecting == 'button' else PRESS_TYPES) + 1
            else:
                count = 2 if self.review else len(PRESETS)+2 if self.picking else 18 if self.editing else 6
            step = ARROWS[value]
            if (self.picking or self.selecting == 'button') and value in (1073741906, 1073741905):
                step *= 2
            self.focus = (self.focus + step) % count
        elif kind == 'key' and value in (13, 1073741912):
            self.choose(self.focus)
        elif kind == 'click':
            for index, (x, y, w, h) in self.boxes:
                if x <= value[0] < x+w and y <= value[1] < y+h:
                    self.choose(index); break
        elif kind == 'text' and self.editing:
            self.draft = (self.draft + ''.join(c for c in value.upper() if c in '0123456789ABCDEF'))[:2]
        elif kind == 'key' and value == 8 and self.editing:
            self.draft = self.draft[:-1]

    def draw(self, canvas):
        canvas.clear()
        canvas.text('Infrared assignments', 64, 42, 38)
        canvas.text('LG television codes / Siri Remote A1513', 66, 96, 23, (114, 191, 227))
        self.boxes = []
        def button(index, title, bounds):
            canvas.rectangle(bounds, (30, 113, 156) if self.focus == index else (36, 48, 65))
            canvas.text(title, bounds[0]+18, bounds[1]+14, 25, max_width=bounds[2]-36)
            self.boxes.append((index, bounds))
        press = next(label for label, value in PRESS_TYPES if value == self.delay)
        if self.busy:
            canvas.text('Working...', 66, 240, 32)
        elif self.review:
            canvas.text(BUTTONS[self.button][0] + ' / ' + press, 66, 175, 28)
            canvas.text(('Set ' + action_label(self.code)) if self.review == 'set' else 'Delete this infrared assignment?', 66, 235, 30)
            canvas.text('This changes one button and press type in the remote.', 66, 305, 24)
            canvas.text('Deleting does not restore an earlier assignment. Bluetooth mapping is unchanged.', 66, 347, 22)
            button(0, 'Cancel', (64, 420, 552, 64))
            button(1, 'Set (IR)' if self.review == 'set' else 'Delete (IR)', (640, 420, 552, 64))
        elif self.selecting == 'button':
            canvas.text('Choose a physical button (IR)', 66, 146, 27)
            for i, title in enumerate([name + ' (IR)' for name, _ in BUTTONS] + ['Cancel']):
                row, column = divmod(i, 2)
                button(i, title, (64+column*580, 200+row*77, 564, 64))
            canvas.text('All seven physical buttons, including the surface click. Swipes are gestures.', 66, 530, 21)
        elif self.selecting == 'press':
            canvas.text('Choose a press type (IR)', 66, 146, 27)
            for i, title in enumerate([label for label, _ in PRESS_TYPES] + ['Cancel']):
                button(i, title, (64, 200+i*77, 1152, 64))
            canvas.text('Normal press sends immediately, even when you keep holding the button.', 66, 468, 22)
            canvas.text('If both entries are set, a long press can send both commands.', 66, 510, 22)
        elif self.picking:
            canvas.text('Choose an action (IR)', 66, 146, 27)
            options = [name + ' (IR) - ' + code for name, code in PRESETS] + ['Enter code directly (IR)', 'Cancel']
            for i, title in enumerate(options):
                row, column = divmod(i, 2)
                button(i, title, (64+column*580, 195+row*57, 564, 49))
        elif self.editing:
            canvas.text('LG code (IR, hex): ' + (self.draft or '__'), 66, 162, 32)
            for i, key in enumerate(list('0123456789ABCDEF') + ['Erase', 'Done']):
                row, column = divmod(i, 6)
                button(i, key, (64+column*190, 240+row*80, 174, 64))
        else:
            button(0, 'Button (IR): ' + BUTTONS[self.button][0] + '  (OK to change)', (64, 150, 1152, 65))
            button(1, 'Press: ' + press + '  (OK to change)', (64, 231, 1152, 65))
            button(2, 'Action: ' + action_label(self.code), (64, 312, 1152, 65))
            for index, title in enumerate(('Set (IR)', 'Delete (IR)', 'Back'), 3):
                button(index, title, (64+(index-3)*390, 411, 372, 64))
            canvas.text('Choose a named IR action, or enter a two-digit LG code directly.', 66, 503, 21)
        canvas.text(self.message, 66, 570, 22, max_width=1148)
        canvas.text(self.detail, 66, 612, 20, (155, 170, 190), max_width=1148)
        canvas.text('Delete affects only infrared. Other press types and Bluetooth actions remain.', 66, 663, 20, (155, 170, 190))
        canvas.present()
