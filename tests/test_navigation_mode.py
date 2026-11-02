import math,struct,unittest
from navigation_mode import NavigationMode
from grouped_prefix_output import GroupedPrefixOutput
from rolling_receiver import RollingReceiver
from test_swipe_click import touch

def sample(angle=0.,buttons=0):
 return {'touch_value':bytes((0,buttons)),'touch_active':False,'orientation3':(0.,0.,math.sin(angle/2))}
def report(angle=0.,buttons=0):
 return b'\xfc\x04'+bytes((buttons,))+struct.pack('<3f',0.,0.,math.sin(angle/2))+b'\0'*6

class Outputs:
 def __init__(self):self.failed=self.closed=False;self.mouse_fd=2;self.motion_writes=0;self.events=[]
 def write_fn(self,fd,packet):self.events.append(('motion',packet));return len(packet)
 def key_pulse(self,key):self.events.append(('key',key))
 def click_frame(self,packet):self.events.append(('click',packet));return len(packet)
 def select_frame(self,packet):self.events.append(('focus',packet));return len(packet)
 def best_effort_release(self):return True

class Tests(unittest.TestCase):
 def test_small_jitter_and_slow_drift_do_not_leave_navigation(self):
  m=NavigationMode();m.select_navigation(0.)
  for i in range(1,2000):m.observe(sample(i*.0002+.02*math.sin(i*.1)),i*.01)
  self.assertEqual(m.mode,'navigation')
 def test_deliberate_movement_reactivates_pointer_once(self):
  m=NavigationMode();m.select_navigation(0.)
  for i in range(60):m.observe(sample(max(0,i-40)*.025),i*.01)
  self.assertEqual(m.mode,'pointer');self.assertEqual(m.pointer_switches,1)
 def test_contact_buttons_and_release_grace_do_not_activate(self):
  m=NavigationMode();m.select_navigation(0.)
  for i in range(100):m.observe(sample(i*.02,0x80),i*.01)
  for i in range(30):m.observe(sample(i*.025),1.+i*.01)
  self.assertEqual(m.mode,'navigation')
 def test_gap_and_impossible_jump_do_not_count_as_deliberate_motion(self):
  m=NavigationMode();m.select_navigation(0.)
  m.observe(sample(0),1.);m.observe(sample(.5),2.);self.assertEqual(m.mode,'navigation')
  m.observe(sample(2.),2.01);self.assertEqual(m.mode,'navigation')
 def test_swipe_gate_prevents_motion_after_direction_and_click_remains(self):
  now=[0.];out=Outputs();r=GroupedPrefixOutput(out,clock=lambda:now[0],sensor_input_verified=True);r.bind(1)
  def feed(angle):
   now[0]+=.01;r.feed_raw(1,report(angle));r.tick()
  for _ in range(150):feed(0.)
  for i in range(20):feed(i*.005)
  self.assertGreater(out.motion_writes,0)
  # Actual press recognizer -> router semantic -> grouped transport.
  for value in (touch(-1500,-200,state=3),touch(-1000,-200,state=4),touch(-1000,-200,state=7)):
   now[0]+=.02;r.feed_raw(1,b'\xfc\x05'+value[1:]+b'\0'*7);r.tick()
  for i in range(90):feed(.10+.02*math.sin(i*.1))
  self.assertEqual(r.router.navigation.mode,'navigation')
  index=next(i for i,e in enumerate(out.events) if e[0]=='key')
  self.assertFalse(any(e[0]=='motion' for e in out.events[index+1:]))
  r.router.press.feed(1,b'\0\x80');r.router.press.feed(1,b'\0\0');r.tick()
  self.assertEqual(sum(e[0]=='focus' for e in out.events),2)
  for i in range(60):feed(.1+max(0,i-10)*.012)
  self.assertEqual(r.router.navigation.mode,'pointer')
  self.assertTrue(any(e[0]=='motion' for e in out.events[index+1:]))
 def test_navigation_mode_survives_receiver_rollover(self):
  now=[0.];r=RollingReceiver(Outputs(),continuity=lambda:True,mode_verified=lambda:True,clock=lambda:now[0],seconds=31)
  r.start();r.receiver.router.navigation.select_navigation(0.);original=r.navigation
  for i in range(3500):
   now[0]=i*.01;r.feed_raw(1,report());r.tick()
  self.assertGreaterEqual(r.rotations,1);self.assertIs(r.receiver.router.navigation,original)
  self.assertEqual(r.receiver.router.navigation.mode,'navigation')

if __name__=='__main__':unittest.main()
