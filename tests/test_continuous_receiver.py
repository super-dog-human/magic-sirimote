import json,os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
from borrowed_runtime_journal import BorrowedRuntimeJournal,inspect_journal
from borrowed_gatt_view import TARGET,ADAPTER
from postconnect_receiver_app import run_once

RUN='a'*32
REPLY={'returnValue':True,'address':TARGET,'adapterAddress':ADAPTER,'clientId':'5'}

class ContinuousJournalTests(unittest.TestCase):
 def session(self,j,g):
  for stage in ('f0af-intent','f0af-ack','gatt-lookup-intent'):
   j({'stage':stage,'generation':g})
  j({'stage':'borrowed-view-obtained','generation':g,'clientIdSha256':'b'*64,'ownership':'unproven'})
  for stage in ('notification-config-intent','notification-enabled','sensor-enable-intent','sensor-enable-ack','sensor-stop-intent'):
   j({'stage':stage})

 def test_many_reconnects_preserve_order_and_latest_generation(self):
  with tempfile.TemporaryDirectory() as d:
   os.chmod(d,0o770);uid=os.getuid();gid=os.getgid()
   j=BorrowedRuntimeJournal(d,RUN,state_uid=uid,group=gid)
   try:
    for g in range(1,16):
     if g>1:j({'stage':'session-recovered','generation':g})
     self.session(j,g)
    self.assertGreater(j.sequence,100)
    evidence=inspect_journal(d,RUN,owner_uid=uid,state_uid=uid,group=gid)
    self.assertEqual(evidence['generation'],15);self.assertEqual(evidence['status'],'sensor-state-unknown')
    j({'stage':'sensor-zero-confirmed'})
    self.assertEqual(inspect_journal(d,RUN,owner_uid=uid,state_uid=uid,group=gid)['status'],'zero-recorded-live-recheck-required')
    # Earlier evidence is checked as well, not just the final zero marker.
    p=Path(d)/('borrowed-'+RUN+'-11.json');v=json.loads(p.read_text());v['generation']=1;p.write_text(json.dumps(v));os.chmod(p,0o640)
    with self.assertRaises(RuntimeError):inspect_journal(d,RUN,owner_uid=uid,state_uid=uid,group=gid)
   finally:j.close()

 def test_reconnect_requires_new_generation_and_cannot_skip_zero_marker(self):
  with tempfile.TemporaryDirectory() as d:
   os.chmod(d,0o770);j=BorrowedRuntimeJournal(d,RUN,state_uid=os.getuid(),group=os.getgid())
   try:
    self.session(j,1)
    with self.assertRaises(RuntimeError):j({'stage':'f0af-intent','generation':2})
    with self.assertRaises(ValueError):j({'stage':'session-recovered','generation':1})
    j({'stage':'session-recovered','generation':2})
    j({'stage':'f0af-intent','generation':2});j({'stage':'f0af-ack','generation':2})
    self.assertEqual(inspect_journal(d,RUN,owner_uid=os.getuid(),state_uid=os.getuid(),group=os.getgid())['status'],'input-start-recorded-sensor-not-attempted')
   finally:j.close()

class ContinuousReceiverTests(unittest.TestCase):
 def test_same_worker_resources_reused_but_old_input_grant_not_reused(self):
  pump=Mock();pump.tracker=pump;pump.snapshot.return_value={'generation':1};pump.stop.return_value=True;pump.mark_active.return_value=True
  lease=Mock();lease.held.return_value=True;journal=Mock(return_value=True);journal.journal.sequence=9;journal.archive_completed.return_value=True
  stop=threading.Event();first=Mock(return_value=True);seen=[]
  def session(**kw):
   seen.append(kw)
   if len(seen)==1:return {'status':'attention','sensorStopVerified':False}
   return {'status':'complete','sensorStopVerified':True}
  def recover(**kw):
   if kw['result']['status']=='complete':return kw['result']
   pump.snapshot.return_value={'generation':2}
   return {**kw['result'],'sensorStopVerified':True,'journalArchived':False,
    'localRecovery':{'generation':2,'observedAt':100,'gattLookupReply':REPLY}}
  factory=Mock(return_value=lease);journals=Mock(return_value=journal)
  result=run_once(state_path='/state',run=RUN,external_feature_guard=lambda:True,duration=None,
   stop_event=stop,clock=lambda:100,pump_factory=lambda:pump,lease_factory=factory,journal_factory=journals,
   session_runner=session,identity_check=lambda:None,input_handoff_check=first,gatt_lookup_reply=REPLY,idle_recovery=recover)
  self.assertEqual(result['status'],'complete');self.assertTrue(result['journalArchived'])
  self.assertEqual(len(seen),2);self.assertIs(seen[0]['input_handoff_check'],first)
  self.assertNotIn('input_handoff_check',seen[1]);self.assertEqual(seen[1]['gatt_lookup_reply'],REPLY)
  self.assertIs(seen[0]['lease'],seen[1]['lease']);self.assertIs(seen[0]['record'],seen[1]['record'])
  journal.assert_called_once_with({'stage':'session-recovered','generation':2})
  factory.assert_called_once();journals.assert_called_once();lease.close.assert_called_once();pump.stop.assert_called_once()

 def test_missing_node_after_resume_exits_with_new_zero_receipt(self):
  for recovered in (True,False):
   pump=Mock();pump.tracker=pump;pump.snapshot.return_value={'generation':1};pump.stop.return_value=True;pump.mark_active.return_value=True
   lease=Mock();lease.held.return_value=True
   journal=Mock(return_value=True);journal.journal.sequence=9
   missing={'status':'attention','diagnostic':'target-not-present','setupStage':'open-target','resourcesClosed':True}
   session=Mock(side_effect=[{'status':'attention'},missing])
   prior={'status':'attention','sensorStopVerified':True,'journalArchived':False,
    'localRecovery':{'generation':2,'observedAt':100,'gattLookupReply':REPLY}}
   def idle(**kw):
    pump.snapshot.return_value={'generation':2}
    return prior
   idle=Mock(side_effect=idle)
   cleanup={**missing,**prior} if recovered else missing
   with patch('owned_idle_recovery.recover_missing_target',return_value=cleanup) as local:
    result=run_once(state_path='/state',run=RUN,external_feature_guard=lambda:True,duration=None,
     clock=lambda:100,pump_factory=lambda:pump,lease_factory=lambda _:lease,journal_factory=lambda *_:journal,
     session_runner=session,identity_check=lambda:None,idle_recovery=idle)
   self.assertEqual(session.call_count,2);idle.assert_called_once();local.assert_called_once()
   self.assertIs(local.call_args.kwargs['prior_recovery'],prior)
   self.assertEqual('localRecovery' in result,recovered)
   pump.stop.assert_called_once();lease.close.assert_called_once();journal.close.assert_called_once()
   journal.archive_completed.assert_not_called()

if __name__=='__main__':unittest.main()
