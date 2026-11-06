import os, sys, unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
import receiver_recovery_entry as entry
class RetryTests(unittest.TestCase):
 def invoke(self, failures, changed=False):
  old={'pid':99999,'startTicks':1,'status':{'Uid':' '.join([str(os.getuid())]*4)}}
  accepted={'request':{'priorProcess':old,'gattLookupReply':{}}}
  stop=Mock();stop.is_set.return_value=False;now=[1.]
  stop.wait.side_effect=lambda n:now.__setitem__(0,now[0]+n)
  pump=Mock();pump.stop.return_value=True
  pump.snapshot.side_effect=([{'generation':1},{'generation':2}] if changed else lambda:{'generation':1})
  lease=Mock();lease.held.return_value=True;records=Mock(return_value=True)
  with ExitStack() as s:
   for name,value in [('recovery_controller_record',{'run':'a'*32}),('authenticate',accepted),('prior_run',{'process':old,'priorOutcome':'attention'}),('write_recovery_start',True),('LocalFeatureLease',lease),('RecoveryRecords',records),('PersistentConnectedStatusPump',pump),('archive_uncertain',True)]:s.enter_context(patch.object(entry,name,return_value=value))
   s.enter_context(patch.object(entry,'_start_ticks',side_effect=FileNotFoundError))
   s.enter_context(patch.object(entry.time,'monotonic',side_effect=lambda:now[0]))
   recover=s.enter_context(patch.object(entry,'recover_zero',side_effect=failures))
   receipt=s.enter_context(patch.object(entry,'write_recovery_receipt'))
   result=entry.run_recovery(state='/unused',controller_app='/c',controller_package='/p',pin={},stop=stop)
   return result,recover.call_count,records,now[0]
 def test_preflight_only_retries_and_reuses_same_generation(self):
  result,count,_,_=self.invoke([entry.RecoveryTargetUnavailable('recovery target unavailable'),{'modeZeroVerified':True}])
  self.assertEqual(count,2);self.assertEqual(result['status'],'recovered')
 def test_other_failure_is_not_repeated(self):
  result,count,_,_=self.invoke([RuntimeError('after command')])
  self.assertEqual(count,1);self.assertEqual(result['status'],'attention')
 def test_connection_generation_change_stops_retry(self):
  result,count,_,_=self.invoke([entry.RecoveryTargetUnavailable('recovery target unavailable')],changed=True)
  self.assertEqual(count,1);self.assertEqual(result['status'],'attention')
 def test_retry_is_bounded(self):
  result,count,_,now=self.invoke(entry.RecoveryTargetUnavailable('recovery target unavailable'))
  self.assertEqual(result['status'],'attention');self.assertLessEqual(count,32);self.assertLessEqual(now,4.1)
if __name__=='__main__':unittest.main()
