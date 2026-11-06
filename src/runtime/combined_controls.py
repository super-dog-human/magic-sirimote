"""Compose pointer, surface and button input, including queued wake actions."""
from system_buttons import SystemButtons,observed_mask,configured_mappings
from queued_wake_button import QueuedWakeButton,QueuedWakeSurface
import time

class CombinedControls:
 def __init__(self,rolling,emit,*,max_system_actions=128,screen_control=None,emit_ready=None):
  if not callable(emit) or not all(callable(getattr(rolling,n,None)) for n in ('start','feed_raw','tick','stop','_live')):raise ValueError('invalid receiver')
  if screen_control is not None and not all(callable(getattr(screen_control,n,None)) for n in ('toggle','blocked')):raise ValueError('invalid screen control')
  if emit_ready is not None and not callable(emit_ready):raise ValueError('invalid readiness check')
  self.emit_ready=emit_ready
  self.screen=screen_control
  self.rolling=rolling;self.emit=emit;self.max_system_actions=max_system_actions;self.buttons=None;self.button_generation=None;self.closed=False;self.system_actions=0;self.wake_button=None;self.wake_surface=None
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
  if self.wake_button is None:
   from touch_surface import current_product
   self.wake_button=QueuedWakeButton(enabled=current_product()==0x0266,
       mapping=mapping,holds=holds,clock=getattr(self.rolling,'clock',time.monotonic))
   self.wake_surface=QueuedWakeSurface(enabled=current_product()==0x0266,
       clock=getattr(self.rolling,'clock',time.monotonic))
  self.buttons=SystemButtons(self._emit,max_actions=self.max_system_actions,mapping=mapping,holds=holds);self.buttons.bind(generation);self.button_generation=generation
 def _flush_wake_button(self):
  if self.wake_button is None or not self.wake_button.ready():return
  if self.closed or self.rolling.closed or self.rolling._live() is not True:
   self.wake_button.cancel();return
  screen_toggle=self.screen is not None and self.wake_button.action=='screen-toggle'
  if screen_toggle:
   # Screen restoration must pass the screen-off input gate. Keep pointer
   # output paused; the screen worker queries current power before toggling.
   if getattr(self.screen,'initializing',lambda:False)():return
  else:
   if self.screen is not None and self.screen.blocked():
    if not getattr(self.screen,'initializing',lambda:False)():self.wake_button.cancel()
    return
   # The queued press has a real all-buttons-released report. It is safe to
   # resume an initially paused output before delivering that completed action.
   if self.rolling.paused:self.rolling.resume_output();self._sync()
   if self.emit_ready is not None and self.emit_ready(self.wake_button.action) is not True:
    return
  action=self.wake_button.take()
  if action is not None:
   self._emit(action)
 def _flush_wake_surface(self):
  if self.wake_surface is None or not self.wake_surface.pending():return
  if self.closed or self.rolling.closed or self.rolling._live() is not True:
   self.wake_surface.cancel();return
  if self.screen is not None and self.screen.blocked():
   if not getattr(self.screen,'initializing',lambda:False)():self.wake_surface.cancel()
   return
  # Never guess pointer versus focused-item click during the initial query.
  if getattr(self.rolling.outputs,'cursor_visible',None) is None:return
  if self.rolling.paused:self.rolling.resume_output();self._sync()
  release=self.wake_surface.take_press()
  started=self.rolling.begin_wake_press()
  if started and release is not None:self.rolling.feed_raw(1,release)
 def start(self):
  if self.closed or self.buttons is not None:raise RuntimeError('already started')
  self.rolling.start();self._sync()
 def feed_raw(self,generation,report):
  if self.closed or self.buttons is None or generation!=1:return False
  try:
   self.wake_button.feed(report);self.wake_surface.feed(report)
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
   self._flush_wake_button();self._flush_wake_surface()
   return result
  except BaseException:
   self.stop('combined-output-error');raise
 def tick(self):
  if self.closed:return False
  try:
   if self.screen is not None and self.screen.blocked():self.rolling.pause_output()
   ok=self.rolling.tick()
   if not ok:self.stop('receiver-ended');return False
   self._sync();self._flush_wake_button();self._flush_wake_surface();return True
  except BaseException:
   self.stop('combined-output-error');raise
 def stop(self,reason='requested'):
  if self.closed:return
  self.closed=True
  if self.wake_button is not None:self.wake_button.cancel()
  if self.wake_surface is not None:self.wake_surface.cancel()
  try:
   if self.buttons is not None:self.buttons.unbind(self.button_generation)
  finally:self.rolling.stop(reason)
 def summary(self):
  return {**self.rolling.summary(),'systemActions':self.system_actions}
