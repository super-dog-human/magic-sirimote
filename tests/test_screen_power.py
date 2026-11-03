import unittest
from screen_power import ScreenPowerWorker
from combined_controls import CombinedControls
from rolling_receiver import RollingReceiver
from test_navigation_mode import Outputs,report

class Client:
 def __init__(self,state='Active',lost_reply=False):self.state=state;self.calls=[];self.lost=lost_reply
 def call(self,method):
  self.calls.append(method)
  if method=='turnOffScreen':self.state='Screen Off'
  if method=='turnOnScreen':self.state='Active'
  if self.lost and method!='getPowerState':return None
  return {'returnValue':True,'state':self.state}

class Tests(unittest.TestCase):
 def test_toggle_twice_uses_tv_state_and_one_write_per_press(self):
  w=ScreenPowerWorker();c=Client();w._step(c);self.assertFalse(w.blocked())
  self.assertTrue(w.toggle());self.assertTrue(w.blocked());self.assertFalse(w.toggle())
  w._step(c);self.assertTrue(w.blocked());self.assertEqual(c.state,'Screen Off')
  self.assertTrue(w.toggle());w._step(c);self.assertFalse(w.blocked())
  self.assertEqual([m for m in c.calls if m!='getPowerState'],['turnOffScreen','turnOnScreen'])
 def test_unknown_write_is_not_retried(self):
  w=ScreenPowerWorker();c=Client(lost_reply=True);w.toggle();w._step(c)
  for _ in range(3):w._step(c)
  self.assertEqual(c.calls.count('turnOffScreen'),1);self.assertTrue(w.blocked())
 def test_unavailable_power_does_not_issue_write(self):
  class Unknown(Client):
   def call(self,m):self.calls.append(m);return None
  c=Unknown();w=ScreenPowerWorker();w.toggle();w._step(c)
  self.assertEqual(c.calls,['getPowerState']);self.assertTrue(w.blocked())
 def test_standby_and_transition_are_not_screen_toggle_targets(self):
  for state in ['Active Standby','Suspend']:
   c=Client(state);w=ScreenPowerWorker();w.toggle();w._step(c);self.assertEqual(c.calls,['getPowerState'])
  w=ScreenPowerWorker();self.assertIsNone(w._state({'returnValue':True,'state':'Active','processing':'Request Suspend'}))
 def test_stale_state_blocks_output(self):
  now=[0.];w=ScreenPowerWorker(clock=lambda:now[0]);w._step(Client());self.assertFalse(w.blocked());now[0]=4;self.assertTrue(w.blocked())
 def test_request_during_poll_remains_pending(self):
  w=ScreenPowerWorker()
  class Racing(Client):
   def call(self,m):w.toggle();return super().call(m)
  w._step(Racing());self.assertTrue(w.blocked());self.assertTrue(w.requested);self.assertTrue(w.pending)
 def test_paused_cursor_does_not_write_or_expire_and_resumes_without_replay(self):
  now=[0.];o=Outputs();r=RollingReceiver(o,continuity=lambda:True,mode_verified=lambda:True,clock=lambda:now[0],seconds=31);r.start()
  for i in range(180):now[0]+=.01;r.feed_raw(1,report(max(0,i-150)*.006));r.tick()
  self.assertGreater(o.motion_writes,0);r.pause_output();count=len(o.events)
  for i in range(40):now[0]+=10;r.feed_raw(1,report(i*.02));self.assertTrue(r.tick())
  self.assertEqual(len(o.events),count);self.assertFalse(r.closed)
  r.resume_output();r.feed_raw(1,report());r.tick();self.assertEqual(len(o.events),count);self.assertFalse(r.paused)
 def test_mic_hold_toggles_once_and_drain_precedes_command(self):
  now=[0.];o=Outputs();r=RollingReceiver(o,continuity=lambda:True,mode_verified=lambda:True,clock=lambda:now[0],seconds=31)
  class Screen:
   off=False;calls=0
   def blocked(self):return self.off
   def toggle(self):
    assert r.paused and r.receiver.closed
    self.off=not self.off;self.calls+=1;return True
  s=Screen();keys=[];combined=CombinedControls(r,keys.append,screen_control=s);combined.start()
  def feed(mask):now[0]+=.01;combined.feed_raw(1,bytes([0xfc,0,mask]));combined.tick()
  for mask in [0,16,16,16,0,32,0,8,0]:feed(mask)
  self.assertEqual(s.calls,1);self.assertTrue(r.paused);self.assertEqual(keys,[])
  feed(16);feed(16);self.assertEqual(s.calls,1);self.assertTrue(r.paused)
  feed(0);self.assertEqual(s.calls,2);self.assertFalse(r.paused)
  feed(0);feed(32);feed(0);self.assertEqual(keys,['back'])
 def test_screen_off_on_reconnect_blocks_before_first_output(self):
  w=ScreenPowerWorker();w._step(Client('Screen Off'))
  now=[0.];o=Outputs();r=RollingReceiver(o,continuity=lambda:True,mode_verified=lambda:True,clock=lambda:now[0],seconds=31)
  c=CombinedControls(r,lambda _:True,screen_control=w);c.start();c.tick()
  self.assertTrue(r.paused);self.assertEqual(o.events,[])
 def test_stop_never_turns_screen_on(self):
  c=Client('Screen Off');w=ScreenPowerWorker();w._step(c);self.assertTrue(w.stop());self.assertNotIn('turnOnScreen',c.calls)
if __name__=='__main__':unittest.main()
