"""Experimental composition with the existing rolling receiver.

Not wired into a TV runner. Callers supply an already-created rolling receiver
and an independently validated semantic system-key sink.
"""
from system_buttons import SystemButtons,observed_mask,configured_mappings

class CombinedControls:
 def __init__(self,rolling,emit,*,max_system_actions=128,screen_control=None):
  if not callable(emit) or not all(callable(getattr(rolling,n,None)) for n in ('start','feed_raw','tick','stop','_live')):raise ValueError('invalid receiver')
  if screen_control is not None and not all(callable(getattr(screen_control,n,None)) for n in ('toggle','blocked')):raise ValueError('invalid screen control')
  self.screen=screen_control
  self.rolling=rolling;self.emit=emit;self.max_system_actions=max_system_actions;self.buttons=None;self.button_generation=None;self.closed=False;self.system_actions=0
 def _emit(self,action):
  if self.closed or self.rolling.closed or self.rolling._live() is not True:raise RuntimeError('receiver continuity lost')
  if self.screen is not None:
   if action=='screen-toggle':
    self.rolling.pause_output()
    if self.screen.toggle() is False:return False
    self.system_actions+=1;return True
   if self.screen.blocked() or self.rolling.paused:return False
  if self.emit(action) is False:return False
  self.system_actions+=1;return True
 def _sync(self,force=False):
  generation=self.rolling.generation
  if self.button_generation==generation and not force:return
  if self.buttons is not None:self.buttons.unbind(self.button_generation)
  from system_buttons import MASK_TO_ACTION
  mapping,holds=configured_mappings({0x01:"home",0x08:"playpause",0x20:"back",0x10:"screen-toggle"} if self.screen is not None else MASK_TO_ACTION)
  self.buttons=SystemButtons(self._emit,max_actions=self.max_system_actions,mapping=mapping,holds=holds);self.buttons.bind(generation);self.button_generation=generation
 def start(self):
  if self.closed or self.buttons is not None:raise RuntimeError('already started')
  self.rolling.start();self._sync()
 def feed_raw(self,generation,report):
  if self.closed or self.buttons is None or generation!=1:return False
  try:
   if self.screen is not None:
    self._sync()
    self.buttons.feed(self.button_generation,report)
    if self.buttons.actions>=self.max_system_actions and observed_mask(report)==0:
     self._sync(force=True)
     self.buttons.feed(self.button_generation,report)
    if self.screen.blocked():self.rolling.pause_output()
    elif self.rolling.paused and observed_mask(report)==0:self.rolling.resume_output()
   result=self.rolling.feed_raw(generation,report)
   if self.rolling.closed:self.stop('receiver-ended');return False
   self._sync()
   # Only a verified all-buttons-released report permits a fresh budget.
   # This avoids terminating daily operation after a finite number of keys.
   if self.screen is None:self.buttons.feed(self.button_generation,report)
   if self.buttons.actions>=self.max_system_actions and observed_mask(report)==0:
    self._sync(force=True)
    self.buttons.feed(self.button_generation,report)
   return result
  except BaseException:
   self.stop('combined-output-error');raise
 def tick(self):
  if self.closed:return False
  try:
   if self.screen is not None and self.screen.blocked():self.rolling.pause_output()
   ok=self.rolling.tick()
   if not ok:self.stop('receiver-ended');return False
   self._sync();return True
  except BaseException:
   self.stop('combined-output-error');raise
 def stop(self,reason='requested'):
  if self.closed:return
  self.closed=True
  try:
   if self.buttons is not None:self.buttons.unbind(self.button_generation)
  finally:self.rolling.stop(reason)
 def summary(self):
  return {**self.rolling.summary(),'systemActions':self.system_actions}
