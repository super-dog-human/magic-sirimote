import ctypes as C
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
from pumping_luna_client import PumpingLunaClient, LunaCallError, NativeRequestScope, native_request_scope
from persistent_status_client import PersistentStatusClient, Error
from borrowed_input_start import BorrowedInputStart
from borrowed_gatt_requester import BorrowedGattRequester
from runtime_device import identity


class ScopeTests(unittest.TestCase):
 def test_validated_commands_share_one_handle_and_close_at_scope_exit(self):
  transport=Mock();transport._request.return_value={'returnValue':True};factory=Mock(return_value=transport)
  spawn=Mock(side_effect=AssertionError('subprocess must not be used'))
  with patch('native_app_identity.verify_self',return_value=True),native_request_scope(factory=factory):
   for _ in range(2):
    client=PumpingLunaClient(pump=lambda:None,guard=lambda:True,native_app=True,spawn=spawn,get_euid=lambda:10)
    self.assertEqual(client('hid/getStatus',{'address':identity().remote}),{'returnValue':True})
   transport.close.assert_not_called()
  factory.assert_called_once();self.assertEqual(transport._request.call_count,2);transport.close.assert_called_once();spawn.assert_not_called()

 def test_invalid_parameters_or_native_identity_never_open_a_handle(self):
  for reason in ('method','target','identity','uid'):
   factory=Mock();spawn=Mock()
   with patch('native_app_identity.verify_self',return_value=reason!='identity'),native_request_scope(factory=factory):
    client=PumpingLunaClient(pump=lambda:None,guard=lambda:True,native_app=True,spawn=spawn,get_euid=lambda:0 if reason=='uid' else 10)
    with self.assertRaises((ValueError,LunaCallError)):
     client('adapter/unpair' if reason=='method' else 'hid/getStatus',{'address':'bad' if reason=='target' else identity().remote})
   factory.assert_not_called();spawn.assert_not_called()

 def test_uncertain_write_poisoned_scope_has_no_subprocess_fallback(self):
  transport=Mock();transport._request.side_effect=TimeoutError('unknown');factory=Mock(return_value=transport);spawn=Mock()
  with patch('native_app_identity.verify_self',return_value=True),native_request_scope(factory=factory):
   client=BorrowedInputStart(pump=lambda:None,guard=lambda:True,spawn=spawn,get_euid=lambda:10)
   with self.assertRaises(TimeoutError):client.start()
   # A new policy object also cannot retry through this failed transport.
   other=BorrowedGattRequester(pump=lambda:None,guard=lambda:True,spawn=spawn,get_euid=lambda:10)
   with self.assertRaises(LunaCallError):other('gatt/connect',{'address':identity().remote,'subscribe':False},timeout=12)
  transport._request.assert_called_once();transport.close.assert_called_once();spawn.assert_not_called()

 def test_validated_parameters_detached_before_guard_runs(self):
  params={'address':identity().remote};transport=Mock();transport._request.return_value={}
  def guard():params['address']='different';return True
  with patch('native_app_identity.verify_self',return_value=True),native_request_scope(factory=lambda:transport):
   client=PumpingLunaClient(pump=lambda:None,guard=guard,native_app=True,get_euid=lambda:10)
   client('hid/getStatus',params)
  self.assertEqual(transport._request.call_args.args[1],{'address':identity().remote})

 def test_reentrant_and_cross_thread_use_rejected(self):
  transport=Mock();scope=NativeRequestScope(lambda:transport);errors=[]
  def invoke():
   try:scope.request('hid/getStatus',{},timeout=1,guard=lambda:None,pump=lambda:None)
   except Exception as e:errors.append(type(e))
  thread=threading.Thread(target=invoke);thread.start();thread.join()
  self.assertEqual(errors,[LunaCallError]);transport._request.assert_not_called()
  scope.busy=True
  with self.assertRaises(LunaCallError):invoke_result=scope.request('hid/getStatus',{},timeout=1,guard=lambda:None,pump=lambda:None)
  scope.busy=False;scope.close()


