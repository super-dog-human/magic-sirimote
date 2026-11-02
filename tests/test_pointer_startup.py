import math,unittest
from adaptive_prefix_pose import AdaptivePrefixPose

def pose(angle=0.,touch=False):
 return {'orientation3':(0.,0.,math.sin(angle/2)), 'touch_active':touch,
         'touch_value':b'\x01\x00' if touch else b'\x00\x00'}

class PointerStartupTests(unittest.TestCase):
 def test_continuous_movement_becomes_ready_without_stillness(self):
  p=AdaptivePrefixPose();outputs=[]
  for i in range(18):
   p.feed(pose(i*.015),i*.01);outputs.append(p.tick(i*.01))
   if p.summary()['calibrated']:break
  self.assertTrue(p.summary()['calibrated']);self.assertLessEqual(i*.01,.17)
  self.assertEqual(p.stats['calibrationResets'],0);self.assertTrue(all(v is None for v in outputs))
  angle=i*.015
  for j in range(1,15):
   p.feed(pose(angle),(i+j)*.01)
   self.assertIn(p.tick((i+j)*.01),(None,(0,0)))
 def test_stationary_start_never_moves_cursor(self):
  p=AdaptivePrefixPose()
  for i in range(100):
   p.feed(pose(.9),i*.01);self.assertIn(p.tick(i*.01),(None,(0,0)))
  self.assertTrue(p.summary()['calibrated'])
 def test_move_after_ready_produces_motion(self):
  p=AdaptivePrefixPose();out=[]
  for i in range(80):
   p.feed(pose(max(0,i-25)*.002),i*.01);out.append(p.tick(i*.01))
  self.assertTrue(any(v is not None and v!=(0,0) for v in out))
 def test_startup_jump_restarts_short_window(self):
  p=AdaptivePrefixPose()
  for i in range(10):p.feed(pose(),i*.01)
  p.feed(pose(.6),.10)
  for i in range(11,24):p.feed(pose(.6),i*.01)
  self.assertFalse(p.summary()['calibrated']);self.assertEqual(p.stats['calibrationResets'],1)
  for i in range(24,28):p.feed(pose(.6),i*.01)
  self.assertTrue(p.summary()['calibrated'])
 def test_gap_restarts_window_even_when_tracking_cleared(self):
  p=AdaptivePrefixPose()
  for i in range(10):p.feed(pose(),i*.01);p._clear_tracking()
  p.feed(pose(),.25)
  self.assertFalse(p.summary()['calibrated']);self.assertEqual(p.samples,1)
  self.assertEqual(p.stats['calibrationResets'],1)
 def test_touch_requires_new_untouched_window(self):
  p=AdaptivePrefixPose()
  for i in range(10):p.feed(pose(),i*.01)
  p.feed(pose(touch=True),.1)
  for i in range(11,24):p.feed(pose(),i*.01)
  self.assertFalse(p.summary()['calibrated'])
  for i in range(24,29):p.feed(pose(),i*.01)
  self.assertTrue(p.summary()['calibrated'])
 def test_burst_at_one_timestamp_cannot_finish_startup(self):
  p=AdaptivePrefixPose()
  for i in range(100):p.feed(pose(),0.)
  self.assertFalse(p.summary()['calibrated'])
 def test_invalid_pose_cannot_become_reference(self):
  p=AdaptivePrefixPose()
  for i in range(100):
   p.feed({**pose(),'orientation3':(2.,0.,0.)},i*.01)
   self.assertIsNone(p.tick(i*.01))
  self.assertFalse(p.summary()['calibrated'])
 def test_touch_after_ready_does_not_reinitialize_or_replay_motion(self):
  p=AdaptivePrefixPose()
  for i in range(30):p.feed(pose(),i*.01);p.tick(i*.01)
  reference=p.reference_inverse
  p.feed(pose(.5,True),.3);p.tick(.3)
  for i in range(31,45):
   p.feed(pose(.5),i*.01);self.assertIn(p.tick(i*.01),(None,(0,0)))
  self.assertEqual(p.reference_inverse,reference)
 def test_backward_time_stops_processing(self):
  p=AdaptivePrefixPose();p.feed(pose(),1.);p.feed(pose(),.5)
  self.assertTrue(p.closed);self.assertIsNone(p.tick(2.))
class RestingNoiseTests(unittest.TestCase):
 def test_resting_jitter_and_slow_sensor_drift_do_not_accumulate(self):
  p=AdaptivePrefixPose();writes=[]
  for i in range(1500):
   now=i*.01;angle=.00065*math.sin(now*3)+.00006*now
   p.feed(pose(angle),now);writes.append(p.tick(now))
  self.assertTrue(p.summary()['calibrated'])
  self.assertFalse(any(v not in (None,(0,0)) for v in writes))
 def test_normal_motion_resumes_without_long_wait(self):
  p=AdaptivePrefixPose();first=None
  for i in range(100):
   now=i*.01;angle=0 if now<.4 else (now-.4)*.20
   p.feed(pose(angle),now);delta=p.tick(now)
   if delta not in (None,(0,0)) and first is None:first=now
  self.assertIsNotNone(first);self.assertLess(first,.7)
 def test_stop_after_movement_settles_and_retains_no_movement_backlog(self):
  p=AdaptivePrefixPose();tail=[]
  for i in range(400):
   now=i*.01
   angle=min(max(now-.4,0),.6)*.25
   if now>=1:angle+=.00065*math.sin(now*3)
   p.feed(pose(angle),now);delta=p.tick(now)
   if now>=2:tail.append(delta)
  self.assertTrue(p.resting);self.assertFalse(any(v not in (None,(0,0)) for v in tail))
 def test_departure_discards_suppressed_offset(self):
  p=AdaptivePrefixPose()
  self.assertTrue(p._hold_resting_noise((0.,0.),0.,.02))
  self.assertTrue(p._hold_resting_noise((.002,0.),.02,.02))
  self.assertTrue(p._hold_resting_noise((.01,0.),.04,.02))
  self.assertFalse(p.resting);self.assertEqual(p.rest_anchor,[.01,0.])

class TransportDiagnosticTests(unittest.TestCase):
 def test_transport_reason_is_bounded_and_old_records_remain_valid(self):
  from receive_diagnostics import capture,valid,KINDS
  from test_receive_diagnostics import details
  old=details();old['motionTransport']={'budgetDrops':0,'bodyWrites':1,'neutralWrites':1}
  self.assertTrue(valid(old))
  for reason in ('queue-age-exceeded','semantic-dispatch-uncertain','private raw data'):
   stats={};summary={'current':{'motionBudgetDrops':0,'transport':{'reason':reason}},'decodedKinds':dict.fromkeys(KINDS,0),'stopReason':'combined-output-error'}
   capture(stats,summary,'receive-exception',{})
   out=stats['receiveDiagnostics'];self.assertTrue(valid(out))
   self.assertEqual(out['motionTransport']['reason'],None if reason=='private raw data' else reason)
  old['motionTransport']['reason']='unrecognized';self.assertFalse(valid(old))
if __name__=='__main__':unittest.main()
