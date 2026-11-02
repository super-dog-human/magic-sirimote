import unittest
from system_buttons import SystemButtons

class ButtonReleaseTests(unittest.TestCase):
 def setUp(self):
  self.actions=[];self.decoder=SystemButtons(self.actions.append);self.decoder.bind(1)
 def feed(self,*masks,generation=1):
  for mask in masks:self.decoder.feed(generation,bytes((0xfc,0,mask)))
 def test_each_button_waits_for_release_and_emits_once(self):
  for mask,action in ((32,'back'),(16,'back'),(1,'home'),(8,'playpause')):
   self.actions.clear();self.feed(0,mask,mask);self.assertEqual(self.actions,[])
   self.feed(0,0);self.assertEqual(self.actions,[action])
 def test_held_at_start_does_not_become_click(self):
  self.feed(32,32,0);self.assertEqual(self.actions,[])
  self.feed(32,0);self.assertEqual(self.actions,['back'])
 def test_chord_or_changed_button_cancels_until_neutral(self):
  for sequence in ((0,32,48,32,0),(0,32,16,0),(0,32,2,32,0)):
   self.feed(*sequence);self.assertEqual(self.actions,[])
 def test_touch_contact_may_remain_when_button_released(self):
  self.feed(0,32);self.decoder.feed(1,bytes((0xfc,1,0))+bytes(11))
  self.assertEqual(self.actions,['back'])
 def test_reconnect_discards_pending_press(self):
  self.feed(0,32);self.decoder.unbind(1);self.decoder.bind(2)
  self.feed(0,generation=1);self.feed(0,generation=2);self.assertEqual(self.actions,[])
  self.feed(32,0,generation=2);self.assertEqual(self.actions,['back'])
 def test_surface_and_volume_are_ignored(self):
  self.feed(0,128,0,2,0,4,0);self.assertEqual(self.actions,[])
 def test_rejected_release_is_not_retried(self):
  calls=[]
  def reject(action):calls.append(action);return False
  self.decoder=SystemButtons(reject);self.decoder.bind(1)
  self.feed(0,32,0,0);self.assertEqual(calls,['back']);self.assertEqual(self.decoder.actions,0)
 def test_emitter_failure_closes_decoder(self):
  def fail(action):raise RuntimeError('output failed')
  self.decoder=SystemButtons(fail);self.decoder.bind(1);self.feed(0,32)
  with self.assertRaises(RuntimeError):self.feed(0)
  self.assertTrue(self.decoder.failed);self.feed(0,32,0)

class CombinedButtonBudgetTests(unittest.TestCase):
 def test_repeated_releases_cross_budget_without_dropped_action(self):
  from combined_controls import CombinedControls
  class Rolling:
   generation=1
   closed=False
   def start(self):pass
   def feed_raw(self,generation,report):return True
   def tick(self):return True
   def stop(self,reason):self.closed=True
   def _live(self):return True
  actions=[];controls=CombinedControls(Rolling(),actions.append,max_system_actions=2);controls.start()
  for mask in (0,32,0,16,0,8,0,1,0,32,0):controls.feed_raw(1,bytes((0xfc,0,mask)))
  self.assertEqual(actions,['back','back','playpause','home','back'])
