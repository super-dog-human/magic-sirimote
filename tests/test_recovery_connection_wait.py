import sys,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
from resident_controller_entry import wait_recovery_connection

class Tests(unittest.TestCase):
 def fixture(self):
  now=[0.];stop=Mock();stop.is_set.return_value=False
  stop.wait.side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)
  watch=Mock();watch.is_open.return_value=True
  watch.snapshot.side_effect=lambda:{'generation':2} if now[0]>=120 else None
  lease=Mock();lease.held.return_value=True
  return dict(watch=watch,lease=lease,stop=stop,clock=lambda:now[0]),now
 def test_remote_can_wake_after_old_ninety_second_deadline(self):
  k,now=self.fixture();wait_recovery_connection(**k)
  self.assertEqual(now[0],120);self.assertEqual(k['stop'].wait.call_count,480)
 def test_explicit_timeout_remains_bounded(self):
  k,now=self.fixture()
  with self.assertRaisesRegex(RuntimeError,'connected target unavailable'):wait_recovery_connection(**k,timeout=1)
  self.assertEqual(now[0],1)
 def test_stop_and_owner_loss_interrupt_wait(self):
  for reason in ('stop','lease','watch'):
   k,now=self.fixture()
   if reason=='stop':k['stop'].is_set.side_effect=lambda:now[0]>=.5
   if reason=='lease':k['lease'].held.side_effect=lambda:now[0]<.5
   if reason=='watch':k['watch'].is_open.side_effect=lambda:now[0]<.5
   with self.assertRaises(RuntimeError):wait_recovery_connection(**k)
   self.assertEqual(now[0],.5)
 def test_invalid_timeout_cannot_begin_wait(self):
  for value in (0,-1,True,float('nan'),float('inf')):
   k,_=self.fixture()
   with self.assertRaises(ValueError):wait_recovery_connection(**k,timeout=value)
   k['watch'].snapshot.assert_not_called()
if __name__=='__main__':unittest.main()
