import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
from borrowed_gatt_view import TARGET,ADAPTER
from owned_idle_recovery import eligible,wait_and_recover,validate_receipt,accept_recovery,recover_missing_target

REPLY={'returnValue':True,'address':TARGET,'adapterAddress':ADAPTER,'clientId':'5'}
FAILURE={'status':'attention','phase':'stop','previousPhase':'receive',
 'readStats':{'receiveDiagnostics':{'receiveFailure':{'stage':'read','type':'OSError','errno':5}}}}

DISCONNECTED={'status':'attention','phase':'stop','previousPhase':'receive',
 'readStats':{'aborted':True,'receiveDiagnostics':{'endReason':'control-or-policy-ended',
 'receiverStopReason':'control-lost','controlFailure':'snapshot','watchState':'missing'}}}

class OwnedRecoveryTests(unittest.TestCase):
 def setup_path(self):
  watch=Mock();watch.is_open.return_value=True;watch.mark_idle.return_value=True
  watch.snapshot.return_value={'generation':2}
  lease=Mock();lease.held.return_value=True
  stop=Mock();stop.is_set.return_value=False
  lookup=Mock(return_value=(REPLY,2));recover=Mock(return_value={'status':'recovered','modeZeroVerified':True,'priorSessionClosedVerified':True})
  records=Mock(return_value=True);factory=Mock(return_value=records)
  kw=dict(result=copy.deepcopy(FAILURE),state_path='/state',run='a'*32,watch=watch,lease=lease,
   initial_generation=1,stop=stop,external_feature_guard=lambda:True,clock=lambda:100,
   lookup=lookup,recover=recover,records_factory=factory,paired_check=lambda:True)
  return kw

 def test_one_cleanup_after_new_connection_leaves_journal_for_controller(self):
  k=self.setup_path();k['watch'].snapshot.side_effect=[None,{'generation':1},{'generation':2},{'generation':2}]
  out=wait_and_recover(**k)
  self.assertTrue(out['sensorStopVerified']);self.assertFalse(out['journalArchived'])
  self.assertEqual(validate_receipt(out)['generation'],2)
  self.assertEqual(k['stop'].wait.call_count,2)
  k['lookup'].assert_called_once();k['recover'].assert_called_once()
  self.assertTrue(k['recover'].call_args.kwargs['session_closed']())
  k['records_factory'].return_value.close.assert_called_once()

 def test_resources_must_be_closed_and_failure_must_be_idle_read(self):
  for value in ({'status':'complete'},
   {**FAILURE,'reason':'resource-close-unverified','errors':['target-close-error'],'sessionResult':FAILURE},
   {**FAILURE,'phase':'prepare'},
   {**FAILURE,'readStats':{'receiveDiagnostics':{'receiveFailure':{'stage':'read','type':'OSError','errno':13}}}}):
   k=self.setup_path();k['result']=value
   self.assertFalse(eligible(value));self.assertEqual(wait_and_recover(**k),value)
   k['lookup'].assert_not_called();k['watch'].mark_idle.assert_not_called()

 def test_stop_owner_loss_or_changed_connection_cannot_report_recovered(self):
  for kind in ('stop','owner','mark','change','uncertain'):
   k=self.setup_path()
   if kind=='stop':k['stop'].is_set.return_value=True
   if kind=='owner':k['lease'].held.return_value=False
   if kind=='mark':k['watch'].mark_idle.return_value=False
   if kind=='change':k['watch'].snapshot.side_effect=[{'generation':2},{'generation':3}]
   if kind=='uncertain':k['recover'].side_effect=RuntimeError('unknown')
   self.assertNotIn('localRecovery',wait_and_recover(**k),kind)

 def test_connection_notification_before_eio_uses_same_verified_recovery(self):
  k=self.setup_path();k['result']=copy.deepcopy(DISCONNECTED)
  k['watch'].snapshot.side_effect=[None,{'generation':1},{'generation':2},{'generation':2}]
  out=wait_and_recover(**k)
  self.assertEqual(validate_receipt(out)['generation'],2)
  self.assertEqual(k['stop'].wait.call_count,2)
  k['recover'].assert_called_once()
  self.assertTrue(k['recover'].call_args.kwargs['session_closed']())

 def test_other_control_failures_cannot_take_idle_path(self):
  for field,value in (('watchState','stale'),('watchState','closed'),
   ('watchState','generation-changed'),('controlFailure','lease'),
   ('controlFailure','external'),('endReason','stop-requested'),
   ('receiverStopReason','requested'),('receiveFailure',None)):
   k=self.setup_path();k['result']=copy.deepcopy(DISCONNECTED)
   k['result']['readStats']['receiveDiagnostics'][field]=value
   self.assertFalse(eligible(k['result']),(field,value))
   wait_and_recover(**k);k['watch'].mark_idle.assert_not_called()

 def test_disconnection_does_not_override_cleanup_or_owner_failure(self):
  for reason in ('cleanup','stop','lease','closed','feature','uncertain'):
   k=self.setup_path();k['result']=copy.deepcopy(DISCONNECTED)
   if reason=='cleanup':k['result']={'reason':'resource-close-unverified','errors':['target-close-error'],'sessionResult':k['result']}
   if reason=='stop':k['stop'].is_set.return_value=True
   if reason=='lease':k['lease'].held.return_value=False
   if reason=='closed':k['watch'].is_open.return_value=False
   if reason=='feature':k['external_feature_guard']=lambda:False
   if reason=='uncertain':k['recover'].return_value={'status':'attention'}
   self.assertNotIn('localRecovery',wait_and_recover(**k),reason)
   if reason!='uncertain':k['lookup'].assert_not_called()

 def test_receipt_rejects_false_or_wrong_target_proofs(self):
  good=wait_and_recover(**self.setup_path())
  for change in ({'sensorStopVerified':False},{'journalArchived':True},
   {'cleanupDiagnostics':[{'stage':'app-cleanup-unverified'}]},
   {'localRecovery':{**good['localRecovery'],'generation':True}},
   {'localRecovery':{**good['localRecovery'],'gattLookupReply':{**REPLY,'address':'00:11:22:33:44:55'}}}):
   with self.assertRaises((ValueError,RuntimeError)):validate_receipt({**good,**change})

 def test_controller_requires_matching_exited_worker_and_fresh_generation(self):
  receipt=wait_and_recover(**self.setup_path())
  process={'pid':123,'status':{'Uid':'5050 5050 5050 5050'}}
  receipt['process']=process
  for reason in ('live','stale','generation','identity','package','valid'):
   cycle=SimpleNamespace(receiver_state='/state',run='a'*32,live={'process':process},
    receiver_app='/app',receiver_package='/pkg',pin={},lease=Mock(),watch=Mock(),
    intent=Mock(),lookup_cache=Mock(),finished=False)
   cycle.lease.held.return_value=True;cycle.watch.is_open.return_value=True
   cycle.watch.snapshot.return_value={'generation':3 if reason=='generation' else 2}
   cycle.intent.archive_recovered.return_value=True
   value=copy.deepcopy(receipt)
   if reason=='identity':value['process']['pid']=124
   with patch('receiver_result_reader.read_receipt',return_value=value), \
        patch('receiver_process_observer.observed_process_ended',return_value=reason!='live'), \
        patch('receiver_package_attestation.package_matches',return_value=reason!='package'), \
        patch('recovery_records.archive_uncertain',return_value=True) as archive, \
        patch('receiver_handoff_archive.archive',return_value=True):
    result=accept_recovery(cycle,clock=lambda:106 if reason=='stale' else 101)
    if reason=='valid':
     self.assertTrue(result['oldReceiverExitVerified']);self.assertTrue(cycle.finished)
     self.assertTrue(archive.call_args.kwargs['proof']())
     cycle.lookup_cache.remember.assert_called_once()
    else:
     self.assertIsNone(result,reason);archive.assert_not_called()

