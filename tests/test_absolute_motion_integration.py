import unittest
from test_absolute_pointer import Kernel
from grouped_prefix_output import GroupedPrefixOutput
from output_bridge import EVENT, BTN_LEFT, KEY_ENTER
from test_navigation_mode import report, shake
from absolute_pointer import SHOW


class AbsoluteMotionIntegrationTests(unittest.TestCase):
 def setUp(self):
  self.now=0.;self.kernel=Kernel();self.output=self.kernel.replacement()
  self.receiver=GroupedPrefixOutput(self.output,clock=lambda:self.now,sensor_input_verified=True)
  self.receiver.bind(1);self.receiver.router.pose.last_pose=(0.,0.)
 def tick(self,delta):
  self.now+=.02;self.receiver.router.tick=lambda:delta;self.receiver.tick()
 def test_continuous_receiver_converts_batches_before_the_device_write(self):
  for _ in range(10):self.tick((31,-17))
  self.tick(None)
  self.assertEqual(self.kernel.positions,[1735,115])
  self.assertEqual(self.output.motion_writes,10)
  packets=[packet for fd,packet in self.kernel.writes if fd==3]
  self.assertEqual(len(packets),10,'Neutral tails must not redisplay or move an absolute cursor')
  for packet in packets:
   events=[v[2:] for v in EVENT.iter_unpack(packet)]
   self.assertFalse(any(kind==2 for kind,_,_ in events),'ABS device must never receive legacy REL packets')
   self.assertEqual(events[:2],[(1,1198,1),(1,1198,0)])
   self.assertEqual(sum(kind==0 for kind,_,_ in events),1)
  self.assertFalse(self.receiver.failed)
 def test_small_motion_is_scaled_immediately_and_reversal_has_no_backlog(self):
  self.tick((1,-1))
  self.assertEqual(self.kernel.positions,[962,537])
  self.assertEqual(len(self.kernel.writes),1)
  self.tick((-1,1))
  self.assertEqual(self.kernel.positions,[960,540])
  self.tick(None)
  self.assertEqual(len(self.kernel.writes),2)
 def test_edge_clamp_does_not_require_unwinding_overshoot(self):
  self.kernel.positions=[1919,1]
  self.tick((10,-10))
  self.assertEqual(self.kernel.positions,[1920,0])
  self.tick((-1,1))
  self.assertEqual(self.kernel.positions,[1917,2])
 def test_pointer_click_then_swipe_selection_uses_the_matching_output(self):
  self.tick((10,5));self.tick(None)
  self.receiver._emit('center',True);self.receiver._emit('center',False)
  self.receiver.router.navigation.select_navigation(self.now)
  self.receiver._emit('left',True);self.receiver._emit('left',False)
  self.receiver._emit('center',True);self.receiver._emit('center',False)
  keys=[(fd,code,value) for fd,packet in self.kernel.writes for _,_,kind,code,value in EVENT.iter_unpack(packet) if kind==1 and code in (BTN_LEFT,KEY_ENTER)]
  self.assertEqual(keys,[(3,BTN_LEFT,1),(3,BTN_LEFT,0),(1,KEY_ENTER,1),(1,KEY_ENTER,0)])
  self.assertTrue(self.output.verify_released())
 def test_absolute_write_failure_stops_the_continuous_receiver(self):
  self.output.write_fn=lambda *_:0
  with self.assertRaises(RuntimeError):self.tick((10,5))
  self.assertTrue(self.receiver.closed);self.assertTrue(self.output.failed)

 def shake_after_swipe(self,amplitude=.15,pitch=False):
  self.receiver.router.navigation.select_navigation(self.now)
  del self.kernel.writes[:]
  for i in range(80):
   self.now+=.01;a=shake(i*.01,amplitude=amplitude)
   self.receiver.feed_raw(1,report(0.,pitch=a) if pitch else report(a));self.receiver.tick()
 def test_shake_after_a_swipe_shows_the_pointer_at_the_screen_center(self):
  self.kernel.positions=[100,900]
  self.shake_after_swipe()
  self.assertEqual(self.receiver.router.navigation.mode,'pointer')
  first=[v[2:] for v in EVENT.iter_unpack(self.kernel.writes[0][1])]
  self.assertEqual(self.kernel.writes[0][0],3)
  self.assertEqual(first[:2],[(1,SHOW,1),(1,SHOW,0)])
  self.assertEqual(first[-2][1:],(1,540));self.assertEqual(first[-3][1:],(0,960))
  self.assertEqual(sum(1 for _,p in self.kernel.writes for e in EVENT.iter_unpack(p) if e[2:4]==(1,SHOW) and e[4]==1),1)
 def test_vertical_shake_after_a_swipe_leaves_the_pointer_hidden(self):
  self.kernel.positions=[100,900]
  self.shake_after_swipe(amplitude=.5,pitch=True)
  self.assertEqual(self.receiver.router.navigation.mode,'navigation')
  self.assertEqual(self.kernel.writes,[]);self.assertEqual(self.kernel.positions,[100,900])


if __name__=='__main__':unittest.main()
