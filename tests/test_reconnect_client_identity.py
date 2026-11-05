import copy,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
root=Path(__file__).resolve().parents[1]/'src'
sys.path[:0]=[str(root/'runtime'),str(root/'native')]
from borrowed_gatt_requester import revalidate_client,ReconnectIdentityRead
from borrowed_gatt_view import TARGET,ADAPTER
from battery_status import SERVICE,LEVEL
from pumping_luna_client import LunaCallError,LunaChildStopError,native_request_scope,PumpingLunaClient
from lifecycle import REMOTE
import test_owned_idle_recovery as recovery_fixture
REPLY=recovery_fixture.REPLY
from owned_idle_recovery import wait_and_recover

RESPONSE={'returnValue':True,'address':TARGET,'adapterAddress':ADAPTER,'service':SERVICE,
          'values':[{'characteristic':LEVEL,'value':{'bytes':[75]}}]}

class IdentityTests(unittest.TestCase):
 def fixture(self):
  watch=Mock();watch.is_open.return_value=True;watch.snapshot.return_value={'generation':2,'observedAt':10.}
  lease=Mock();lease.held.return_value=True;request=Mock(return_value=copy.deepcopy(RESPONSE))
  factory=Mock(return_value=request)
  return dict(watch=watch,lease=lease,requester_factory=factory,clock=lambda:10.),request
 def test_fresh_read_revalidates_hint_without_connect_or_mode_command(self):
  k,request=self.fixture();value=revalidate_client(REPLY,**k)
  self.assertEqual(value,(REPLY,2));request.assert_called_once_with('gatt/readCharacteristicValues',{'clientId':'5','service':SERVICE,'characteristics':[LEVEL]},timeout=1)
 def test_bad_or_stale_hint_never_sends_read(self):
  for reason in ('id','remote','generation','stale','owner'):
   k,request=self.fixture();reply=copy.deepcopy(REPLY)
   if reason=='id':reply['clientId']='0'
   if reason=='remote':reply['address']='00:00:00:00:00:00'
   if reason=='generation':k['watch'].snapshot.return_value=None
   if reason=='stale':k['clock']=lambda:14.
   if reason=='owner':k['lease'].held.return_value=False
   self.assertIsNone(revalidate_client(reply,**k));request.assert_not_called()
 def test_wrong_target_adapter_service_or_ambiguous_value_cannot_refresh_hint(self):
  for change in ({'returnValue':False},{'address':'00:00:00:00:00:00'}, {'adapterAddress':'00:00:00:00:00:00'},
                 {'service':'wrong'},{'clientId':'9'},{'values':[]},{'values':RESPONSE['values']*2}):
   k,request=self.fixture();request.return_value={**copy.deepcopy(RESPONSE),**change}
   self.assertIsNone(revalidate_client(REPLY,**k))
 def test_generation_change_during_read_aborts_instead_of_returning_hint(self):
  k,request=self.fixture()
  def read(*a,**kw):
   k['watch'].snapshot.return_value={'generation':3,'observedAt':10.};return RESPONSE
  request.side_effect=read
  with self.assertRaisesRegex(RuntimeError,'control lost'):revalidate_client(REPLY,**k)
 def test_stopped_read_timeout_can_fall_back_but_unknown_child_stop_cannot(self):
  for error in (LunaCallError('timed out'),LunaChildStopError('stop unconfirmed')):
   k,request=self.fixture();request.side_effect=error
   if isinstance(error,LunaChildStopError):
    with self.assertRaises(LunaChildStopError):revalidate_client(REPLY,**k)
   else:self.assertIsNone(revalidate_client(REPLY,**k))
 def test_diagnostics_record_bounded_reason_not_raw_response(self):
  k,request=self.fixture();record=Mock();request.return_value={'returnValue':False,'errorCode':106,'errorText':'private value'}
  self.assertIsNone(revalidate_client(REPLY,record=record,**k))
  self.assertEqual(record.call_args.args,('revalidation',{'outcome':'response-not-validated','elapsedMs':0,'replyAccepted':False,'errorCode':106}))
  request.side_effect=LunaCallError('Native application identity unverified')
  self.assertIsNone(revalidate_client(REPLY,record=record,**k));self.assertEqual(record.call_args.args[1]['reason'],'app-identity')
 def test_probe_policy_allows_only_one_exact_battery_read(self):
  args={'clientId':'5','service':SERVICE,'characteristics':[LEVEL]}
  c=ReconnectIdentityRead('5',pump=lambda:None,guard=lambda:True)
  for method,params,timeout in (('gatt/connect',args,1),('gatt/readCharacteristicValues',{**args,'clientId':'6'},1),('gatt/readCharacteristicValues',args,2)):
   with self.assertRaises(ValueError):c._validate_request(method,params,timeout)
  self.assertEqual(c._validate_request('gatt/readCharacteristicValues',args,1),('gatt/readCharacteristicValues',1,False))
  with self.assertRaises(LunaCallError):c._validate_request('gatt/readCharacteristicValues',args,1)
 def test_probe_does_not_consume_or_poison_shared_command_handle(self):
  transport=Mock();transport._request.return_value={'returnValue':True}
  children=[]
  def spawn(argv,**kw):
   child=subprocess.Popen([sys.executable,'-c','print(\'{"returnValue":false,"errorCode":106}\',flush=True)'],**kw)
   children.append(child);return child
  with patch('native_app_identity.verify_self',return_value=True),native_request_scope(factory=lambda:transport) as scope:
   c=ReconnectIdentityRead('5',pump=lambda:None,guard=lambda:True,spawn=spawn,get_euid=lambda:1000)
   self.assertFalse(c('gatt/readCharacteristicValues',{'clientId':'5','service':SERVICE,'characteristics':[LEVEL]},timeout=1)['returnValue'])
   self.assertIsNone(scope.client);self.assertFalse(scope.failed);self.assertIsNotNone(children[0].poll())
   ordinary=PumpingLunaClient(native_app=True,pump=lambda:None,guard=lambda:True,get_euid=lambda:1000)
   self.assertTrue(ordinary('hid/getStatus',{'address':REMOTE},timeout=1)['returnValue'])
  transport._request.assert_called_once();transport.close.assert_called_once()

class RecoveryTests(unittest.TestCase):
 def test_recovery_verifies_readiness_only_after_lookup_and_retains_zero_check(self):
  k=recovery_fixture.OwnedRecoveryTests().setup_path()
  out=wait_and_recover(**k);self.assertTrue(out['sensorStopVerified'])
  k['lookup'].assert_called_once();k['recover'].assert_called_once()
  self.assertIs(k['lookup'].call_args.kwargs['verify_ready'],revalidate_client)
  self.assertEqual(k['recover'].call_args.kwargs['gatt_lookup_reply'],REPLY)

if __name__=='__main__':unittest.main()
