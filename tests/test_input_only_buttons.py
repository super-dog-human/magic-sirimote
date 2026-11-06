import unittest
from types import SimpleNamespace
from unittest.mock import patch
from early_navigation import EarlyNavigation
from output_bridge import VerifiedOutputs
from fixture_devices import MemoryDevices
import system_buttons

class Tests(unittest.TestCase):
 def exercise(self,button,hold=False,ir=False):
  now=[0.];queue=[];actions=[];device=MemoryDevices()
  outputs=VerifiedOutputs(1,2,ioctl_fn=device.ioctl,write_fn=device.write,sleep_fn=lambda _:None)
  def read(fd,size):
   if not queue:raise BlockingIOError()
   return queue.pop(0)
  mapping={f'{button:02x}:00':'ir:09' if ir else 'playpause',f'{button:02x}:01':'ir:09' if ir else 'back'}
  with patch.object(system_buttons,'CONFIGURED',mapping):
   early=EarlyNavigation(outputs,8,generation=1,guard=lambda:True,abort=lambda:False,
    clock=lambda:now[0],read_fn=read,system_key_emit=lambda action:actions.append(action),
    screen_control=SimpleNamespace(blocked=lambda:False,toggle=lambda:True))
   early.start();early.receiver.buttons.clock=lambda:now[0]
   queue.append(bytes([252,0,0]));early.pump()
   now[0]=150.;early.pump()
   queue.append(bytes([252,0,button]));early.pump()
   self.assertEqual(actions,[])
   now[0]+=.8 if hold else .1
   queue.append(bytes([252,0,0]));early.pump()
   self.assertEqual(actions,[] if ir else ['back' if hold else 'playpause'])
   self.assertFalse(early.rolling.receiver.bridge.sensor_input_verified)
   early.stop();self.assertTrue(outputs.verify_released())
 def test_all_six_short_presses_after_idle_without_motion_packets(self):
  for button in (1,2,4,8,16,32):
   with self.subTest(button=button):self.exercise(button)
 def test_all_six_holds_after_idle_without_motion_packets(self):
  for button in (1,2,4,8,16,32):
   with self.subTest(button=button):self.exercise(button,hold=True)
 def test_ir_assignments_do_not_emit_duplicate_tv_actions(self):
  for button in (1,2,4,8,16,32):
   with self.subTest(button=button):self.exercise(button,ir=True)
