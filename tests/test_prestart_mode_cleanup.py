import unittest
from types import SimpleNamespace
from unittest.mock import patch
import borrowed_session_coordinator as c
from borrowed_session_runner import run_once


class Tests(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.mode=0;self.reads=0
        outer=self
        class Reader:
            reference_verified=False
            selector_attempts=0
            closed=False
            def __init__(self,*args,**kwargs):outer.reader=self
            def bind_borrowed(self,**kwargs):pass
            def read(self,generation):
                outer.reads+=1
                if outer.reads>2:raise RuntimeError('mode request budget consumed')
                self.selector_attempts=1;self.reference_verified=True
                outer.calls.append('activation-read')
                return {'mode':outer.mode}
        for name,value in (
            ('BorrowedModeReader',Reader),
            ('BoundConnectedView',lambda *a:SimpleNamespace(generation=1,snapshot=lambda:{})),
            ('BorrowedControlGuard',lambda **kw:lambda:True)):
            p=patch.object(c,name,value);p.start();self.addCleanup(p.stop)
        view=SimpleNamespace(generation=1,client_id='4',discover=lambda:'4',
                             close=lambda:self.calls.append('close'))
        def write(mode):self.mode=mode;self.calls.append(('write',mode));return True
        def stop_read(reader):
            self.assertTrue(reader.reference_verified)
            self.calls.append('independent-stop-read');return self.mode
        self.session,_=c.create_session(watch=object(),view=view,lease=object(),paired=True,
            call=lambda *a:None,write_mode=write,read_stop_mode=stop_read,
            external_feature_guard=lambda:True,record=lambda row:True,
            clock=lambda:1,reader_clock=lambda:1)

    def test_cancel_before_activation_establishes_reference_without_mode_write(self):
        def cancel(session):raise RuntimeError('screen off')
        result=run_once(lambda:self.session,lambda s:self.fail(),before_start=cancel)
        self.assertTrue(result['sensorStopVerified'])
        self.assertEqual(self.calls,['activation-read','independent-stop-read','close'])

    def test_failed_reference_is_not_retried_or_claimed_stopped(self):
        self.reader.selector_attempts=1;self.reader.closed=True
        with self.assertRaises(RuntimeError):self.session.stop()
        self.assertEqual(self.calls,['close'])
        self.assertEqual(self.session.state,'attention')

    def test_normal_activation_keeps_two_read_budget(self):
        result=run_once(lambda:self.session,lambda s:{'status':'complete'})
        self.assertEqual(result['status'],'complete')
        self.assertEqual(self.reads,2)
        self.assertEqual([v for v in self.calls if isinstance(v,tuple)],[('write',1),('write',0)])

    def test_existing_nonzero_mode_is_not_disabled_by_prestart_cleanup(self):
        self.mode=1
        result=self.session.stop()
        self.assertFalse(result['modeZeroVerified'])
        self.assertEqual(result['status'],'attention')
        self.assertFalse(any(isinstance(v,tuple) for v in self.calls))
