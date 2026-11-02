import unittest
from grouped_prefix_output import GroupedPrefixOutput
from output_bridge import VerifiedOutputs, EVENT, KEY_ENTER, BTN_LEFT, _frame
from fixture_devices import MemoryDevices
from test_swipe_click import touch

class Tests(unittest.TestCase):
 def make(self):
  self.now=0.;self.dev=MemoryDevices()
  self.out=VerifiedOutputs(1,2,ioctl_fn=self.dev.ioctl,write_fn=self.dev.write,sleep_fn=lambda _:None)
  self.r=GroupedPrefixOutput(self.out,clock=lambda:self.now,sensor_input_verified=True);self.r.bind(1);self.r.router.press.feed(1,b"\0\0")
 def keys(self):
  return [(fd,code,value) for fd,events in self.dev.writes for _,_,kind,code,value in events if kind==1]
 def press(self,down):self.r.router.press.feed(1,b'\0'+bytes((0x80 if down else 0,)));self.r.tick()
 def test_pointer_center_is_mouse_click(self):
  self.make();self.press(True);self.press(False)
  self.assertEqual(self.keys(),[(2,BTN_LEFT,1),(2,BTN_LEFT,0)]);self.assertTrue(self.out.verify_released())
 def test_actual_swipe_then_press_is_native_enter(self):
  self.make()
  for value in (touch(-1500,-200,state=3),touch(-1000,-200,state=4),touch(-1000,-200,state=7)):
   self.now+=.02;self.r.feed_raw(1,b'\xfc\x05'+value[1:]+b'\0'*7);self.r.tick()
  self.now+=.1;self.r.tick();self.press(True);self.press(False)
  self.assertEqual(self.r.router.navigation.mode,'navigation')
  self.assertEqual(self.keys(),[(1,106,1),(1,106,0),(1,KEY_ENTER,1),(1,KEY_ENTER,0)])
  self.assertTrue(self.out.verify_released())
 def test_focus_release_stays_on_original_device_after_mode_change(self):
  self.make();self.r.router.navigation.select_navigation(0.);self.press(True)
  self.r.router.navigation.mode='pointer';self.press(False)
  self.assertEqual(self.keys(),[(1,KEY_ENTER,1),(1,KEY_ENTER,0)])
 def test_pointer_release_stays_on_original_device_after_mode_change(self):
  self.make();self.press(True);self.r.router.navigation.select_navigation(0.);self.press(False)
  self.assertEqual(self.keys(),[(2,BTN_LEFT,1),(2,BTN_LEFT,0)])
 def test_stop_releases_held_focused_center(self):
  self.make();self.r.router.navigation.select_navigation(0.);self.press(True);self.r.stop()
  self.assertEqual(self.keys(),[(1,KEY_ENTER,1),(1,KEY_ENTER,0)]);self.assertTrue(self.out.verify_released())
 def test_partial_enter_down_attempts_release_and_fails_closed(self):
  self.make();original=self.out.write_fn;calls=[]
  def partial(fd,packet):
   calls.append((fd,packet));n=original(fd,packet)
   return n-1 if len(calls)==1 else n
  self.out.write_fn=partial
  with self.assertRaises(OSError):self.out.select_frame(_frame(KEY_ENTER,1))
  self.assertTrue(self.out.failed);self.assertTrue(self.out.verify_released())
  self.assertEqual(self.keys(),[(1,KEY_ENTER,1),(1,KEY_ENTER,0)])
 def test_uncertain_enter_release_is_cleaned_up_without_second_down(self):
  self.make();self.out.select_frame(_frame(KEY_ENTER,1));original=self.out.write_fn
  self.out.write_fn=lambda fd,packet: len(packet)-1
  with self.assertRaises(OSError):self.out.select_frame(_frame(KEY_ENTER,0))
  self.out.write_fn=original;self.assertTrue(self.out.best_effort_release())
  self.assertEqual(self.keys(),[(1,KEY_ENTER,1),(1,KEY_ENTER,0)])
 def test_select_rejects_mouse_packet_and_unowned_release(self):
  for packet in (_frame(BTN_LEFT,1),_frame(KEY_ENTER,0)):
   self.make()
   with self.assertRaises((ValueError,RuntimeError)):self.out.select_frame(packet)
   self.assertEqual(self.keys(),[])

if __name__=='__main__':unittest.main()
