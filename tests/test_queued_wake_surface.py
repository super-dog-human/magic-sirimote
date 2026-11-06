import unittest
from unittest.mock import patch
from combined_controls import CombinedControls
from rolling_receiver import RollingReceiver
from output_bridge import VerifiedOutputs,KEY_ENTER,BTN_LEFT
from fixture_devices import MemoryDevices,touch

class Screen:
 def __init__(self):self.state=None
 def blocked(self):return self.state!='active'
 def initializing(self):return self.state is None
 def toggle(self):return True

class Tests(unittest.TestCase):
 def make(self,product=0x0266):
  self.now=0.;self.live=True;self.screen=Screen();self.dev=MemoryDevices()
  self.out=VerifiedOutputs(1,2,ioctl_fn=self.dev.ioctl,write_fn=self.dev.write,sleep_fn=lambda _:None)
  self.out.cursor_visible=None
  self.rolling=RollingReceiver(self.out,continuity=lambda:self.live,mode_verified=lambda:True,clock=lambda:self.now)
  with patch('touch_surface.current_product',return_value=product),patch('system_buttons.CONFIGURED',None):
   self.c=CombinedControls(self.rolling,lambda _:True,screen_control=self.screen);self.c.start()
  self.c.tick()
 def feed(self,s):
  self.now+=.01
  self.c.feed_raw(1,bytes.fromhex(s) if isinstance(s,str) else s);self.c.tick()
 def frames(self):
  return [(fd,code,value) for fd,events in self.dev.writes for _,_,kind,code,value in events if kind==1]
 def ready(self,visible=False):
  self.screen.state='active';self.out.cursor_visible=visible;self.c.tick()
 def test_short_wake_press_waits_for_screen_and_visibility_then_selects_once(self):
  self.make();self.feed('fce08000');self.feed('fc0000')
  self.assertEqual(self.frames(),[])
  self.screen.state='active';self.c.tick();self.assertEqual(self.frames(),[])
  self.ready(False);self.assertEqual(self.frames(),[(1,KEY_ENTER,1),(1,KEY_ENTER,0)])
  self.feed('fc0000');self.c.tick();self.assertEqual(len(self.frames()),2)
 def test_held_wake_starts_down_then_real_release_uses_same_destination(self):
  for visible,fd,code in [(False,1,KEY_ENTER),(True,2,BTN_LEFT)]:
   self.make();self.ready(visible);self.feed('fce08000')
   self.assertEqual(self.frames(),[(fd,code,1)])
   self.out.cursor_visible=not visible
   self.feed('fc0080');self.assertEqual(len(self.frames()),1)
   self.feed('fc0000');self.assertEqual(self.frames(),[(fd,code,1),(fd,code,0)])
 def test_release_before_pointer_query_uses_pointer_and_does_not_change_position(self):
  self.make();self.feed('fce080');self.feed('fc0000');self.ready(True)
  self.assertEqual(self.frames(),[(2,BTN_LEFT,1),(2,BTN_LEFT,0)])
  self.assertFalse(any(kind==2 for _,events in self.dev.writes for _,_,kind,_,_ in events))
 def test_normal_press_after_wake_still_works(self):
  self.make();self.feed('fce08000');self.feed('fc0000');self.ready(False)
  self.feed('fc0080');self.feed('fc0000')
  self.assertEqual(self.frames(),[(1,KEY_ENTER,1),(1,KEY_ENTER,0)]*2)
 def test_no_guess_from_ordinary_unknown_or_chord_reports(self):
  for first in ('fc0080','fc0000','fce04000','fce08100','fce0800000'):
   self.make();self.feed(first);self.feed('fce08000');self.feed('fc0000');self.ready(False)
   self.assertEqual(self.frames(),[])
 def test_other_models_do_not_replay_wake_surface(self):
  for product in (None,0x026d):
   self.make(product);self.feed('fce08000');self.feed('fc0000');self.ready(False)
   self.assertEqual(self.frames(),[])
 def test_pending_press_cancelled_on_expiry_off_loss_stop_and_another_button(self):
  for why in ('expiry','off','loss','stop','conflict','newpress'):
   self.make();self.feed('fce08000');self.feed('fc0000')
   if why=='expiry':self.now=3.1
   elif why=='off':self.screen.state='off'
   elif why=='loss':self.live=False
   elif why=='stop':self.c.stop()
   elif why=='conflict':self.feed('fc0008')
   else:self.feed('fc0080')
   self.c.tick();self.ready(False);self.assertEqual(self.frames(),[])
 def test_disconnect_or_screen_off_releases_started_click_once(self):
  for why in ('loss','off','stop'):
   self.make();self.ready(False);self.feed('fce08000')
   if why=='loss':self.live=False
   elif why=='off':self.screen.state='off'
   else:self.c.stop()
   self.c.tick();self.c.tick()
   self.assertEqual(self.frames(),[(1,KEY_ENTER,1),(1,KEY_ENTER,0)])
 def test_short_write_is_terminal_and_never_retried(self):
  self.make();self.ready(False);self.dev.short=True
  with self.assertRaises(RuntimeError):self.feed('fce08000')
  self.assertTrue(self.c.closed);self.dev.short=False;self.c.tick()
  self.assertEqual(self.frames(),[])
 def test_held_contact_cannot_also_produce_swipe(self):
  self.make();self.ready(False);self.feed('fce08000')
  self.feed(touch(200,800,3,1,buttons=128));self.feed(touch(1200,800,4,2,buttons=128))
  self.feed(touch(1200,800,7,3,buttons=0));self.c.tick()
  self.assertEqual(self.frames(),[(1,KEY_ENTER,1),(1,KEY_ENTER,0)])
 def test_recognizer_cannot_begin_second_wake_press_or_wrong_generation(self):
  self.make();self.ready(False);p=self.rolling.receiver.router.press
  self.assertFalse(p.begin_wake_press(99))
  self.feed('fce08000');self.feed('fc0000')
  p=self.rolling.receiver.router.press
  self.assertFalse(p.begin_wake_press(self.rolling.generation))
  self.assertEqual(len(self.frames()),2)
