"""Old receiver requests must not make the settings window close on every open."""
import json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/integrated'),str(ROOT/'src/native'),str(ROOT/'src/runtime')]
import native_manager as manager
import receiver_request

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.state=self.root/'roles/receiver/state';self.state.mkdir(parents=True);self.state.chmod(0o770)
        self.run='a'*32;self.owner=os.getuid();self.group=os.getgid()
        self.record={'run':self.run,'process':{'status':{'Uid':' '.join([str(self.owner)]*4)}}}
    def request(self,expired=False):
        now=int(time.time()*1000)
        receiver_request.write_request(self.state,self.run,now-1000 if expired else now+60000,
                                      now_ms=now-2000 if expired else now,state_uid=self.owner,group=self.group)
    def pending(self):
        read=receiver_request.read_request
        with patch.object(manager,'SERVICE',self.root),patch('runtime_bundle.select'),patch('bundle_boot.receiver_settings'),patch('controller_start_record.read_record',return_value=self.record),patch('receiver_request.read_request',side_effect=lambda directory,**kw:read(directory,**kw,state_uid=self.owner,group=self.group)):
            return manager.pending_worker()
    def test_fresh_attested_request_can_launch(self):
        self.request();self.assertTrue(self.pending())
    def test_absent_request_keeps_settings_open(self):
        self.assertFalse(self.pending())
    def test_expired_request_is_retained_and_never_launches(self):
        self.request(expired=True)
        with self.assertRaisesRegex(RuntimeError,'expired'):self.pending()
        self.assertTrue((self.state/'request.json').exists())
    def test_previous_start_or_result_prevents_replaying_a_run(self):
        self.request()
        for kind in ('start','result'):
            path=self.state/('receiver-'+kind+'-'+self.run+'.json');path.write_text('{}')
            self.assertFalse(self.pending());self.assertTrue(path.exists());path.unlink()
    def test_run_mismatch_is_not_a_new_handoff(self):
        self.request();self.record['run']='b'*32
        with self.assertRaisesRegex(RuntimeError,'run changed'):self.pending()
    def test_recovery_can_follow_normal_result_but_cannot_replay_its_own_result(self):
        (self.state/'recovery-request.json').write_text('{}')
        (self.state/('receiver-result-'+self.run+'.json')).write_text('{}')
        with patch.object(manager,'SERVICE',self.root),patch('runtime_bundle.select'),patch('bundle_boot.receiver_settings',return_value={'remoteAddress':'aa:bb:cc:dd:ee:10','adapterAddress':'aa:bb:cc:dd:ee:20','remoteName':'TEST_REMOTE'}),patch('runtime_device.configure'),patch('receiver_recovery_entry.recovery_controller_record',return_value=self.record),patch('recovery_request.read_recovery_request',return_value={'run':self.run}):
            self.assertTrue(manager.pending_worker())
            (self.state/('receiver-recovery-result-'+self.run+'.json')).write_text('{}')
            self.assertFalse(manager.pending_worker())
    def test_live_controller_attestation_still_required(self):
        self.request()
        with patch.object(manager,'SERVICE',self.root),patch('runtime_bundle.select'),patch('bundle_boot.receiver_settings',side_effect=RuntimeError('no live controller')):
            with self.assertRaisesRegex(RuntimeError,'live controller'):manager.pending_worker()

class VisibleWindowTests(unittest.TestCase):
    def test_worker_exit_does_not_close_reopened_settings_or_lose_drafts(self):
        with tempfile.TemporaryDirectory() as d:
            bus=Mock();bus.request.return_value={'returnValue':True}
            bus.events.side_effect=[[('relaunch',{})],[('close',{})]]
            canvas=Mock();canvas.events.return_value=[]
            worker=Mock();worker.pid=123;worker.poll.return_value=1
            app=manager.RuntimeSetup(Path(d),bus);app.button_drafts={'10:00':'screen-toggle'}
            with patch.object(manager,'STATE',Path(d)),patch.object(manager,'NativeBus') as context,patch.object(manager,'RuntimeSetup',return_value=app),patch.object(manager,'pending_worker',return_value=True),patch.object(manager,'Canvas',return_value=canvas),patch.object(manager.subprocess,'Popen',return_value=worker),patch.object(manager.os,'set_blocking'),patch.object(manager.os,'read',return_value=b''),patch.object(manager.signal,'signal'),patch.object(manager.time,'sleep'),patch.object(app,'refresh_pairing'):
                context.return_value.__enter__.return_value=bus
                manager.main()
            self.assertEqual(bus.events.call_count,2)
            self.assertEqual(app.button_drafts,{'10:00':'screen-toggle'})
            self.assertTrue(app.resume_after_settings)
            self.assertIn('Remote connection ended',app.message)
            worker.terminate.assert_not_called()

    def test_background_window_exits_after_receiver_failure(self):
        with tempfile.TemporaryDirectory() as d:
            bus=Mock();bus.request.return_value={'returnValue':True}
            bus.events.side_effect=[[('relaunch',{})],[('pause',{})]]
            canvas=Mock();canvas.events.return_value=[]
            worker=Mock();worker.pid=123;worker.poll.side_effect=[None,1]
            app=manager.RuntimeSetup(Path(d),bus);app.battery.refresh=Mock()
            with patch.object(manager,'STATE',Path(d)),patch.object(manager,'NativeBus') as context,patch.object(manager,'RuntimeSetup',return_value=app),patch.object(manager,'pending_worker',return_value=True),patch.object(manager,'Canvas',return_value=canvas),patch.object(manager.subprocess,'Popen',return_value=worker),patch.object(manager.os,'set_blocking'),patch.object(manager.os,'read',return_value=b''),patch.object(manager.signal,'signal'),patch.object(manager.time,'sleep'),patch.object(app,'refresh_pairing'):
                context.return_value.__enter__.return_value=bus
                manager.main()
            self.assertEqual(bus.events.call_count,2)
            self.assertFalse(app.resume_after_settings)
            worker.terminate.assert_not_called()
            canvas.close.assert_called_once()

if __name__=='__main__':unittest.main()
