"""Independent stop proof must never infer idle from missing observations."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('private_idle',Path(__file__).resolve().parents[1]/'tools/installer/private_idle.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class IdleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.service=self.root/'service';self.apps=self.root/'apps';self.proc=self.root/'proc';self.proc.mkdir()
        for rel in ('state/startup-private','roles/controller/state','roles/receiver/state'):
            (self.service/rel).mkdir(parents=True)
        for name,value in (('SERVICE_ROOT',self.service),('APPLICATIONS',self.apps)):
            p=patch.object(m,name,value);p.start();self.addCleanup(p.stop)
        self.startup=self.service/'state/startup-private/startup.json'
        self.startup.write_text(json.dumps({'schema':1,'token':'a'*48,'phase':'ready','enabled':False}))
    def enable(self):
        value=json.loads(self.startup.read_text())
        value.update(enabled=True,activityId=42,power={'cycle':7},lastOutcome='manual-start')
        self.startup.write_text(json.dumps(value));return value

    def test_only_enabled_flag_changes_and_owner_is_preserved(self):
        original=self.enable();before=self.startup.stat()
        settings=self.service/'state/settings.json';settings.write_text('keep settings')
        pending=self.service/'state/reset-pending.json';pending.write_text('keep reset progress')
        with patch.object(m,'active_processes',return_value=[]):
            self.assertTrue(m.disable_idle_startup())
            self.assertFalse(m.disable_idle_startup())
        self.assertEqual(json.loads(self.startup.read_text()),{**original,'enabled':False})
        after=self.startup.stat()
        self.assertEqual((after.st_uid,after.st_gid),(before.st_uid,before.st_gid))
        self.assertEqual(after.st_mode & 0o777,0o600)
        self.assertEqual(settings.read_text(),'keep settings');self.assertEqual(pending.read_text(),'keep reset progress')
        self.assertEqual(list(self.startup.parent.glob('.maintenance-*')),[])

    def test_active_process_prevents_any_startup_write(self):
        self.enable();before=self.startup.read_bytes()
        with patch.object(m,'active_processes',return_value=[{'pid':123,'role':'controller'}]):
            with self.assertRaisesRegex(RuntimeError,'not fully stopped'):m.disable_idle_startup()
        self.assertEqual(self.startup.read_bytes(),before)

    def test_cleanup_marker_prevents_startup_write(self):
        self.enable();before=self.startup.read_bytes()
        (self.service/'roles/receiver/state/borrowed-active').write_text('pending')
        with patch.object(m,'active_processes',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'not fully stopped'):m.disable_idle_startup()
        self.assertEqual(self.startup.read_bytes(),before)

    def test_process_appearing_before_commit_leaves_original_intact(self):
        self.enable();before=self.startup.read_bytes()
        with patch.object(m,'active_processes',side_effect=[[],[{'pid':123,'role':'ui'}]]):
            with self.assertRaises(RuntimeError):m.disable_idle_startup()
        self.assertEqual(self.startup.read_bytes(),before)
        self.assertEqual(list(self.startup.parent.glob('.maintenance-*')),[])

    def test_concurrent_startup_edit_is_not_overwritten(self):
        self.enable();changed=[]
        def processes():
            if changed:
                value=json.loads(self.startup.read_text());value['activityId']=99
                self.startup.write_text(json.dumps(value))
            changed.append(True);return []
        with patch.object(m,'active_processes',side_effect=processes):
            with self.assertRaisesRegex(RuntimeError,'not overwritten'):m.disable_idle_startup()
        value=json.loads(self.startup.read_text());self.assertTrue(value['enabled']);self.assertEqual(value['activityId'],99)
        self.assertEqual(list(self.startup.parent.glob('.maintenance-*')),[])

    def test_failed_atomic_replace_retains_original_and_removes_temporary(self):
        self.enable();before=self.startup.read_bytes()
        with patch.object(m,'active_processes',return_value=[]),patch.object(m.os,'replace',side_effect=OSError('write failed')):
            with self.assertRaises(OSError):m.disable_idle_startup()
        self.assertEqual(self.startup.read_bytes(),before)
        self.assertEqual(list(self.startup.parent.glob('.maintenance-*')),[])

    def test_disable_is_not_accepted_as_stop_proof(self):
        with patch.object(m,'disable_idle_startup',return_value=True),patch.object(m,'verify_idle',side_effect=RuntimeError('new receiver')):
            with self.assertRaisesRegex(RuntimeError,'new receiver'):m.prepare_idle()

    def shared_directory_context(self):
        from contextlib import ExitStack
        paths=m.shared_state_paths()
        for path in paths:path.mkdir(parents=True,exist_ok=True);path.chmod(0o777)
        original_stat=os.fstat;original_lstat=Path.lstat
        def stamp(info):
            if not __import__('stat').S_ISDIR(info.st_mode):return info
            data=list(info);data[4]=5999;data[5]=5000;return os.stat_result(data)
        stack=ExitStack()
        stack.enter_context(patch.object(m.os,'fstat',side_effect=lambda fd:stamp(original_stat(fd))))
        stack.enter_context(patch.object(Path,'lstat',lambda path,*a,**kw:stamp(original_lstat(path,*a,**kw))))
        stack.enter_context(patch.object(m,'verify_idle',return_value={'idle':True}))
        stack.enter_context(patch.object(m,'snapshot',return_value={'startupDisabled':True,'processes':[],'cleanupMarkers':[]}))
        return stack,paths

    def test_shared_directories_normalize_without_touching_records(self):
        stack,paths=self.shared_directory_context()
        saved=paths[1]/'settings.json';saved.write_text('preserved');saved.chmod(0o640)
        before=saved.stat()
        with stack:
            report=m.normalize_shared_state()
            self.assertEqual(len(report),5)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o770 for p in paths))
        self.assertEqual(saved.read_text(),'preserved')
        self.assertEqual(saved.stat().st_mode,before.st_mode)
        self.assertEqual(saved.stat().st_ino,before.st_ino)

    def test_invalid_shared_directory_stops_before_any_chmod(self):
        stack,paths=self.shared_directory_context();paths[-1].chmod(0o755)
        with stack,self.assertRaisesRegex(RuntimeError,'owner/mode'):m.normalize_shared_state()
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o777 for p in paths[:-1]))

    def test_symlink_shared_directory_is_rejected(self):
        stack,paths=self.shared_directory_context();paths[-1].rmdir();paths[-1].symlink_to(paths[0])
        with stack,self.assertRaises(RuntimeError):m.normalize_shared_state()
        self.assertEqual(paths[0].stat().st_mode & 0o777,0o777)

    def test_runtime_appearing_during_shared_validation_blocks_chmod(self):
        stack,paths=self.shared_directory_context()
        with stack,patch.object(m,'snapshot',return_value={'startupDisabled':True,'processes':[{'pid':5}],'cleanupMarkers':[]}):
            with self.assertRaisesRegex(RuntimeError,'Runtime changed'):m.normalize_shared_state()
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o777 for p in paths))

    def test_valid_disabled_and_enabled_states(self):
        self.assertTrue(m.startup_disabled())
        value=json.loads(self.startup.read_text());value['enabled']=True;self.startup.write_text(json.dumps(value))
        self.assertFalse(m.startup_disabled())
    def test_missing_record_differs_from_missing_service_state(self):
        self.startup.unlink();self.assertTrue(m.startup_disabled())
        (self.service/'state/startup-private').rmdir();(self.service/'state').rmdir()
        with self.assertRaises(FileNotFoundError):m.startup_disabled()
    def test_malformed_or_duplicated_enabled_field_rejected(self):
        for value in ('{}','{"schema":1,"enabled":false,"enabled":true}', '[]'):
            self.startup.write_text(value)
            with self.assertRaises((RuntimeError,ValueError)):m.startup_disabled()
    def test_symlinked_startup_record_rejected(self):
        target=self.root/'target';self.startup.rename(target);self.startup.symlink_to(target)
        with self.assertRaises(OSError):m.startup_disabled()
    def test_all_app_roles_are_detected_without_signalling(self):
        for pid,rel in ((1,'roles/controller/native_probe.py'),(2,'roles/receiver/native_probe.py')):
            d=self.proc/str(pid);d.mkdir();(d/'cmdline').write_bytes(b'/usr/bin/python3\0-I\0-B\0'+str(self.service/rel).encode()+b'\0')
        d=self.proc/'3';d.mkdir();(d/'cmdline').write_bytes(b'/usr/bin/python3\0-I\0-B\0'+str(self.apps/m.APP_ID/'native_probe.py').encode()+b'\0')
        self.assertEqual({x['role'] for x in m.active_processes(self.proc)},{'controller','receiver','ui'})
    def test_unexpected_app_invocation_rejected(self):
        d=self.proc/'1';d.mkdir();(d/'cmdline').write_bytes(b'python3\0'+str(self.service/'roles/receiver/native_probe.py').encode()+b'\0')
        with self.assertRaises(RuntimeError):m.active_processes(self.proc)
    def test_proc_permission_error_is_not_absence(self):
        d=self.proc/'1';d.mkdir()
        with patch.object(Path,'read_bytes',side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):m.active_processes(self.proc)
    def test_symlink_cleanup_marker_still_blocks_installation(self):
        (self.service/'roles/receiver/state/request.json').symlink_to(self.root/'missing')
        with patch.object(m,'active_processes',return_value=[]):
            self.assertEqual(m.snapshot()['cleanupMarkers'],['roles/receiver/state/request.json'])
    def test_requires_two_consecutive_idle_observations(self):
        idle={'startupDisabled':True,'processes':[],'cleanupMarkers':[]}
        active={**idle,'processes':[{'role':'receiver','pid':1}]}
        now=[0]
        def wait(seconds):now[0]+=seconds
        with patch.object(m,'snapshot',side_effect=[idle,active,idle,idle]) as read:
            self.assertTrue(m.verify_idle(lambda:now[0],wait)['idle']);self.assertEqual(read.call_count,4)
    def test_enabled_startup_or_pending_marker_times_out(self):
        for value in ({'startupDisabled':False,'processes':[],'cleanupMarkers':[]},
                      {'startupDisabled':True,'processes':[],'cleanupMarkers':['request']}):
            now=[0]
            def wait(seconds):now[0]+=seconds
            with patch.object(m,'snapshot',return_value=value),self.assertRaisesRegex(RuntimeError,'package unchanged'):
                m.verify_idle(lambda:now[0],wait)

if __name__=='__main__':unittest.main()
