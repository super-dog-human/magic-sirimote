"""A1513 system-button decoder; no device or network operations.

Button-bit reference: https://github.com/a-funk/open-appleremote/blob/main/docs/PROTOCOL.md
The cited capture is A1962; this project separately verified the mapping on A1513/G3.
Callers must supply an independently verified, bounded semantic key emitter.
The integrated receiver supplies saved press/hold mappings. Legacy defaults
map MENU and microphone to Back; voice is not enabled.
"""
import time
import math
CONFIGURED = None

def configure_assignments(bindings):
 global CONFIGURED
 CONFIGURED = dict(bindings)

def configured_mappings(default):
 if CONFIGURED is None:return default, None
 # Unknown slots leave the remote's stored IR alone and emit no TV action.
 normal={key:None for key in (1,2,4,8,16,32)}
 holds={key:None for key in normal}
 for slot,action in CONFIGURED.items():
  button,delay=(int(part,16) for part in slot.split(':'))
  if button not in normal:continue
  target=normal if delay==0 else holds
  target[button]=None if action=='none' or action.startswith('ir:') else action
 return normal,holds

MASK_TO_ACTION={0x01:'home',0x08:'playpause',0x20:'back',0x10:'back'}

def observed_mask(report):
 if type(report) not in (bytes,bytearray) or not report or report[0]!=0xfc:return None
 if len(report)<3:return None
 kind=report[1]
 valid=((kind==0 and len(report)==3) or (kind==1 and len(report)==14) or
        (kind==2 and len(report)==21) or (kind in (4,5,6) and len(report)==21) or
        (kind==0x10 and len(report) in (3,21)))
 return report[2] if valid else None

class SystemButtons:
 def __init__(self,emit,*,max_actions=128,mapping=None,holds=None,clock=time.monotonic):
  if not callable(emit) or type(max_actions) is not int or not 1<=max_actions<=1024:raise ValueError('invalid output')
  self.mapping=dict(MASK_TO_ACTION if mapping is None else mapping)
  self.holds=dict(holds or {});self.clock=clock;self.pressed_at=None
  self.emit=emit;self.max_actions=max_actions;self.generation=None;self.armed=False;self.pending=None;self.actions=0;self.failed=False
 def bind(self,generation):
  if type(generation) is not int or generation<=0 or self.generation is not None or self.failed:raise ValueError('invalid generation')
  self.generation=generation;self.armed=False;self.pending=None
 def feed(self,generation,report):
  if self.failed or generation!=self.generation or self.generation is None:return False
  mask=observed_mask(report)
  if mask is None:return False
  if mask!=0:
   # Only a single uninterrupted press after a neutral report is eligible.
   if self.armed and mask in self.mapping:
    self.pending=mask;self.armed=False;self.pressed_at=self.clock()
   elif mask!=self.pending:
    self.pending=None;self.armed=False
   return False
  pending=self.pending
  self.pending=None;self.armed=True
  if pending is None:return False
  elapsed=self.clock()-self.pressed_at
  if not math.isfinite(elapsed) or elapsed<0:return False
  action=self.holds.get(pending,self.mapping[pending]) if elapsed>=0.716 else self.mapping[pending]
  if action is None:return False
  if self.actions>=self.max_actions:self.failed=True;raise RuntimeError('action budget exhausted')
  try:sent=self.emit(action)
  except BaseException:self.failed=True;raise
  if sent is False:return False
  self.actions+=1;return True
 def unbind(self,generation):
  if generation!=self.generation or self.generation is None:return False
  self.generation=None;self.armed=False;self.pending=None;return True
