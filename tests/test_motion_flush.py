import sys,unittest
from pathlib import Path
from grouped_prefix_output import GroupedPrefixOutput
from relative_grouped_packets import encode_neutral_cursor_flush

class Outputs:
 def __init__(self):self.failed=self.closed=False;self.mouse_fd=2;self.motion_writes=0;self.packets=[];self.clicks=[];self.keys=[]
 def write_fn(self,fd,data):self.packets.append(data);return len(data)
 def click_frame(self,packet):self.clicks.append(packet);return len(packet)
 def key_pulse(self,action):self.keys.append(action)
 def best_effort_release(self):return True

class MotionTests(unittest.TestCase):
 def make(self):
  self.now=0.;self.output=Outputs();self.r=GroupedPrefixOutput(self.output,clock=lambda:self.now,sensor_input_verified=True);self.r.bind(1);self.r.router.pose.last_pose=(0.,0.)
 def tick(self,delta,advance=.020):
  self.now+=advance;self.r.router.tick=lambda:delta;self.r.tick()
 def test_continuous_motion_flushes_previous_frame_before_next_body(self):
  self.make()
  for _ in range(10):self.tick((15,3))
  self.assertGreaterEqual(self.output.packets.count(encode_neutral_cursor_flush()),8)
  self.assertFalse(self.r.closed)
 def test_oversized_motion_does_not_stop_buttons_or_following_motion(self):
  self.make();self.tick((1921,0))
  self.assertFalse(self.r.closed);self.assertEqual(self.output.packets,[])
  self.r._emit('center',True);self.r._emit('center',False);self.assertEqual(len(self.output.clicks),2)
  self.r.router.pose.last_pose=(0.,0.);self.tick((15,2));self.assertEqual(self.output.motion_writes,1)
  self.assertEqual(self.r.summary()['motionBudgetDrops'],1)
 def test_diagonal_record_budget_is_combined(self):
  self.make();self.tick((960,961));self.assertFalse(self.r.closed);self.assertEqual(self.output.packets,[])
 def test_invalid_delta_still_fails_closed(self):
  self.make()
  with self.assertRaises(TypeError):self.tick((True,0))
  self.assertTrue(self.r.closed)
 def test_write_failure_is_not_dropped_as_motion_budget(self):
  self.make();self.output.write_fn=lambda *_:0
  with self.assertRaises(RuntimeError):self.tick((15,1))
  self.assertTrue(self.r.closed)
 def test_pending_semantic_order_survives_motion_drop(self):
  self.make();self.tick((15,0));self.r._emit('center',True);self.r._emit('center',False)
  self.tick((1921,0));self.assertEqual(len(self.output.clicks),2);self.assertFalse(self.r.closed)

if __name__=='__main__':unittest.main()
