"""Lifecycle commands refuse conflicts and publish cooperative stop requests."""
import importlib.util
import json
import os
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/integrated'), str(ROOT / 'src/native')]
import control
from native_manager import RuntimeSetup, consume_installer, maintenance_action


def found(**changes):
    return dict({'controller': [], 'receiver': [], 'legacy': [], 'ui': []}, **changes)


class ControlTests(unittest.TestCase):
    def test_start_does_not_run_after_unknown_activity_creation(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            bus = Mock(); bus.tv_address.return_value = 'aa:bb:cc:dd:ee:20'; bus.remote_name.return_value = 'Remote'
            bus.request.side_effect = [{'returnValue': True}, {'returnValue': True, 'status': 'create-required', 'token': 'a' * 48}]
            bus.create_startup.side_effect = RuntimeError('unknown create outcome')
            app = RuntimeSetup(Path(d), bus)
            values = {'schema': 1, 'remoteAddress': 'aa:bb:cc:dd:ee:10', 'adapterAddress': 'aa:bb:cc:dd:ee:20', 'remoteName': 'Remote', 'gyroEnabled': True}
            with patch('native_manager.settings.save'), self.assertRaises(RuntimeError): app.apply(values)
            self.assertEqual([call.args[0] for call in bus.request.call_args_list], ['configure', 'startupPrepare'])
            self.assertFalse(app.done)

    def test_first_save_waits_for_clean_stop_before_applying_all_twelve_cells(self):
        from unittest.mock import Mock
        values = {'schema': 1, 'remoteAddress': 'aa:bb:cc:dd:ee:10', 'adapterAddress': 'aa:bb:cc:dd:ee:20', 'remoteName': 'Remote', 'gyroEnabled': True}
        with tempfile.TemporaryDirectory() as d:
            bus = Mock(); bus.tv_address.return_value = 'aa:bb:cc:dd:ee:20'; bus.remote_name.return_value = 'Remote'; app = RuntimeSetup(Path(d), bus); app.values.update(values)
            bus.request.return_value = {'returnValue': True, 'status': 'stop-requested'}
            app.choose(5, Mock())
            self.assertEqual(bus.request.call_args.args[0], 'drain')
            bus.request.return_value = {'returnValue': True, 'cleanStop': False, 'processes': found(controller=[{'pid': 1}])}
            with patch.object(app, 'apply') as apply, patch.object(app, 'start_assignment_batch') as assignments:
                self.assertFalse(app.settings_tick(Mock()))
                apply.assert_not_called()
                app.next_settings_check = 0
                bus.request.return_value = {'returnValue': True, 'cleanStop': True, 'processes': found()}
                self.assertTrue(app.settings_tick(Mock()))
                apply.assert_not_called()
                assignments.assert_called_once()
                self.assertEqual(len(assignments.call_args.args[0]),12)

    def test_settings_timeout_never_changes_configuration(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            bus = Mock(); bus.tv_address.return_value = 'aa:bb:cc:dd:ee:20'; bus.remote_name.return_value = 'Remote'; app = RuntimeSetup(Path(d), bus)
            app.pending_settings = ('save', {}, 0)
            bus.request.return_value = {'returnValue': True, 'cleanStop': False, 'processes': found()}
            with patch.object(app, 'apply') as apply:
                self.assertTrue(app.settings_tick(Mock()))
                apply.assert_not_called()
            self.assertIn('not confirmed', app.message)

    def test_button_drafts_wait_for_global_save_and_clean_stop(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            bus=Mock();bus.tv_address.return_value='aa:bb:cc:dd:ee:20';bus.remote_name.return_value='Remote'
            bus.request.return_value={'returnValue':True,'cleanStop':False,'processes':found()}
            from tv_assignments import execute
            execute(d,'assign',32,2,'none')
            app=RuntimeSetup(Path(d),bus);app.values['remoteAddress']='aa:bb:cc:dd:ee:10';canvas=Mock()
            app.choose(6,canvas);app.infrared.choose(0);app.infrared.choose(0)
            app.handle(('key',461),canvas)
            bus.request.assert_not_called();self.assertEqual(app.button_drafts,{'20:00':'none'})
            app.choose(5,canvas)
            self.assertIsNone(app.confirm_action)
            self.assertTrue(app.controls_disabled)
            self.assertEqual(bus.request.call_args.args[0],'drain')
            with patch.object(app,'start_assignment_batch') as submit, patch.object(app,'persist_device') as persist:
                app.settings_tick(canvas);submit.assert_not_called();persist.assert_not_called()
                app.next_settings_check=0
                bus.request.return_value={'returnValue':True,'cleanStop':True,'processes':found()}
                order=[];persist.side_effect=lambda *_:order.append('identity');submit.side_effect=lambda *_:order.append('assignments')
                app.settings_tick(canvas);self.assertEqual(order,['identity','assignments'])
                from tv_assignments import displayed_bindings
                submit.assert_called_once_with(displayed_bindings(d, {'20:00':'none'}))

    def test_installer_cannot_interrupt_an_infrared_write(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            bus = Mock(); bus.tv_address.return_value = 'aa:bb:cc:dd:ee:20'; bus.remote_name.return_value = 'Remote'; app = RuntimeSetup(Path(d), bus); app.choose(6, Mock())
            app.infrared.busy = True
            with self.assertRaisesRegex(RuntimeError, 'finish before updating'):
                app.stop_runtime()
            bus.request.assert_not_called()

    def test_global_save_cleanup_failure_keeps_drafts_and_does_not_write(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            bus=Mock();bus.request.return_value={'returnValue':True,'cleanStop':False,'processes':found()}
            app=RuntimeSetup(Path(d),bus);app.button_drafts={'20:00':'none'}
            app.pending_assignments=dict(app.button_drafts);app.pending_settings=('save',{},0)
            with patch.object(app,'start_assignment_batch') as submit, patch.object(app,'persist_device') as persist:
                self.assertTrue(app.settings_tick(Mock()));submit.assert_not_called();persist.assert_not_called()
            self.assertIsNone(app.pending_settings);self.assertEqual(app.button_drafts,{'20:00':'none'})
            self.assertIn('not confirmed',app.message)

    def test_configuration_always_activates_but_stop_stays_internal(self):
        from unittest.mock import Mock
        values = {'schema': 1, 'remoteAddress': 'aa:bb:cc:dd:ee:10', 'adapterAddress': 'aa:bb:cc:dd:ee:20', 'remoteName': 'Remote', 'gyroEnabled': True}
        with tempfile.TemporaryDirectory() as d:
            bus = Mock(); bus.tv_address.return_value = 'aa:bb:cc:dd:ee:20'; bus.remote_name.return_value = 'Remote'; bus.request.return_value = {'returnValue': True, 'status': 'registered'}
            app = RuntimeSetup(Path(d), bus)
            with patch('native_manager.settings.save'):
                app.apply(values)
            self.assertTrue(app.done)
            self.assertEqual(bus.request.call_args.args[0], 'start')
            app.pending_settings = ('buttons', None, 100)
            app.resume_after_settings = True
            app.stop_runtime()
            self.assertFalse(app.resume_after_settings)
            self.assertIsNone(app.pending_settings)
            self.assertEqual(bus.request.call_args.args[0], 'stop')

    def test_configuration_repairs_verified_startup_state_before_enabling(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            bus = Mock(); bus.tv_address.return_value = 'aa:bb:cc:dd:ee:20'; bus.remote_name.return_value = 'Remote'; bus.request.side_effect = [
                {'returnValue': True, 'status': 'repair-required'},
                {'returnValue': True, 'status': 'scheduled'},
                {'returnValue': True, 'status': 'registered'}]
            app = RuntimeSetup(Path(d), bus); app.enable_startup()
            self.assertEqual([call.args[0] for call in bus.request.call_args_list], ['startupPrepare','startupRepair','startupPrepare'])

    def test_archive_before_input_requires_empty_journal_and_no_receiver(self):
        import orphan_reconcile as recovery
        from unittest.mock import Mock
        for mode in ('empty', 'written', 'receiver'):
            with tempfile.TemporaryDirectory() as d:
                cpath=Path(d)/'controller';bpath=Path(d)/'receiver';cpath.mkdir();bpath.mkdir()
                run='b'*32;owner=os.getuid();group=os.getgid()
                intent={'run':run,'stage':'receiver-launch-intent','generation':1}
                def write(path,value,mode):
                    path.write_text(json.dumps(value));path.chmod(mode)
                write(cpath/'receiver-launch-intent.json',intent,0o640)
                write(bpath/'request.json',{'schema':1,'appId':'org.magicsirimote.app','run':run,'expiresEpochMs':1},0o660)
                write(bpath/'controller-start.json',{'schema':1,'appId':'org.magicsirimote.app','run':run,'process':{'pid':123,'startTicks':456,'status':{'Uid':' '.join([str(owner)]*4)}}},0o660)
                journal=cpath/('input-'+run+'.jsonl');journal.write_text('input-intent' if mode=='written' else '');journal.chmod(0o640)
                if mode=='receiver':(bpath/('receiver-start-'+run+'.json')).write_text('{}')
                c=os.open(cpath,os.O_RDONLY);b=os.open(bpath,os.O_RDONLY)
                lease=Mock();lease.dirfd=c;lease.held.return_value=True
                try:
                    with patch.object(recovery.bundle,'active',return_value=True), patch.object(recovery,'_ended',return_value=True), patch.object(recovery.att,'candidate_pids',return_value=[]), patch.object(recovery.package,'package_matches',return_value=True):
                        result=recovery.archive_before_input(c=c,b=b,intent=intent,intent_stat=(cpath/'receiver-launch-intent.json').stat(),controller_app='controller',receiver_app='receiver',receiver_package='package',pin={},lease=lease,owner=owner,group=group)
                    if mode=='empty':
                        self.assertEqual(result['priorOutcome'],'input-never-started')
                        self.assertTrue((bpath/('request-before-input-'+run+'.json')).is_file())
                        self.assertFalse((cpath/'receiver-launch-intent.json').exists())
                    else:
                        self.assertIsNone(result)
                        self.assertTrue((cpath/'receiver-launch-intent.json').exists())
                finally:os.close(c);os.close(b)

    def test_integrated_handoff_path_fits_linux_socket_limit(self):
        import prelaunch_handoff_runtime as handoff
        with patch.object(handoff.bundle, 'active', return_value=True):
            path = handoff.socket_path(handoff.bundle.ROOT / 'roles/controller/state', 'a' * 32)
            self.assertLess(len(bytes(path)), 108)
            self.assertEqual(path.parent, handoff.bundle.ROOT / 'state')
        with patch.object(handoff.bundle, 'active', return_value=False):
            self.assertEqual(handoff.socket_path('/legacy/state', 'a' * 32), Path('/legacy/state/h' + 'a' * 16))

    def test_installer_cannot_start_input_while_button_settings_are_open(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            bus = Mock(); bus.tv_address.return_value = 'aa:bb:cc:dd:ee:20'; bus.remote_name.return_value = 'Remote'; app = RuntimeSetup(Path(d), bus)
            app.infrared = Mock()
            with self.assertRaisesRegex(RuntimeError, 'Close button settings'):
                app.apply({})
            bus.request.assert_not_called()

    def test_ir_programming_refuses_retained_sensor_state(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            app = RuntimeSetup(Path(d), Mock())
            with patch('control_processes.require_no_other_input'), patch('control_processes.clean_state', return_value=False), patch('ir_programmer.execute') as execute:
                result = app.program_ir(Path(d), 'delete', 1, 2, '')
                self.assertEqual(result['status'], 'not-sent')
                self.assertIn('cleanup', result['message'])
                execute.assert_not_called()

    def test_ir_idle_exception_does_not_ignore_a_controller_or_other_service(self):
        import ir_programmer as ir
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); process = root / '2147483000'; process.mkdir()
            command = process / 'cmdline'
            command.write_bytes(b'org.magicsirimote.app.service\0')
            with self.assertRaises(RuntimeError): ir.runtime_idle(root)
            ir.runtime_idle(root, allow_idle_service=True)
            for args in (b'/usr/bin/python3\0-I\0-B\0/media/developer/apps/usr/palm/services/org.magicsirimote.app.service/roles/controller/native_probe.py\0', b'org.magicsirimote.other.service\0'):
                command.write_bytes(args)
                with self.assertRaises(RuntimeError): ir.runtime_idle(root, allow_idle_service=True)

    def test_ir_idle_allows_only_exact_readonly_helpers(self):
        import ir_programmer as ir
        service='/media/developer/apps/usr/palm/services/org.magicsirimote.app.service/'
        with tempfile.TemporaryDirectory() as d:
            process=Path(d)/'2147483000';process.mkdir();command=process/'cmdline'
            prefix=['/usr/bin/python3','-I','-B']
            for tail in ([service+'power-read.py'],[service+'activity-read.py'],[service+'control.py','status']):
                command.write_bytes(b'\0'.join(x.encode() for x in prefix+tail)+b'\0')
                ir.runtime_idle(Path(d),allow_idle_service=True)
                with self.assertRaises(RuntimeError):ir.runtime_idle(Path(d))
            for tail in ([service+'control.py','start'],[service+'control.py','configure'],
                         [service+'roles/receiver/native_probe.py'],[service+'power-read.py','unexpected'],
                         [service+'unknown.py'],[service+'../power-read.py']):
                command.write_bytes(b'\0'.join(x.encode() for x in prefix+tail)+b'\0')
                with self.assertRaises(RuntimeError):ir.runtime_idle(Path(d),allow_idle_service=True)

    def test_old_native_window_blocks_input_before_launch_intent(self):
        import postconnect_supervisor_cycle as cycle
        from unittest.mock import Mock
        owner = cycle.SupervisorCycle.__new__(cycle.SupervisorCycle)
        owner.lease = Mock(); owner.lease.held.return_value = True
        with patch.object(cycle.bundle, 'active', return_value=True), patch('control_processes.processes', return_value=found(ui=[{'pid': 8}])):
            self.assertEqual(owner.begin(), {'status': 'not-ready'})

    def test_launcher_cannot_reuse_an_existing_native_window(self):
        import tv_launch
        from unittest.mock import Mock
        invoke = Mock()
        launcher = tv_launch.Launcher('a' * 32, invoke=invoke)
        with patch.object(tv_launch.bundle, 'active', return_value=True), patch('control_processes.processes', return_value=found(ui=[{'pid': 8}])):
            self.assertEqual(launcher.launch('B', 'a' * 32), 'rejected')
        invoke.assert_not_called()

    def test_start_refuses_previous_runtime_before_loading_device_settings(self):
        with patch.object(control, 'processes', return_value=found(legacy=[{'pid': 5}])), patch.object(control, 'load') as load:
            with self.assertRaisesRegex(RuntimeError, 'previous input'):
                control.prepare_start()
            load.assert_not_called()

    def test_configuration_refuses_live_worker_or_unfinished_journal(self):
        for processes, clean in ((found(receiver=[{'pid': 5}]), True), (found(), False)):
            with patch.object(control, 'processes', return_value=processes), patch.object(control, 'clean_state', return_value=clean), patch.object(control, 'save') as save:
                with self.assertRaises(RuntimeError): control.configure({})
                save.assert_not_called()

    def test_missing_controller_is_not_reported_as_clean_stop_with_worker_or_journal(self):
        for processes, clean in ((found(receiver=[{'pid': 9}]), True), (found(), False)):
            with patch.object(control, 'processes', return_value=processes), patch.object(control, 'clean_state', return_value=clean):
                self.assertEqual(control.stop()['status'], 'needs-recovery')

    def test_gui_start_closes_only_after_service_accepts_configuration_and_start(self):
        class Bus:
            def __init__(self): self.calls = []
            def tv_address(self): return 'aa:bb:cc:dd:ee:20'
            def remote_name(self, remote, adapter, verified_name=None): return 'Remote'
            def request(self, method, params): self.calls.append(method); return {'returnValue': True, 'status': 'registered'}
        with tempfile.TemporaryDirectory() as d:
            bus = Bus(); app = RuntimeSetup(Path(d), bus)
            values = {'schema': 1, 'remoteAddress': 'aa:bb:cc:dd:ee:10', 'adapterAddress': 'aa:bb:cc:dd:ee:20', 'remoteName': 'Remote', 'gyroEnabled': True}
            with patch('native_manager.settings.save'):
                app.apply(values)
            self.assertTrue(app.done)
            self.assertEqual(bus.calls, ['configure', 'startupPrepare', 'startupRepair', 'start'])

    def test_external_device_configuration_is_rejected(self):
        nonce = 'a' * 32
        for request in ({'nonce':nonce,'action':'configure'},
                        {'nonce':nonce,'action':'start','settings':{'remoteAddress':'aa:bb:cc:dd:ee:10'}},
                        {'nonce':nonce,'action':'stop','remoteAddress':'aa:bb:cc:dd:ee:10'}):
            with self.assertRaises(ValueError): maintenance_action(request, nonce)
        for action in ('start', 'stop'):
            self.assertEqual(maintenance_action({'nonce':nonce,'action':action},nonce),action)

    def test_maintenance_start_uses_only_saved_identity(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d:
            bus = Mock(); bus.tv_address.return_value = 'aa:bb:cc:dd:ee:20'
            bus.remote_name.return_value = 'Remote'
            bus.request.return_value = {'returnValue':True,'status':'registered'}
            app = RuntimeSetup(Path(d), bus)
            app.saved_values = {'remoteAddress':'aa:bb:cc:dd:ee:10',
                'adapterAddress':'aa:bb:cc:dd:ee:20','remoteName':'Remote',
                'gyroEnabled':True,'gyroSensitivity':3}
            app.values['remoteAddress'] = 'aa:bb:cc:dd:ee:99'
            with patch('native_manager.settings.save'):
                app.start_saved()
            method, payload = bus.request.call_args_list[0].args
            self.assertEqual(method, 'configure')
            self.assertEqual(payload['settings']['schema'], 1)
            self.assertEqual(payload['settings']['remoteAddress'], 'aa:bb:cc:dd:ee:10')
            self.assertTrue(app.done)

    def test_installer_unknown_result_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            nonce = 'a' * 32
            (Path(d) / ('install-result-' + nonce + '.json')).write_text('{"status":"pending"}')
            with patch('native_manager.STATE', Path(d)):
                self.assertFalse(consume_installer({'installerRequest': nonce}, lambda *_: self.fail('replayed')))


if __name__ == '__main__': unittest.main()
