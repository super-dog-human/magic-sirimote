import sys,time
import unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/runtime'))
from input_start_handoff import InputStartHandoff
from controller_status_watch import ResumingControllerWatch
from borrowed_gatt_view import TARGET,ADAPTER
from preborrow_guard import PreBorrowGuard


def snapshot(generation):
    p={'returnValue':True,'address':TARGET,'adapterAddress':ADAPTER,'connected':True,'connecting':False,'connectRequest':False}
    return {'generation':generation,'sequence':1,'observedAt':time.monotonic(),'hid':dict(p),'gatt':dict(p)}


class ResumingWatchTests(unittest.TestCase):
    def test_connection_observation_never_renews_old_input_grant(self):
        valid=[True];owner=[True];value=[snapshot(1)]
        send=Mock(return_value=True)
        h=InputStartHandoff(run='a'*32,controller={'pid':10,'startTicks':20},generation=1,
            connection_valid=lambda _:valid[0],journal=lambda _:True,send_input_start=send,
            launch_receiver=lambda _:True,connection_snapshot=lambda:value[0],
            connection_observation=lambda:{'open':True,'snapshot':value[0]},owner_valid=lambda:owner[0])
        h.begin()
        request={'run':h.run,'token':h.token,'challenge':'b'*32}
        with self.assertRaises(RuntimeError):h.validate({**request,'operation':'connection'},30)
        self.assertTrue(h.validate(request,30)['inputStarted'])
        valid[0]=False;value[0]=None
        with self.assertRaises(RuntimeError):h.validate(request,30)
        self.assertTrue(h.revoked)
        r=h.validate({**request,'operation':'connection'},30)
        self.assertEqual(r['connection'],{'open':True,'snapshot':None})
        self.assertNotIn('inputStarted',r)
        value[0]=snapshot(2)
        self.assertEqual(h.validate({**request,'operation':'connection'},30)['connection']['snapshot']['generation'],2)
        with self.assertRaises(RuntimeError):h.validate(request,30)
        with self.assertRaises(RuntimeError):h.validate({**request,'operation':'connection'},31)
        owner[0]=False
        with self.assertRaises(RuntimeError):h.validate({**request,'operation':'connection'},30)
        send.assert_called_once()

    def test_idle_notice_requires_bound_worker_and_revokes_grant(self):
        h=InputStartHandoff(run='a'*32,controller={'pid':10,'startTicks':20},generation=1,
            connection_valid=lambda _:True,journal=lambda _:True,send_input_start=lambda:True,
            launch_receiver=lambda _:True,connection_observation=lambda:{'open':True,'snapshot':snapshot(1)},
            owner_valid=lambda:True)
        h.begin();request={'run':h.run,'token':h.token,'challenge':'b'*32}
        with self.assertRaises(RuntimeError):h.validate({**request,'operation':'idle'},30)
        self.assertFalse(h.receiver_idle)
        h.validate(request,30)
        with self.assertRaises(RuntimeError):h.validate({**request,'operation':'idle'},31)
        self.assertFalse(h.receiver_idle)
        h.validate({**request,'operation':'idle'},30)
        self.assertTrue(h.receiver_idle);self.assertTrue(h.revoked)
        with self.assertRaises(RuntimeError):h.validate(request,30)

    def test_idle_and_reconnect_invalidate_old_session_but_keep_readonly_watch(self):
        client=Mock();client.connection.return_value={'open':True,'snapshot':snapshot(1)}
        watch=ResumingControllerWatch(client)
        lease=Mock();lease.held.return_value=True
        guard=PreBorrowGuard(watch,lease,generation=1,external_feature_guard=lambda:True,clock=time.monotonic)
        self.assertTrue(watch._refresh());self.assertTrue(guard())
        client.connection.return_value={'open':True,'snapshot':None}
        self.assertTrue(watch._refresh());self.assertTrue(watch.is_open());self.assertFalse(guard())
        client.connection.return_value={'open':True,'snapshot':snapshot(2)}
        self.assertTrue(watch._refresh());self.assertEqual(watch.snapshot()['generation'],2)
        self.assertFalse(guard())
        self.assertTrue(PreBorrowGuard(watch,lease,generation=2,external_feature_guard=lambda:True,clock=time.monotonic)())
        client.connection.return_value={'open':False,'snapshot':None}
        self.assertFalse(watch._refresh());self.assertFalse(watch.is_open())

    def test_bad_or_stale_owner_replies_close_watch(self):
        for value in (None,{'open':True,'snapshot':{**snapshot(2),'observedAt':time.monotonic()-10}},
                      {'open':True,'snapshot':{**snapshot(2),'hid':{'returnValue':False}}}):
            client=Mock();client.connection.return_value=value
            watch=ResumingControllerWatch(client)
            self.assertFalse(watch._refresh());self.assertFalse(watch.is_open())


if __name__=='__main__':unittest.main()