class TransportTests(unittest.TestCase):
 def fixture(self,raw=b'{"returnValue":true}',deliver=True):
  c=object.__new__(PersistentStatusClient);c.owner=threading.get_ident();c.abort=lambda:False
  c.closed=False;c.disconnected=False;c.callbacks=[];c.handle=C.c_void_p(1);c.context=1;c.error=Error()
  c.payload=lambda _:raw;c._check=lambda ok:None if ok else (_ for _ in ()).throw(RuntimeError('call failed'))
  c.cancel=Mock(return_value=True);c.iterate=Mock();c.free_error=Mock();c.init_error=Mock()
  def close():c.closed=True;c.callbacks.clear()
  c.close=Mock(side_effect=close)
  def call(handle,url,params,callback,data,token,error):
   token._obj.value=9
   if deliver:callback(None,None,None)
   return True
  c.call_one=Mock(side_effect=call)
  return c

 def test_direct_request_keeps_original_status_read_policy(self):
  c=self.fixture()
  self.assertTrue(c.read('hid/getStatus')['returnValue'])
  self.assertEqual(json.loads(c.call_one.call_args.args[2]),{'address':identity().remote,'subscribe':False})
  self.assertEqual(c.callbacks,[]);c.cancel.assert_not_called();c.close.assert_not_called()
  with self.assertRaises(ValueError):c.read('hid/internal/setReport')

 def test_timeout_cancels_unregisters_and_keeps_callback_until_close(self):
  c=self.fixture(deliver=False);now=[0.];observed=[]
  def close():observed.append(len(c.callbacks));c.closed=True;c.callbacks.clear()
  c.close.side_effect=close
  def sleep(seconds):now[0]+=seconds
  with patch('persistent_status_client.time.monotonic',side_effect=lambda:now[0]),patch('persistent_status_client.time.sleep',side_effect=sleep):
   with self.assertRaises(TimeoutError):c._request('hid/getStatus',{},timeout=.02)
  c.cancel.assert_called_once();c.close.assert_called_once();self.assertEqual(observed,[1]);self.assertTrue(c.closed)
  with self.assertRaises(RuntimeError):c._request('hid/getStatus',{},timeout=1)
  c.call_one.assert_called_once()

 def test_guard_checks_before_dispatch_and_after_reply(self):
  c=self.fixture();guard=Mock(side_effect=[None,RuntimeError('owner changed')])
  with self.assertRaises(RuntimeError):c._request('hid/getStatus',{},timeout=1,guard=guard)
  self.assertEqual(guard.call_count,2);c.call_one.assert_called_once()
  c=self.fixture();guard=Mock(side_effect=RuntimeError('owner lost'))
  with self.assertRaises(RuntimeError):c._request('hid/getStatus',{},timeout=1,guard=guard)
  c.call_one.assert_not_called();c.close.assert_called_once()

 def test_slow_guard_prevents_dispatch_after_deadline(self):
  c=self.fixture();now=[0.]
  def guard():now[0]=2.
  with patch('persistent_status_client.time.monotonic',side_effect=lambda:now[0]):
   with self.assertRaises(TimeoutError):c._request('hid/getStatus',{},timeout=1,guard=guard)
  c.call_one.assert_not_called()

 def test_invalid_reply_does_not_become_success(self):
  for raw in (b'[]',b'{',b'x'*65537):
   c=self.fixture(raw)
   with self.assertRaises(RuntimeError):c._request('hid/getStatus',{},timeout=1)

 def test_explicit_navigation_pump_runs_between_reply_checks(self):
  c=self.fixture(deliver=False);now=[0.];calls=[]
  class Pump:
   poll_interval=.005
   def __call__(self):calls.append(now[0])
  guard=Mock()
  with patch('persistent_status_client.time.monotonic',side_effect=lambda:now[0]),patch('persistent_status_client.time.sleep',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)):
   with self.assertRaises(TimeoutError):c._request('hid/getStatus',{},timeout=.031,pump=Pump(),guard=guard)
  self.assertGreaterEqual(len(calls),6)
  self.assertEqual(guard.call_count,1)
  c.call_one.assert_called_once();c.cancel.assert_called_once()

 def test_invalid_pump_rate_never_dispatches(self):
  for interval in (0,.001,.2,float('nan'),True):
   c=self.fixture();pump=Mock();pump.poll_interval=interval
   with self.assertRaises(ValueError):c._request('hid/getStatus',{},timeout=1,pump=pump)
   c.call_one.assert_not_called()


if __name__=='__main__':unittest.main()
