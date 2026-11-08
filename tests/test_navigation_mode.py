import math,struct,unittest
from navigation_mode import NavigationMode
from grouped_prefix_output import GroupedPrefixOutput
from rolling_receiver import RollingReceiver
from test_swipe_click import touch

def sample(angle=0.,buttons=0,pitch=0.):
 # angle: yaw (side-to-side) about the vertical axis; pitch: up/down about the horizontal axis.
 return {'touch_value':bytes((0,buttons)),'touch_active':False,'orientation3':(math.sin(pitch/2),0.,math.sin(angle/2))}
def shake(t,amplitude=.15,period=.3):
 """Side-to-side shake: one turnaround every half period."""
 return amplitude*math.sin(2*math.pi*t/period)
def report(angle=0.,buttons=0,pitch=0.):
 return b'\xfc\x04'+bytes((buttons,))+struct.pack('<3f',math.sin(pitch/2),0.,math.sin(angle/2))+b'\0'*6

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
 def test_side_to_side_shake_reactivates_pointer_once(self):
  m=NavigationMode();m.select_navigation(0.)
  for i in range(1,200):m.observe(sample(shake(max(0,i*.01-.4))),i*.01)
  self.assertEqual(m.mode,'pointer');self.assertEqual(m.pointer_switches,1)
 def test_two_turnarounds_within_half_a_second_are_enough_and_one_is_not(self):
  def run(strokes,stroke_seconds=.15,width=.15):
   m=NavigationMode();m.select_navigation(0.)
   for i in range(1,200):
    t=max(0,i*.01-.4);k=min(int(t/stroke_seconds),strokes);frac=1. if k>=strokes else (t/stroke_seconds)%1.
    # Triangle wave: stroke 0 goes out, stroke 1 comes back, ...
    yaw=width*((frac if k%2==0 else 1-frac) if k<strokes else (1. if strokes%2 else 0.))
    m.observe(sample(yaw),i*.01)
   return m
  self.assertEqual(run(2).mode,'navigation')   # out and back: one turnaround
  self.assertEqual(run(3).mode,'pointer')      # out, back, out: two turnarounds
  self.assertEqual(run(3,stroke_seconds=.5).mode,'navigation')  # same, but too slow
 def test_slow_turnarounds_outside_the_window_do_not_count(self):
  m=NavigationMode();m.select_navigation(0.)
  # Same amplitude, but a turnaround only every 0.8 s.
  for i in range(1,900):m.observe(sample(shake(max(0,i*.01-.4),period=1.6)),i*.01)
  self.assertEqual(m.mode,'navigation')
 def test_vertical_shake_never_reactivates_pointer(self):
  m=NavigationMode();m.select_navigation(0.)
  for i in range(1,600):m.observe(sample(0.,pitch=shake(max(0,i*.01-.4),amplitude=.5)),i*.01)
  self.assertEqual(m.mode,'navigation');self.assertEqual(m.pointer_switches,0)
 def test_mostly_vertical_shake_with_sideways_twist_does_not_reactivate_pointer(self):
  # Wrist twist adds a sideways swing (0.14 rad, wider than a stroke) to a big up/down shake.
  m=NavigationMode();m.select_navigation(0.)
  for i in range(1,600):
   t=max(0,i*.01-.4);m.observe(sample(shake(t,amplitude=.07),pitch=shake(t,amplitude=.4)),i*.01)
  self.assertEqual(m.mode,'navigation');self.assertEqual(m.pointer_switches,0)
 def test_horizontal_shake_with_some_vertical_wobble_still_reactivates_pointer(self):
  m=NavigationMode();m.select_navigation(0.)
  for i in range(1,200):
   t=max(0,i*.01-.4);m.observe(sample(shake(t,amplitude=.15),pitch=shake(t,amplitude=.04)),i*.01)
  self.assertEqual(m.mode,'pointer')
 def test_one_vertical_stroke_breaks_the_horizontal_count(self):
  m=NavigationMode();m.select_navigation(0.)
  # right, back, then a stroke that is mostly vertical, then right again.
  path=[(0,0)]*40+[(.15*k/15,0) for k in range(1,16)]+[(.15*(1-k/15),0) for k in range(1,16)]
  path+=[(.0,.4*k/15) for k in range(1,16)]+[(.12*k/15,.4) for k in range(1,16)]
  for i,(a,pt) in enumerate(path):m.observe(sample(a,pitch=pt),.4+i*.01)
  self.assertEqual(m.mode,'navigation')
 def test_small_fast_wobble_does_not_reactivate_pointer(self):
  # Strokes narrower than STROKE_RADIANS, however quick.
  m=NavigationMode();m.select_navigation(0.)
  for i in range(1,600):m.observe(sample(shake(max(0,i*.01-.4),amplitude=NavigationMode.STROKE_RADIANS*.4,period=.2)),i*.01)
  self.assertEqual(m.mode,'navigation')
 def test_large_but_one_directional_rotation_does_not_leave_navigation(self):
  m=NavigationMode();m.select_navigation(0.)
  for i in range(1,400):m.observe(sample(i*.005),i*.01)
  self.assertEqual(m.mode,'navigation');self.assertEqual(m.pointer_switches,0)
 def test_hand_wobble_between_swipes_does_not_leave_navigation(self):
  m=NavigationMode();m.select_navigation(0.)
  for i in range(1,600):m.observe(sample(.03*math.sin(i*.3)+.1*math.sin(i*.04)),i*.01)
  self.assertEqual(m.mode,'navigation')
 def test_shaking_before_the_release_delay_ends_does_not_count(self):
  m=NavigationMode();m.select_navigation(0.)
  for i in range(1,30):m.observe(sample(shake(i*.01)),i*.01)
  self.assertEqual(m.mode,'navigation')
 def test_contact_buttons_and_release_grace_do_not_activate(self):
  m=NavigationMode();m.select_navigation(0.)
  for i in range(100):m.observe(sample(shake(i*.01),0x80),i*.01)
  for i in range(30):m.observe(sample(shake(i*.01)),1.+i*.01)
  self.assertEqual(m.mode,'navigation')
 def test_gap_and_impossible_jump_do_not_count_as_deliberate_motion(self):
  m=NavigationMode();m.select_navigation(0.)
  m.observe(sample(0),1.);m.observe(sample(.5),2.);self.assertEqual(m.mode,'navigation')
  m.observe(sample(2.),2.01);self.assertEqual(m.mode,'navigation')
 def test_gaps_between_reports_break_the_shake(self):
  m=NavigationMode();m.select_navigation(0.)
  for i in range(1,100):m.observe(sample(shake(i*.1)),1.+i*.1)
  self.assertEqual(m.mode,'navigation')
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
  for i in range(60):feed(.1+shake(i*.01))
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
