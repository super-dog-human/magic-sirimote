"""Six-button editor: selections stay in memory until the main Save action."""
import tv_assignments as assignments

ARROWS = {1073741906: -1, 1073741905: 1, 1073741904: -1, 1073741903: 1}
BACK = (27, 461, 1073742094)
BUTTONS = assignments.ROWS
PRESETS = (('Power on/off', '08'), ('Back', '28'), ('Home', '7C'),
           ('Settings', '43'), ('Volume +', '02'), ('Volume -', '03'),
           ('Mute', '09'), ('Play', 'B0'), ('Pause', 'BA'))
TV_ACTIONS = (('Do nothing', 'none'), ('Back', 'back'),
              ('Play / Pause', 'playpause'),
              ('Screen off / restore', 'screen-toggle'))
CHOICES = TV_ACTIONS + tuple((name + ' (IR)', 'ir:' + code) for name, code in PRESETS)
CUSTOM = len(CHOICES)


def label(action):
    if action == 'home': return 'Home (legacy TV)'
    return next((name for name, value in CHOICES if value == action),
                'Code ' + action[3:] + ' (IR)' if action.startswith('ir:') else action)



class InfraredScreen:
    def __init__(self, state, drafts=None):
        self.state = state
        self.drafts = {} if drafts is None else drafts
        self.button = self.delay = self.focus = self.cell = 0
        self.code = ''
        self.editing = self.picking = self.busy = self.done = False
        self.draft = ''
        self.boxes = []
        self.message = 'Changes stay pending until Save on the first screen.'
        self.detail = 'Existing IR entries are unknown until changed here. Browsing does not change them.'
        self.refresh_saved_tv()

    def refresh_saved_tv(self):
        try:
            value = assignments.load(self.state)
            self.tv_bindings = value['bindings'] if value['schema'] == 2 else {}
        except (OSError, ValueError):
            self.tv_bindings = None

    def cell_label(self, button, delay):
        key = assignments.slot(button, delay)
        if key in self.drafts: return label(self.drafts[key]) + ' (edited)'
        if self.tv_bindings is None: return 'Unavailable'
        if key in self.tv_bindings: return label(self.tv_bindings[key])
        default = assignments.DEFAULTS.get(key)
        if delay == 2 and button != 1:
            normal = assignments.slot(button, 0)
            default = self.drafts.get(normal, self.tv_bindings.get(normal, assignments.DEFAULTS.get(normal)))
            if default == 'none' or default and default.startswith('ir:'):
                default = None
        return label(default) + ' *' if default else 'IR unknown *'

    def tick(self):
        return False

    def choose(self, index):
        if self.busy: return
        if self.editing:
            if index == 16: self.draft = self.draft[:-1]
            elif index == 17:
                if len(self.draft) != 2:
                    self.message = 'Enter exactly two hexadecimal digits.'
                    return
                self.code = 'ir:' + self.draft; self.editing = False
                self.stage_choice()
            elif 0 <= index < 16 and len(self.draft) < 2:
                self.draft += '0123456789ABCDEF'[index]
            return
        if self.picking:
            if 0 <= index < CUSTOM:
                self.code = CHOICES[index][1]; self.picking = False
                self.stage_choice()
            elif index == CUSTOM:
                self.picking = False; self.editing = True; self.draft = ''; self.focus = 0
            else:
                self.picking = False; self.focus = self.cell
            return
        if 0 <= index < 12:
            self.cell = index; self.button, column = divmod(index, 2)
            self.delay = 2 if column else 0
            self.picking = True; self.focus = 0
        else: self.done = True

    def stage_choice(self):
        key = assignments.slot(BUTTONS[self.button][1], self.delay)
        saved = (self.tv_bindings or {}).get(key)
        if self.code == saved:
            self.drafts.pop(key, None)
        else:
            self.drafts[key] = self.code
        self.picking = self.editing = False
        self.focus = self.cell
        self.message = 'Change kept in this session. Back returns to the first screen to save.'

    def handle(self, event):
        if self.busy: return
        kind, value = event
        if kind == 'close' or kind == 'key' and value in BACK:
            self.editing = self.picking = False; self.done = True
        elif kind == 'key' and value in ARROWS:
            if not (self.picking or self.editing):
                if value == 1073741905:
                    self.focus = 0 if self.focus == 12 else min(12, self.focus + 2)
                elif value == 1073741906:
                    self.focus = 10 if self.focus == 12 else 12 if self.focus < 2 else self.focus - 2
                elif self.focus < 12:
                    self.focus = (self.focus // 2) * 2 + (1 if value == 1073741903 else 0)
                return
            count = CUSTOM+2 if self.picking else 18 if self.editing else 13
            step = ARROWS[value]
            if value in (1073741906,1073741905):
                step *= 3 if self.picking else 6 if self.editing else 2
            self.focus = (self.focus + step) % count
        elif kind == 'key' and value in (13,1073741912): self.choose(self.focus)
        elif kind == 'click':
            for index, (x,y,w,h) in self.boxes:
                if x <= value[0] < x+w and y <= value[1] < y+h:
                    self.choose(index); break
        elif kind == 'text' and self.editing:
            self.draft = (self.draft + ''.join(c for c in value.upper() if c in '0123456789ABCDEF'))[:2]
        elif kind == 'key' and value == 8 and self.editing: self.draft = self.draft[:-1]

    def draw(self, canvas):
        canvas.clear(); canvas.text('Button assignments',64,42,38)
        canvas.text('Choose actions, then save together on the first screen',66,96,23,(114,191,227))
        self.boxes=[]
        def button(index,title,bounds,size=23):
            canvas.rectangle(bounds,(30,113,156) if self.focus==index else (36,48,65))
            canvas.text(title,bounds[0]+16,bounds[1]+14,size,max_width=bounds[2]-32)
            self.boxes.append((index,bounds))
        if self.editing:
            canvas.text('LG code (IR, hex): '+(self.draft or '__'),66,162,32)
            for i,key in enumerate(list('0123456789ABCDEF')+['Erase','Done']):
                row,col=divmod(i,6);button(i,key,(64+col*190,240+row*80,174,64))
        elif self.picking:
            canvas.text(BUTTONS[self.button][0]+(' / Hold' if self.delay else ' / Press'),66,144,25)
            for i,title in enumerate([name for name,_ in CHOICES]+['Custom code (IR)','Cancel']):
                row,col=divmod(i,3);button(i,title,(64+col*388,190+row*58,372,50),21)
        else:
            canvas.text('Button',66,150,23);canvas.text('Press',330,150,23);canvas.text('Hold (~0.7 s)',770,150,23)
            for row,(name,mask) in enumerate(BUTTONS):
                y=188+row*55;canvas.text(name,66,y+14,24,max_width=230)
                for col,delay in enumerate((0,2)):
                    button(row*2+col,self.cell_label(mask,delay),(312+col*448,y,432,49),22)
            button(12,'Back',(64,530,220,51))
        canvas.text(self.message,66,594,21,max_width=1148)
        canvas.text(self.detail,66,628,19,(155,170,190),max_width=1148)
        canvas.text('IR Hold requires IR Press; a hold can send both. TV actions run on release.',66,669,18,(155,170,190),max_width=1148)
        canvas.present()
