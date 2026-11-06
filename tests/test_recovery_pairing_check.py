import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))

from postconnect_receiver_device import RecoveryPairingCheck
from borrowed_recovery_runtime import recover_owned_zero
from borrowed_gatt_view import TARGET, ADAPTER


class Tests(unittest.TestCase):
 def test_repeated_guards_reuse_only_a_quarter_second(self):
  now=[10.];check=Mock(return_value=True);control=Mock(return_value=True)
  guard=RecoveryPairingCheck(check,control,clock=lambda:now[0])
  for i in range(25):
   now[0]=10+i*.009
   self.assertTrue(guard())
  self.assertEqual(check.call_count,1)
  self.assertEqual(control.call_count,26)
  now[0]=10.25;self.assertTrue(guard());self.assertEqual(check.call_count,2)
  self.assertTrue(guard(fresh=True));self.assertEqual(check.call_count,3)

 def test_disconnect_or_revocation_invalidates_cached_pairing_permanently(self):
  check=Mock(return_value=True);control=Mock(return_value=True)
  guard=RecoveryPairingCheck(check,control,clock=lambda:10.)
  self.assertTrue(guard());control.return_value=False
  self.assertFalse(guard());control.return_value=True
  self.assertFalse(guard());self.assertEqual(check.call_count,1)

 def test_status_failure_or_change_during_read_cannot_be_reused(self):
  for failure in ('false','exception','control'):
   check=Mock(return_value=True);control=Mock(return_value=True)
   if failure=='false':check.return_value=False
   elif failure=='exception':check.side_effect=OSError('read failed')
   else:control.side_effect=[True,False]
   guard=RecoveryPairingCheck(check,control,clock=lambda:10.)
   self.assertFalse(guard());self.assertFalse(guard())
   self.assertEqual(check.call_count,1)

 def test_clock_rollback_and_slow_reads_do_not_extend_evidence(self):
  now=[10.];check=Mock(return_value=True)
  guard=RecoveryPairingCheck(check,lambda:True,clock=lambda:now[0])
  self.assertTrue(guard());now[0]=9.9;self.assertFalse(guard())
  now[0]=11.;self.assertFalse(guard())
  def slow():now[0]+=.3;return True
  check=Mock(side_effect=slow)
  guard=RecoveryPairingCheck(check,lambda:True,clock=lambda:now[0])
  self.assertTrue(guard());self.assertTrue(guard());self.assertEqual(check.call_count,2)

 def recovery(self,paired):
  profile={'returnValue':True,'address':TARGET,'adapterAddress':ADAPTER,
           'connected':True,'connecting':False,'connectRequest':False}
  watch=Mock();watch.snapshot.return_value={'generation':2,'observedAt':10.,'hid':profile,'gatt':profile}
  lease=Mock();lease.held.return_value=True
  view=Mock();view.generation=2;view.client_id='5';view.discover.return_value='5'
  requester=Mock();requester.adopt.return_value=view
  class Reader:
   reference_verified=True
   def __init__(self,call,*,exclusive_feature_guard,clock):self.guard=exclusive_feature_guard
   def bind_borrowed(self,**kwargs):
    if not self.guard():raise RuntimeError('lost pairing')
   def read(self,generation):
    for _ in range(20):
     if not self.guard():raise RuntimeError('lost pairing')
    return {'mode':0}
  args=dict(watch=watch,lease=lease,generation=2,paired_check=paired,
   external_feature_guard=lambda:True,record=lambda _:True,session_closed=lambda:True,
   gatt_lookup_reply={'returnValue':True,'address':TARGET,'adapterAddress':ADAPTER,'clientId':'5'},
   notification_preparer=lambda *a,**k:{'beforeFlags':1,'writeAttempted':False},
   clock=lambda:10.,requester_factory=lambda **_:requester,reader_factory=Reader,
   activation_factory=lambda **_:SimpleNamespace(),stop_factory=lambda **_:lambda *a,**k:True)
  return args,view

 def test_recovery_requires_fresh_pairing_at_completion(self):
  for final_paired in (True,False):
   check=Mock(side_effect=[True,final_paired]);args,view=self.recovery(check)
   if final_paired:
    result=recover_owned_zero(**args)
    self.assertTrue(result['modeZeroVerified']);self.assertTrue(result['priorSessionClosedVerified'])
   else:
    with self.assertRaisesRegex(RuntimeError,'zero unconfirmed'):recover_owned_zero(**args)
   self.assertEqual(check.call_count,2)
   view.close.assert_called_once()


 def test_notifications_are_prepared_before_any_recovery_feature_access(self):
  args,view=self.recovery(lambda:True);events=[]
  def notification(*a,**k):
   self.assertTrue(k['guard']());events.append('notification')
   return {'beforeFlags':0,'writeAttempted':True}
  factory=args['activation_factory']
  def activation(**kwargs):
   events.append('feature-client');return factory(**kwargs)
  args.update(notification_preparer=notification,activation_factory=activation,
              record=lambda event:events.append(event) or True)
  result=recover_owned_zero(**args)
  self.assertTrue(result['modeZeroVerified'])
  self.assertLess(events.index('notification'),events.index('feature-client'))
  record=next(e for e in events if isinstance(e,dict) and e['stage']=='recovery-notification-verified')
  self.assertEqual(record['beforeFlags'],0);self.assertTrue(record['writeAttempted'])

 def test_notification_failure_or_guard_loss_prevents_recovery_feature_access(self):
  for fail in ('raise','guard','record'):
   args,view=self.recovery(lambda:True)
   def notification(*a,**k):
    if fail=='raise':raise RuntimeError('notification-enable-unconfirmed')
    if fail=='guard':args['watch'].snapshot.return_value=None
    return {'beforeFlags':1,'writeAttempted':False}
   def record(event):return not (fail=='record' and event['stage']=='recovery-notification-verified')
   args.update(notification_preparer=notification,record=record,
               activation_factory=lambda **_:self.fail('feature access after notification failure'))
   with self.assertRaises(RuntimeError):recover_owned_zero(**args)
   view.close.assert_called_once()


if __name__=='__main__':unittest.main()
