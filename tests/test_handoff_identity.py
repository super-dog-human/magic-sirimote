"""Exercise recovery parsing in a fresh process with a non-default device."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import importlib.util,json,os,sys,tempfile,time,types
from pathlib import Path
from unittest.mock import patch
root=Path(sys.argv[1]);scenario=sys.argv[2]
sys.path[:0]=[str(root/'src/integrated'),str(root/'src/native'),str(root/'src/runtime')]
import native_manager as manager
values={'remoteAddress':'aa:bb:cc:dd:ee:10','adapterAddress':'aa:bb:cc:dd:ee:20','remoteName':'TEST_REMOTE','gyroEnabled':True,'gyroSensitivity':3}
# Use the real recovery parser, adapting only filesystem owners to this host.
# Load it lazily, just as the native launcher does after session attestation.
def read(directory,**kwargs):
    spec=importlib.util.spec_from_file_location('actual_recovery_request',root/'src/runtime/recovery_request.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.read_recovery_request(directory,**kwargs,state_uid=os.getuid(),group=os.getgid())
sys.modules['recovery_request']=types.SimpleNamespace(read_recovery_request=read)
with tempfile.TemporaryDirectory() as folder:
    service=Path(folder);state=service/'roles/receiver/state';state.mkdir(parents=True);state.chmod(0o770)
    run='a'*32
    process={'pid':123,'startTicks':456,'status':{'Uid':' '.join([str(os.getuid())]*4)}}
    record={'run':run,'process':process}
    reply={'returnValue':True,'subscribed':False,'address':values['remoteAddress'],'adapterAddress':values['adapterAddress'],'clientId':'012'}
    if scenario=='wrong-device':reply['address']='aa:bb:cc:dd:ee:30'
    request={'schema':2,'appId':'org.magicsirimote.app','run':run,'expiresEpochMs':int(time.time()*1000)+(60000 if scenario!='expired' else -1000),'priorProcess':process,'gattLookupReply':reply}
    path=state/'recovery-request.json';path.write_text(json.dumps(request));path.chmod(0o660)
    if scenario=='completed':(state/('receiver-recovery-result-'+run+'.json')).write_text('{}')
    # Controller liveness/pins have separate tests. Do not mock device binding
    # or GATT validation: their import order caused the regression.
    sys.modules['controller_start_record']=types.SimpleNamespace(read_record=lambda *args,**kwargs:record)
    with patch.object(manager,'SERVICE',service),patch('bundle_boot.receiver_settings',return_value=values):
        try:
            pending=manager.pending_worker()
        except (RuntimeError,ValueError) as error:
            if scenario not in ('wrong-device','expired'):raise
            assert ('invalid borrowed view' if scenario=='wrong-device' else 'expired') in str(error),str(error)
        else:
            assert scenario not in ('wrong-device','expired'), 'Invalid request admitted'
            assert pending is (scenario!='completed')
    assert json.loads(path.read_text())==request, 'Recovery evidence changed'
'''


class HandoffIdentityTests(unittest.TestCase):
    def test_real_recovery_parser_uses_attested_device_and_preserves_guards(self):
        for scenario in ('fresh', 'wrong-device', 'expired', 'completed'):
            with self.subTest(scenario=scenario):
                result = subprocess.run([sys.executable, '-B', '-c', PROBE, str(ROOT), scenario],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