class MissingTargetTests(unittest.TestCase):
 setup_path=OwnedRecoveryTests.setup_path
 def fixture_missing(self):
  k=self.setup_path()
  prior=wait_and_recover(**k)
  k.pop('initial_generation');k.pop('lookup')
  k['recover'].reset_mock();k['records_factory'].reset_mock()
  k['prior_recovery']=prior
  k['result']={'status':'attention','diagnostic':'target-not-present',
   'setupStage':'open-target','resourcesClosed':True}
  return k

 def test_new_zero_proof_without_reconnecting_and_no_mark_idle(self):
  k=self.fixture_missing();k['watch'].mark_idle.reset_mock()
  out=recover_missing_target(**k)
  self.assertEqual(validate_receipt(out)['generation'],2)
  k['recover'].assert_called_once()
  self.assertEqual(k['recover'].call_args.kwargs['gatt_lookup_reply'],REPLY)
  self.assertTrue(k['recover'].call_args.kwargs['session_closed']())
  k['watch'].mark_idle.assert_not_called();k['stop'].wait.assert_not_called()

 def test_bad_stage_cleanup_old_lookup_or_owner_cannot_start_recovery(self):
  for reason in ('stage','diagnostic','resources','cleanup','stale','future','generation','stop','lease','watch','feature','prior'):
   k=self.fixture_missing()
   if reason=='stage':k['result']['setupStage']='session'
   if reason=='diagnostic':k['result']['diagnostic']='target-inventory-incomplete'
   if reason=='resources':k['result']['resourcesClosed']=False
   if reason=='cleanup':k['result']={'status':'attention','reason':'resource-close-unverified','errors':['target-close-error'],'sessionResult':k['result']}
   if reason=='stale':k['clock']=lambda:106
   if reason=='future':k['clock']=lambda:99
   if reason=='generation':k['watch'].snapshot.return_value={'generation':3}
   if reason=='stop':k['stop'].is_set.return_value=True
   if reason=='lease':k['lease'].held.return_value=False
   if reason=='watch':k['watch'].is_open.return_value=False
   if reason=='feature':k['external_feature_guard']=lambda:False
   if reason=='prior':k['prior_recovery']['sensorStopVerified']=False
   self.assertNotIn('localRecovery',recover_missing_target(**k),reason)
   k['recover'].assert_not_called()

 def test_old_zero_cannot_mask_failed_new_proof_or_changed_connection(self):
  for reason in ('error','nonzero','closure','generation','record'):
   k=self.fixture_missing()
   if reason=='error':k['recover'].side_effect=RuntimeError('read failed')
   if reason=='nonzero':k['recover'].return_value={'status':'attention'}
   if reason=='closure':k['recover'].return_value={'status':'recovered','modeZeroVerified':True,'priorSessionClosedVerified':False}
   if reason=='generation':k['watch'].snapshot.side_effect=[{'generation':2},{'generation':3}]
   if reason=='record':k['records_factory'].return_value.side_effect=[True,False]
   self.assertNotIn('localRecovery',recover_missing_target(**k),reason)


if __name__=='__main__':unittest.main()
