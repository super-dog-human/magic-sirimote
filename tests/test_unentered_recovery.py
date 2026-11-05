import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/runtime'))
import unentered_recovery as recovery


class UnenteredRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.c = Path(self.tmp.name) / 'controller'; self.c.mkdir(mode=0o770)
        self.b = Path(self.tmp.name) / 'receiver'; self.b.mkdir(mode=0o770)
        self.c.chmod(0o770); self.b.chmod(0o770)
        self.run = 'a' * 32
        self.process = {'pid': 12345, 'startTicks': 54321, 'status': {'Uid': ' '.join([str(os.getuid())]*4), 'CapEff': '0000000000000000'}}
        self.old = {'pid': 22345, 'startTicks': 12345, 'status': dict(self.process['status'])}
        self.record = {'run': self.run, 'process': self.process, 'schema': 1, 'appId': recovery.APP}
        self.write(self.b/'recovery-controller-start.json', self.record, 0o660)
        self.request = {'run': self.run, 'schema': 2, 'appId': recovery.APP, 'priorProcess': self.old,
                        'gattLookupReply': {'returnValue': True}, 'expiresEpochMs': 1000}
        self.write(self.b/'recovery-request.json', self.request, 0o660)
        for kind in ('intent', 'reply', 'stable'):
            value = {'run': self.run, 'generation': 2}
            if kind == 'reply': value = {'run': self.run, 'reply': self.request['gattLookupReply'], 'ownership': 'unproven'}
            self.write(self.c/('recovery-gatt-'+self.run+'-'+kind+'.json'), value, 0o640)
        (self.b/'borrowed-active').mkdir()
        (self.b/'borrowed-active'/'evidence').write_text('original sensor state remains uncertain')
        (self.b/'controller-start.json').write_text('original controller evidence')
        self.args = dict(run=self.run,controller_state=self.c,receiver_state=self.b,
                         controller_app='/controller',receiver_app='/receiver',proof=lambda:True,
                         prior={'process':self.old},state_uid=os.getuid(),group=os.getgid(),now_ms=2000,native_idle=lambda:True)
        # Filesystem, ownership, journal preservation and archive resumption are real.
        # Process/package proof and parsed request endpoint are isolated here.
        for name, value in [('read_record', self.record), ('_ended', True), ('validate_reply', True)]:
            p = patch.object(recovery,name,return_value=value);p.start();self.addCleanup(p.stop)
        self.before=self.contents()

    def write(self,p,value,mode):
        p.write_text(json.dumps(value));p.chmod(mode)

    def contents(self):
        return {str(p.relative_to(self.tmp.name)):p.read_bytes() for p in Path(self.tmp.name).rglob('*') if p.is_file()}

    def test_expired_unentered_attempt_is_preserved_and_original_journal_untouched(self):
        self.assertTrue(recovery.retire(**self.args))
        after=self.contents()
        self.assertEqual(after['receiver/borrowed-active/evidence'],self.before['receiver/borrowed-active/evidence'])
        self.assertEqual(after['receiver/controller-start.json'],self.before['receiver/controller-start.json'])
        self.assertEqual(sorted(after.values()),sorted(self.before.values()))
        self.assertFalse((self.b/'recovery-request.json').exists())
        self.assertFalse((self.b/'recovery-controller-start.json').exists())

    def test_started_result_or_journal_blocks_all_archiving(self):
        for name in ('receiver-recovery-start-'+self.run+'.json','receiver-recovery-result-'+self.run+'.json',
                     'recovery-'+self.run+'-1.json','recovery-active'):
            with self.subTest(name=name):
                p=self.b/name;p.write_text('{}');before=self.contents()
                with self.assertRaisesRegex(RuntimeError,'already recorded'):recovery.retire(**self.args)
                self.assertEqual(before,self.contents());p.unlink()

    def test_live_or_unverified_process_package_lease_or_native_blocks(self):
        for kind in ('process','proof','native'):
            args=dict(self.args)
            if kind=='proof':args['proof']=lambda:False
            if kind=='native':args['native_idle']=lambda:False
            with patch.object(recovery,'_ended',return_value=kind!='process'):
                with self.assertRaises(RuntimeError):recovery.retire(**args)
            self.assertEqual(self.before,self.contents())

    def test_unexpired_wrong_run_mismatch_or_bad_permissions_preserved(self):
        for kind in ('expiry','run','prior','mode','symlink','unknown'):
            with self.subTest(kind=kind):
                p=self.b/'recovery-request.json';request=dict(self.request)
                if kind=='expiry':request['expiresEpochMs']=2000
                if kind=='run':request['run']='b'*32
                if kind=='prior':request['priorProcess']={**self.old,'pid':22}
                self.write(p,request,0o660)
                if kind=='mode':p.chmod(0o666)
                if kind=='symlink':
                    p.rename(self.b/'target');p.symlink_to('target')
                extra=self.c/('recovery-gatt-'+self.run+'-unknown.json')
                if kind=='unknown':extra.write_text('{}')
                before=self.contents()
                with self.assertRaises((RuntimeError,OSError)):recovery.retire(**self.args)
                self.assertEqual(before,self.contents())
                if kind=='symlink':p.unlink();(self.b/'target').rename(p)
                if extra.exists():extra.unlink()
                self.write(p,self.request,0o660)

    def test_partial_archives_resume_after_each_rename(self):
        rename=os.rename
        for count in range(1,5):
            # Recreate this attempt's files before the next simulated interruption.
            for folder in (self.c,self.b):
                for p in folder.glob('*-unentered-*'):p.unlink()
            for name,raw in self.before.items():
                p=Path(self.tmp.name)/name;p.write_bytes(raw)
                if p.name.startswith('recovery-'):p.chmod(0o640 if p.parent==self.c else 0o660)
            calls=[0]
            def interrupted(*args,**kwargs):
                rename(*args,**kwargs);calls[0]+=1
                if calls[0]==count:raise OSError('simulated shutdown after rename')
            with patch.object(recovery.os,'rename',side_effect=interrupted):
                with self.assertRaises(OSError):recovery.retire(**self.args)
            self.assertTrue((self.b/'recovery-controller-start.json').exists())
            self.assertTrue(recovery.retire(**self.args))
            self.assertEqual(sorted(self.before.values()),sorted(self.contents().values()))

    def test_new_start_evidence_during_archive_prevents_further_changes(self):
        rename=os.rename;calls=[]
        def entered(*args,**kwargs):
            rename(*args,**kwargs);calls.append(args)
            (self.b/('receiver-recovery-start-'+self.run+'.json')).write_text('{}')
        with patch.object(recovery.os,'rename',side_effect=entered):
            with self.assertRaises(RuntimeError):recovery.retire(**self.args)
        self.assertEqual(len(calls),1)
        self.assertTrue((self.b/'recovery-controller-start.json').exists())

