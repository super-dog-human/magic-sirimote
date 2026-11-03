"""Reset ordering, partial outcomes, target scoping and recovery, without hardware."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/integrated'),str(ROOT/'src/native'),str(ROOT/'src/runtime')]
import settings
import reset_remote as reset
import reset_state
from reset_screen import ResetScreen
from native_manager import RuntimeSetup

VALUES={'schema':1,'remoteAddress':'aa:bb:cc:dd:ee:10','adapterAddress':'aa:bb:cc:dd:ee:20','remoteName':'TESTREMOTE','gyroEnabled':True,'gyroSensitivity':3}

class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name);settings.save(self.state,VALUES)
        self.value=reset.create(self.state);self.events=[];self.paired=True
    def program(self,*args):
        self.events.append(('delete',args[2],args[3]));return {'status':'submitted','receiptSaved':True}
    def call(self,method,params,timeout):
        self.events.append((method,params))
        if method=='adapter/getStatus':return {'returnValue':True,'adapters':[{'adapterAddress':VALUES['adapterAddress']}]}
        if method=='device/getStatus':return {'returnValue':True,'devices':[
            {'address':VALUES['remoteAddress'],'paired':self.paired}, {'address':'aa:bb:cc:dd:ee:30','paired':True}]}
        if method=='adapter/unpair':
            self.assertEqual(params,{'address':VALUES['remoteAddress']});self.paired=False
            return {'returnValue':True}
        self.fail(method)
    def run_reset(self,**kw):
        return reset.run(self.state,self.value,kw.get('program',self.program),kw.get('call',self.call),kw.get('idle',lambda:None))
    def test_all_slots_before_unpair_and_settings_retained_until_commit(self):
        result=self.run_reset()
        self.assertEqual(result['phase'],'clear');self.assertTrue(result['unpaired'])
        self.assertEqual(self.events[:14],[('delete',b,d) for b,d in reset.SLOTS])
        self.assertEqual(sum(e[0]=='adapter/unpair' for e in self.events),1)
        self.assertEqual(settings.load(self.state),VALUES)
        reset.finish_local(self.state,result)
        self.assertFalse((self.state/'settings.json').exists())
        self.assertFalse((self.state/reset.FILE).exists())
        self.assertTrue((self.state/('reset-archive-'+result['id'])/'settings.json').exists())
    def test_hold_removed_before_press_and_old_ir_history_not_used_after_reset(self):
        for button in (1,2,4,8,16,32,128):
            self.assertLess(reset.SLOTS.index((button,2)),reset.SLOTS.index((button,0)))
        path=self.state/'ir-operation-old.json'
        path.write_text(json.dumps({'button':1,'delay':2,'status':'submitted','action':'set','code':'08'}))
        result=self.run_reset();reset.finish_local(self.state,result)
        from tv_assignments import ir_knowledge
        self.assertEqual(ir_knowledge(self.state,{}),{})
        self.assertTrue((self.state/('reset-archive-'+result['id'])/path.name).exists())
    def test_failed_ir_stops_before_unpair_and_resumes_only_remaining_slots(self):
        program=Mock(side_effect=[{'status':'submitted','receiptSaved':True},{'status':'uncertain','receiptSaved':True,'message':'No reply'}])
        result=self.run_reset(program=program)
        self.assertEqual(result['phase'],'failed');self.assertEqual(len(result['completed']),1)
        self.assertFalse(self.events)
        self.value=reset.load(self.state);self.events=[]
        result=self.run_reset()
        self.assertEqual(self.events[0],('delete',1,0));self.assertTrue(result['unpaired'])
    def test_missing_receipt_not_counted_or_unpaired(self):
        result=self.run_reset(program=lambda *_:{'status':'submitted','receiptSaved':False})
        self.assertEqual(result['phase'],'failed');self.assertEqual(result['completed'],[])
        self.assertFalse(self.events)
    def test_no_ir_when_runtime_not_stopped(self):
        result=self.run_reset(idle=Mock(side_effect=RuntimeError('active')))
        self.assertEqual(result['phase'],'failed');self.assertFalse(self.events)
    def test_changed_saved_identity_stops_before_writing(self):
        settings.save(self.state,{**VALUES,'remoteAddress':'aa:bb:cc:dd:ee:40'})
        self.assertEqual(self.run_reset()['phase'],'failed');self.assertFalse(self.events)
    def test_lost_unpair_reply_keeps_state_and_explicit_retry_checks_registration(self):
        def call(method,params,timeout):
            result=self.call(method,params,timeout)
            if method=='adapter/unpair':return {'returnValue':False}
            return result
        result=self.run_reset(call=call)
        self.assertEqual(result['phase'],'failed');self.assertFalse(result['unpaired'])
        self.assertTrue((self.state/'settings.json').exists())
        self.value=reset.load(self.state);self.events=[]
        self.assertTrue(self.run_reset()['unpaired'])
        self.assertFalse(any(e[0] in ('delete','adapter/unpair') for e in self.events))
    def test_unpair_ack_is_not_enough(self):
        def call(method,params,timeout):
            if method=='adapter/unpair':return {'returnValue':True}
            return self.call(method,params,timeout)
        self.assertEqual(self.run_reset(call=call)['phase'],'failed')
        self.assertFalse(self.value['unpaired'])
    def test_wrong_adapter_and_missing_status_stop(self):
        for reply in ({'returnValue':True,'adapters':[{'adapterAddress':'aa:bb:cc:dd:ee:40'}]}, {'returnValue':True}):
            with self.subTest(reply=reply):
                self.value['completed']=['%02X:%02X'%s for s in reset.SLOTS]
                self.assertEqual(self.run_reset(call=lambda *_:reply)['phase'],'failed')
                self.assertFalse(self.value['unpaired'])
    def test_incomplete_progress_cannot_clear_settings(self):
        with self.assertRaises(RuntimeError):reset.finish_local(self.state,self.value)
        self.assertTrue((self.state/'settings.json').exists())
    def test_corrupt_or_other_owner_progress_not_used(self):
        self.value['completed']=['20:00'];reset_state.write(self.state/reset.FILE,self.value)
        with self.assertRaises(ValueError):reset.load(self.state)
    def test_local_cleanup_can_resume_after_settings_retired(self):
        self.run_reset()
        reset_state.retire(self.state,self.value['id'],['settings.json'])
        reset.finish_local(self.state,self.value)
        self.assertFalse((self.state/reset.FILE).exists())

class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for rel in ('state/sessions','roles/controller/state','roles/receiver/state'):
            path=self.root/rel;path.mkdir(parents=True);(path/'README.txt').write_text('keep')
            (path/'old.json').write_text('{}')
        settings.save(self.root/'state',VALUES)
        reset_state.write(self.root/'state/device-binding.json',VALUES)
        self.params={'resetId':'a'*32,'remoteAddress':VALUES['remoteAddress'],'adapterAddress':VALUES['adapterAddress']}
    def test_retire_roles_binding_and_settings_after_idle_proof(self):
        result=reset_state.reset_service(self.root,self.params,lambda:None)
        self.assertEqual(result['status'],'reset')
        for folder in ('state','roles/controller/state','roles/receiver/state','state/sessions'):
            self.assertTrue((self.root/folder/('reset-archive-'+'a'*32)).is_dir())
        self.assertFalse((self.root/'state/device-binding.json').exists())
        self.assertEqual(reset_state.reset_service(self.root,self.params,lambda:None),result)
    def test_active_or_different_target_preserves_binding(self):
        with self.assertRaises(RuntimeError):reset_state.reset_service(self.root,self.params,Mock(side_effect=RuntimeError('active')))
        with self.assertRaises(ValueError):reset_state.reset_service(self.root,{**self.params,'remoteAddress':'aa:bb:cc:dd:ee:40'},lambda:None)
        self.assertTrue((self.root/'state/device-binding.json').exists())
    def test_interrupted_retirement_resumes_without_overwriting_archives(self):
        original=reset_state.retire;calls=[]
        def retire(*args):
            calls.append(args)
            if len(calls)==2:raise OSError('interrupted')
            return original(*args)
        with patch.object(reset_state,'retire',side_effect=retire),self.assertRaises(OSError):
            reset_state.reset_service(self.root,self.params,lambda:None)
        self.assertEqual(reset_state.reset_service(self.root,self.params,lambda:None)['status'],'reset')
    def test_links_and_traversal_rejected(self):
        d=self.root/'roles/controller/state';(d/'bad').symlink_to(self.root/'state')
        with self.assertRaises(RuntimeError):reset_state.retire(d,'b'*32)
        with self.assertRaises(ValueError):reset_state.retire(d,'c'*32,['../state'])
        self.assertTrue((self.root/'state/settings.json').exists())

class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.state=Path(self.tmp.name)
        settings.save(self.state,VALUES);self.bus=Mock();self.app=RuntimeSetup(self.state,self.bus)
    def test_cancel_and_back_do_not_stop_or_reset(self):
        self.app.choose(9,Mock());screen=self.app.reset
        self.assertEqual(screen.phase,'confirm');screen.handle(('key',461))
        self.assertIsNone(self.app.reset);self.bus.request.assert_not_called()
        self.assertFalse((self.state/reset.FILE).exists())
    def test_only_confirmation_starts_stop_then_wait(self):
        self.app.choose(9,Mock());screen=self.app.reset
        self.bus.request.return_value={'returnValue':True,'status':'stop-requested'}
        screen.choose(1);self.addCleanup(screen.release)
        self.assertTrue(screen.busy);self.assertTrue(self.app.controls_disabled)
        self.assertEqual(self.bus.request.call_args.args[0],'stop')
        self.bus.request.return_value={'returnValue':True,'cleanStop':False,'startup':{'enabled':False}}
        with patch('reset_screen.threading.Thread') as thread:
            screen.tick();thread.assert_not_called()
        screen.handle(('key',13));self.assertTrue(screen.busy)
    def test_timeout_preserves_all_settings_and_offers_resume(self):
        self.app.choose(9,Mock());screen=self.app.reset
        self.bus.request.return_value={'returnValue':True,'status':'stop-requested'}
        screen.choose(1);screen.deadline=0
        self.bus.request.return_value={'returnValue':True,'cleanStop':False,'startup':{'enabled':False}}
        screen.tick();self.assertTrue(screen.can_resume);self.assertFalse(screen.busy)
        self.assertEqual(settings.load(self.state),VALUES)
        with patch.object(self.app,'start_saved') as start:
            screen.choose(0);start.assert_called_once()
        self.assertFalse((self.state/reset.FILE).exists())
    def test_pending_reset_blocks_normal_pairing_on_reopen(self):
        reset.create(self.state);self.app.refresh_pairing()
        self.assertIsInstance(self.app.reset,ResetScreen)
        self.assertIsNone(self.app.pairing)
        with self.assertRaises(RuntimeError):self.app.start_saved()
    def test_finish_requires_service_ack_before_local_clear(self):
        self.app.choose(9,Mock());screen=self.app.reset;screen.value=reset.create(self.state)
        screen.value['completed']=['%02X:%02X'%s for s in reset.SLOTS];screen.value['unpaired']=True
        self.bus.request.return_value={'returnValue':False}
        with self.assertRaises(RuntimeError):screen.finish()
        self.assertTrue((self.state/'settings.json').exists())
        self.bus.request.return_value={'returnValue':True,'status':'reset'}
        with patch.object(self.app,'refresh_pairing') as refresh:screen.finish();refresh.assert_called_once()
        self.assertEqual(self.app.values['remoteAddress'],'');self.assertFalse((self.state/'settings.json').exists())

if __name__=='__main__':unittest.main()
