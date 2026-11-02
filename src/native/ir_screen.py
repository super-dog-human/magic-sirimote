"""TV-remote friendly IR editor. Only an explicit confirmation sends a change."""
import queue
import threading
from ir_programmer import BUTTONS, execute, packet
import tv_assignments

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
    def __init__(self, state, submit=execute, submit_tv=tv_assignments.execute):
        self.state, self.submit = state, submit
        self.submit_tv = submit_tv
        self.route = 'ir'
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
        self.message = 'Choose a button, a press type, and an IR or TV action.'
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
        if status == 'configured-only':
            self.message = 'TV assignment saved locally; not active in this preview.' if result.get('operation') == 'set' else 'Saved TV assignment deleted.'
            self.detail = 'Input runtime integration is still required. No infrared setting was changed.'
        elif status == 'tv-save-failed':
            self.message = 'Could not confirm the saved TV assignment.'
            self.detail = 'No infrared request was sent. Check the app storage before trying again.'
        elif status == 'submitted':
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
            submit = self.submit_tv if self.route == 'tv' else self.submit
            self.message = 'Saving the TV assignment. Please wait.' if self.route == 'tv' else 'Checking the remote and sending one request. Please wait.'
            self.detail = 'Use the original LG remote for this screen.'
            def work():
                try:
                    value = submit(*args)
                except Exception:
                    value = {'status': 'tv-save-failed' if self.route == 'tv' else 'uncertain'}
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
                self.route = 'ir'
                self.message = 'Choose Set to review this infrared assignment.'
                self.detail = 'Current remote settings cannot be read; this is your selected command.'
                self.code = PRESETS[index][1]
                self.picking = False; self.focus = 2
            elif index == len(PRESETS):
                self.route = 'tv'
                self.picking = False; self.focus = 2
                self.message = 'Screen off / restore keeps audio playing; press again to restore.'
                self.detail = 'TV-side assignment: saving is supported; runtime integration is pending.'
            elif index == len(PRESETS)+1:
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
                self.route = 'ir'
                self.message = 'Choose Set to review this infrared assignment.'
                self.detail = 'Current remote settings cannot be read; this is your selected command.'
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
                if self.route == 'tv':
                    tv_assignments.slot(BUTTONS[self.button][1], self.delay)
                else:
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
                self.editing = False; self.picking = True; self.focus = len(PRESETS)+1
            elif self.picking:
                self.picking = False; self.focus = 2
            else:
                self.done = True
        elif kind == 'key' and value in ARROWS:
            if self.selecting:
                count = len(BUTTONS if self.selecting == 'button' else PRESS_TYPES) + 1
            else:
                count = 2 if self.review else len(PRESETS)+3 if self.picking else 18 if self.editing else 6
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
        canvas.text('Button assignments', 64, 42, 38)
        canvas.text('LG television codes / Siri Remote A1513', 66, 96, 23, (114, 191, 227))
        self.boxes = []
        def button(index, title, bounds):
            canvas.rectangle(bounds, (30, 113, 156) if self.focus == index else (36, 48, 65))
            canvas.text(title, bounds[0]+18, bounds[1]+14, 25, max_width=bounds[2]-36)
            self.boxes.append((index, bounds))
        tv = self.route == 'tv'
        action = 'Screen off / restore (TV)' if tv else action_label(self.code)
        set_label, delete_label = ('Save', 'Delete') if tv else ('Set', 'Delete')
        press = 'Normal press (release)' if tv and self.delay == 0 else next(label for label, value in PRESS_TYPES if value == self.delay)
        if self.busy:
            canvas.text('Working...', 66, 240, 32)
        elif self.review:
            canvas.text(BUTTONS[self.button][0] + ' / ' + press, 66, 175, 28)
            canvas.text(('Save ' if tv else 'Set ') + action if self.review == 'set' else 'Delete this ' + ('TV' if tv else 'infrared') + ' assignment?', 66, 235, 30)
            canvas.text('Saves this button and press type locally. Not active in this preview.' if tv else 'This changes one button and press type in the remote.', 66, 305, 24)
            canvas.text('Input runtime integration is pending. Infrared settings are unchanged.' if tv else 'Deleting does not restore an earlier assignment. Bluetooth mapping is unchanged.', 66, 347, 22)
            button(0, 'Cancel', (64, 420, 552, 64))
            button(1, set_label if self.review == 'set' else delete_label, (640, 420, 552, 64))
        elif self.selecting == 'button':
            canvas.text('Choose a physical button', 66, 146, 27)
            for i, title in enumerate([name for name, _ in BUTTONS] + ['Cancel']):
                row, column = divmod(i, 2)
                button(i, title, (64+column*580, 200+row*77, 564, 64))
            canvas.text('All seven physical buttons, including the surface click. Swipes are gestures.', 66, 530, 21)
        elif self.selecting == 'press':
            canvas.text('Choose a press type', 66, 146, 27)
            for i, title in enumerate([('Normal press (release)' if tv and value == 0 else label) for label, value in PRESS_TYPES] + ['Cancel']):
                button(i, title, (64, 200+i*77, 1152, 64))
            canvas.text('TV choices are saved for the future input runtime; not active in this preview.' if tv else 'Normal press sends immediately, even when you keep holding the button.', 66, 468, 22)
            canvas.text('Choose Action first to see whether it uses IR or TV-side processing.' if tv else 'If both IR entries are set, a long press can send both commands.', 66, 510, 22)
        elif self.picking:
            canvas.text('Choose an action', 66, 146, 27)
            options = [name + ' (IR) - ' + code for name, code in PRESETS] + ['Screen off / restore (TV)', 'Enter code directly (IR)', 'Cancel']
            for i, title in enumerate(options):
                row, column = divmod(i, 2)
                button(i, title, (64+column*580, 195+row*57, 564, 49))
        elif self.editing:
            canvas.text('LG code (IR, hex): ' + (self.draft or '__'), 66, 162, 32)
            for i, key in enumerate(list('0123456789ABCDEF') + ['Erase', 'Done']):
                row, column = divmod(i, 6)
                button(i, key, (64+column*190, 240+row*80, 174, 64))
        else:
            button(0, 'Button: ' + BUTTONS[self.button][0] + '  (OK to change)', (64, 150, 1152, 65))
            button(1, 'Press: ' + press + '  (OK to change)', (64, 231, 1152, 65))
            button(2, 'Action: ' + action, (64, 312, 1152, 65))
            for index, title in enumerate((set_label, delete_label, 'Back'), 3):
                button(index, title, (64+(index-3)*390, 411, 372, 64))
            canvas.text('TV assignments are saved locally; input runtime integration is still pending.' if tv else 'Choose an action, or enter a two-digit LG infrared code directly.', 66, 503, 21)
        canvas.text(self.message, 66, 570, 22, max_width=1148)
        canvas.text(self.detail, 66, 612, 20, (155, 170, 190), max_width=1148)
        canvas.text('TV: local configuration only. IR: explicit programming of the remote.', 66, 663, 20, (155, 170, 190))
        canvas.present()
