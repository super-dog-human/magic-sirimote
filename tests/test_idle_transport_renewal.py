import sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src/runtime')]
from pumping_luna_client import NativeRequestScope,LunaCallError,native_request_scope,renew_failed_native_requests_after_idle
from owned_idle_recovery import wait_and_recover
import test_owned_idle_recovery as recovery_fixture

class Tests(unittest.TestCase):
 def request(self,scope,method='hid/getStatus'):
  return scope.request(method,{},timeout=1,guard=lambda:None,pump=lambda:None)
 def test_failed_call_is_not_replayed_and_new_read_uses_new_handle(self):
  old,new=Mock(),Mock();old._request.side_effect=TimeoutError('lost connection');new._request.return_value={'returnValue':True}
  factory=Mock(side_effect=[old,new]);scope=NativeRequestScope(factory)
  with self.assertRaises(TimeoutError):self.request(scope,'hid/internal/setReport')
  with self.assertRaises(LunaCallError):self.request(scope)
  self.assertTrue(scope.renew_failed());old.close.assert_called_once()
  self.assertTrue(self.request(scope)['returnValue'])
  self.assertEqual(old._request.call_count,1);self.assertEqual(new._request.call_args.args[0],'hid/getStatus')
  scope.close();new.close.assert_called_once()
 def test_healthy_handle_is_not_reopened(self):
  client=Mock();scope=NativeRequestScope(lambda:client);self.request(scope)
  self.assertFalse(scope.renew_failed());self.request(scope)
  client.close.assert_not_called();self.assertEqual(client._request.call_count,2);scope.close()
 def test_failed_close_prevents_new_handle(self):
  client=Mock();client._request.side_effect=TimeoutError();client.close.side_effect=RuntimeError('unregister failed')
  factory=Mock(return_value=client);scope=NativeRequestScope(factory)
  with self.assertRaises(TimeoutError):self.request(scope)
  with self.assertRaises(RuntimeError):scope.renew_failed()
  self.assertTrue(scope.failed)
  with self.assertRaises(LunaCallError):self.request(scope)
  self.assertEqual(factory.call_count,1)
 def test_wrong_thread_and_inflight_renewal_rejected(self):
  scope=NativeRequestScope();scope.failed=True
  for busy,owner in ((True,scope.owner),(False,-1)):
   scope.busy=busy;scope.owner=owner
   with self.assertRaises(LunaCallError):scope.renew_failed()
 def test_scope_exit_closes_replacement_handle(self):
  old,new=Mock(),Mock();old._request.side_effect=RuntimeError('broken')
  with native_request_scope(factory=Mock(side_effect=[old,new])) as scope:
   with self.assertRaises(RuntimeError):self.request(scope)
   self.assertTrue(renew_failed_native_requests_after_idle());self.request(scope)
  old.close.assert_called_once();new.close.assert_called_once()
  self.assertFalse(renew_failed_native_requests_after_idle())
 def test_idle_renewal_precedes_lookup_and_independent_zero(self):
  k=recovery_fixture.OwnedRecoveryTests().setup_path();order=[]
  k['lookup'].side_effect=lambda **kw:(order.append('lookup') or (recovery_fixture.REPLY,2))
  k['recover'].side_effect=lambda **kw:(order.append('zero') or {'status':'recovered','modeZeroVerified':True,'priorSessionClosedVerified':True})
  with patch('pumping_luna_client.renew_failed_native_requests_after_idle',side_effect=lambda:(order.append('renew') or True)):
   self.assertTrue(wait_and_recover(**k)['sensorStopVerified'])
  self.assertEqual(order,['renew','lookup','zero'])
 def test_bad_boundary_or_failed_close_cannot_renew_or_resume(self):
  for reason in ('not-closed','stopping','close-failed'):
   k=recovery_fixture.OwnedRecoveryTests().setup_path()
   if reason=='not-closed':k['result']={'status':'complete'}
   if reason=='stopping':k['stop'].is_set.return_value=True
   with patch('pumping_luna_client.renew_failed_native_requests_after_idle',side_effect=RuntimeError('close-failed')) as renew:
    self.assertNotIn('localRecovery',wait_and_recover(**k))
   if reason!='close-failed':renew.assert_not_called()
   k['lookup'].assert_not_called();k['recover'].assert_not_called()

if __name__=='__main__':unittest.main()
