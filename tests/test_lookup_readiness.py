import sys,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
from prelaunch_handoff_runtime import lookup_before_input
from borrowed_gatt_view import TARGET,ADAPTER
from pumping_luna_client import LunaChildStopError

REPLY={'returnValue':True,'address':TARGET,'adapterAddress':ADAPTER,'clientId':'5'}

class Tests(unittest.TestCase):
 def fixture(self):
  now=[0.];generation=[2];events=[];watch=Mock();watch.is_open.return_value=True
  watch.snapshot.side_effect=lambda:{'generation':generation[0],'observedAt':now[0]}
  lease=Mock();lease.held.return_value=True
  request=Mock(return_value=REPLY)
  def wait(seconds):now[0]+=seconds
  kw=dict(watch=watch,lease=lease,record=lambda s,v:events.append((s,v,now[0])),
          requester_factory=lambda **_:request,clock=lambda:now[0],wait=wait)
  return kw,now,generation,events,request
 def test_verified_read_and_newer_observation_replace_half_second_wait(self):
  k,now,gen,events,request=self.fixture();observed=[]
  def verify(reply,**kwargs):
   self.assertEqual(request.call_count,1);self.assertEqual(reply,REPLY)
   observed.append(now[0]);return REPLY,gen[0]
  self.assertEqual(lookup_before_input(**k,verify_ready=verify),(REPLY,2))
  self.assertGreater(now[0],observed[0]);self.assertLess(now[0],.5)
  self.assertEqual(events[-1][1]['source'],'verified-read')
 def test_failed_read_uses_original_time_requirement_once(self):
  k,now,gen,events,request=self.fixture();verify=Mock(return_value=None)
  self.assertEqual(lookup_before_input(**k,verify_ready=verify),(REPLY,2))
  verify.assert_called_once();self.assertGreaterEqual(now[0],.6)
  self.assertNotIn('source',events[-1][1])
 def test_generation_change_after_read_invalidates_fast_proof(self):
  k,now,gen,events,request=self.fixture();verify=Mock(return_value=(REPLY,2))
  def wait(seconds):
   now[0]+=seconds
   if now[0]>=.1:gen[0]=3
  k['wait']=wait
  self.assertEqual(lookup_before_input(**k,verify_ready=verify),(REPLY,3))
  self.assertGreaterEqual(now[0],.6);self.assertNotIn('source',events[-1][1]);verify.assert_called_once()
 def test_disconnect_after_read_invalidates_fast_proof_even_same_generation(self):
  k,now,gen,events,request=self.fixture()
  k['watch'].snapshot.side_effect=lambda:None if .09<now[0]<.19 else {'generation':2,'observedAt':now[0]}
  self.assertEqual(lookup_before_input(**k,verify_ready=Mock(return_value=(REPLY,2))),(REPLY,2))
  self.assertGreaterEqual(now[0],.7);self.assertNotIn('source',events[-1][1])
 def test_stale_observation_after_successful_read_cannot_advance(self):
  k,now,gen,events,request=self.fixture()
  k['watch'].snapshot.side_effect=lambda:{'generation':2,'observedAt':min(now[0],.05)}
  with self.assertRaisesRegex(RuntimeError,'did not stabilize'):
   lookup_before_input(**k,verify_ready=Mock(return_value=(REPLY,2)))
  self.assertFalse(any(e[0]=='stable' for e in events))
 def test_unknown_child_stop_is_not_swallowed_as_optional_read_failure(self):
  k,now,gen,events,request=self.fixture()
  with self.assertRaises(LunaChildStopError):
   lookup_before_input(**k,verify_ready=Mock(side_effect=LunaChildStopError('stop unknown')))
  self.assertFalse(any(e[0]=='stable' for e in events))
 def test_read_generation_loss_allows_normal_observation_but_owner_loss_aborts(self):
  for owner_lost in (False,True):
   k,now,gen,events,request=self.fixture()
   def verify(*a,**kw):
    gen[0]=3
    if owner_lost:k['lease'].held.return_value=False
    raise RuntimeError('reconnect identity control lost')
   if owner_lost:
    with self.assertRaisesRegex(RuntimeError,'watch unavailable'):lookup_before_input(**k,verify_ready=verify)
   else:
    self.assertEqual(lookup_before_input(**k,verify_ready=verify),(REPLY,3));self.assertGreaterEqual(now[0],.6)

if __name__=='__main__':unittest.main()