class ControllerRetryTests(unittest.TestCase):
    def test_retired_unentered_dispatch_rechecks_then_connects(self):
        from contextlib import ExitStack
        from unittest.mock import Mock
        import resident_controller_entry as entry
        now=[0.0];stop=Mock();stop.is_set.return_value=False
        stop.wait.side_effect=lambda n:now.__setitem__(0,now[0]+n)
        lease=Mock();lease.held.return_value=True
        trace=[];pump=Mock();pump.stop.return_value=True
        with ExitStack() as s:
            s.enter_context(patch('orphan_reconcile._read',return_value=({'run':'a'*32},None)))
            inspect=s.enter_context(patch('takeover_prepare.inspect',side_effect=[RuntimeError('previous recovery attempt retained'),RuntimeError('previous recovery attempt retained'),{'status':'eligible'}]))
            retire=s.enter_context(patch('takeover_prepare.retire_unentered',side_effect=[RuntimeError('unentered recovery request not expired'),True]))
            connect=s.enter_context(patch.object(entry,'bootstrap',return_value=True))
            s.enter_context(patch.object(entry,'PersistentConnectedStatusPump',return_value=pump))
            s.enter_context(patch.object(entry,'wait_recovery_connection'))
            execute=s.enter_context(patch('takeover_recovery.execute',return_value={'status':'recovered'}))
            self.assertEqual(entry.recover_retained_if_connected(lease=lease,pin={},stop=stop,clock=lambda:now[0],trace=trace.append),{'status':'recovered'})
            self.assertEqual(now[0],1)
            self.assertEqual(inspect.call_count,3);self.assertEqual(retire.call_count,2)
            connect.assert_called_once();execute.assert_called_once()
            self.assertIn('bootstrap-unentered-recovery-archived',trace)

    def test_uncertain_started_recovery_does_not_connect_or_launch(self):
        from unittest.mock import Mock
        import resident_controller_entry as entry
        stop=Mock();stop.is_set.return_value=False
        lease=Mock();lease.held.return_value=True
        with patch('orphan_reconcile._read',return_value=({'run':'a'*32},None)), \
             patch('takeover_prepare.inspect',side_effect=RuntimeError('previous recovery attempt retained')), \
             patch('takeover_prepare.retire_unentered',side_effect=RuntimeError('unentered recovery lookup uncertain')), \
             patch.object(entry,'bootstrap') as connect, patch('takeover_recovery.execute') as execute:
            with self.assertRaisesRegex(RuntimeError,'lookup uncertain'):
                entry.recover_retained_if_connected(lease=lease,pin={},stop=stop)
            connect.assert_not_called();execute.assert_not_called()


class RecoveryEntryOrderingTests(unittest.TestCase):
    def test_failed_start_receipt_prevents_sensor_access(self):
        from contextlib import ExitStack
        from unittest.mock import Mock
        import receiver_recovery_entry as entry
        old={'pid':99999,'startTicks':1,'status':{'Uid':' '.join([str(os.getuid())]*4)}}
        with ExitStack() as s:
            s.enter_context(patch.object(entry,'recovery_controller_record',return_value={'run':'a'*32}))
            s.enter_context(patch.object(entry,'authenticate',return_value={'request':{'priorProcess':old}}))
            s.enter_context(patch.object(entry,'prior_run',return_value={'process':old}))
            s.enter_context(patch.object(entry,'_start_ticks',side_effect=FileNotFoundError))
            s.enter_context(patch.object(entry,'write_recovery_start',side_effect=OSError('receipt not durable')))
            feature=s.enter_context(patch.object(entry,'LocalFeatureLease'))
            recover=s.enter_context(patch.object(entry,'recover_zero'))
            with self.assertRaisesRegex(OSError,'not durable'):
                entry.run_recovery(state='/unused',controller_app='/c',controller_package='/p',pin={},stop=Mock())
            feature.assert_not_called();recover.assert_not_called()


if __name__=='__main__':unittest.main()
