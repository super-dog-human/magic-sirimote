"""Reproduce boot-widened state without a TV, root, or Bluetooth commands."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ColdBootModes(unittest.TestCase):
    def child(self, code, bundled=True):
        paths = [str(ROOT/'src'/p) for p in ('runtime','runtime/vendor','native','integrated')]
        setup = 'import sys; sys.path[:0]=' + repr(paths) + '\n'
        setup += 'import runtime_bundle as bundle\n'
        if bundled:
            setup += "bundle.select('controller')\n"
        setup += 'import os, stat, tempfile, json\nfrom pathlib import Path\nfrom unittest.mock import patch\n'
        run = subprocess.run([sys.executable, '-I', '-B', '-c', setup+code],
                             text=True, capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_boot_widened_parent_and_owned_lock_support_exclusive_lease(self):
        self.child('''
from supervisor_lease import SupervisorLease
with tempfile.TemporaryDirectory() as temp:
 p=Path(temp);p.chmod(0o777);lock=p/'supervisor.lock';lock.touch();lock.chmod(0o777)
 lease=SupervisorLease(p,state_uid=os.getuid(),group=os.getgid())
 assert lease.held() and stat.S_IMODE(lock.stat().st_mode)==0o600
 try: SupervisorLease(p,state_uid=os.getuid(),group=os.getgid())
 except BlockingIOError: pass
 else: raise AssertionError('Second supervisor admitted')
 lease.close()
 assert stat.S_IMODE(p.stat().st_mode)==0o777
''')

    def test_wrong_owner_links_and_unexpected_modes_still_rejected(self):
        self.child('''
from supervisor_lease import SupervisorLease
with tempfile.TemporaryDirectory() as temp:
 p=Path(temp);p.chmod(0o777)
 for owner,group,mode in [(os.getuid()+1,os.getgid(),0o777),(os.getuid(),os.getgid()+1,0o777),(os.getuid(),os.getgid(),0o776)]:
  p.chmod(mode)
  try: SupervisorLease(p,state_uid=owner,group=group)
  except RuntimeError: pass
  else: raise AssertionError('Unexpected metadata accepted')
 p.chmod(0o777);target=p/'target';target.touch();(p/'supervisor.lock').symlink_to(target)
 try: SupervisorLease(p,state_uid=os.getuid(),group=os.getgid())
 except (OSError,RuntimeError): pass
 else: raise AssertionError('Symlink followed')
''')

    def test_live_requests_remain_strict_in_boot_widened_directories(self):
        self.child('''
from receiver_request import write_request,read_request
with tempfile.TemporaryDirectory() as temp:
 p=Path(temp);p.chmod(0o777);options={'state_uid':os.getuid(),'group':os.getgid()}
 write_request(p,'a'*32,2000,now_ms=1000,**options)
 assert stat.S_IMODE((p/'request.json').stat().st_mode)==0o660
 assert read_request(p,owner_uid=os.getuid(),now_ms=1000,**options)['run']=='a'*32
 (p/'request.json').chmod(0o777)
 try: read_request(p,owner_uid=os.getuid(),now_ms=1000,**options)
 except RuntimeError: pass
 else: raise AssertionError('Widened live request accepted')
''')

    def test_retained_binding_and_new_session_after_boot(self):
        self.child('''
import bundle_boot
from types import SimpleNamespace
real_fstat=os.fstat;real_lstat=Path.lstat
def tvstat(s):
 values={key:getattr(s,key) for key in dir(s) if key.startswith('st_')}
 values['st_gid']=5000
 if stat.S_ISDIR(s.st_mode): values['st_uid']=5999
 return SimpleNamespace(**values)
values={'schema':1,'remoteAddress':'aa:bb:cc:dd:ee:10','adapterAddress':'aa:bb:cc:dd:ee:20','remoteName':'Remote'}
with tempfile.TemporaryDirectory() as temp:
 p=Path(temp);p.chmod(0o777)
 with patch.object(os,'fstat',side_effect=lambda fd:tvstat(real_fstat(fd))),patch.object(Path,'lstat',lambda path,*a,**kw:tvstat(real_lstat(path,*a,**kw))):
  bundle_boot.bind_device(p,values)
  bound=p/'device-binding.json';original=bound.read_bytes();bound.chmod(0o777)
  bundle_boot.bind_device(p,values)
  assert bound.read_bytes()==original
  try: bundle_boot.bind_device(p,dict(values,remoteName='Different'))
  except RuntimeError: pass
  else: raise AssertionError('Saved identity replaced')
  session=p/'123-456.json';bundle_boot._save_session(session,values)
  assert bundle_boot._read(session,os.getuid())['remoteName']=='Remote'
  session.chmod(0o777)
  try: bundle_boot._read(session,os.getuid())
  except RuntimeError: pass
  else: raise AssertionError('Widened live session accepted')
''')

    def test_recovery_reads_widened_history_without_claiming_live_sensor_stop(self):
        self.child('''
from atomic_session_directory import AtomicSessionDirectory
from borrowed_runtime_journal import inspect_journal
with tempfile.TemporaryDirectory() as temp:
 p=Path(temp);p.chmod(0o777);options={'state_uid':os.getuid(),'group':os.getgid()}
 session=AtomicSessionDirectory(p,'a'*32,**options)
 session({'stage':'prelaunch-input-intent','generation':1})
 session({'stage':'prelaunch-input-ack','generation':1})
 session.close()
 active=p/'borrowed-active';active.chmod(0o777)
 for record in active.iterdir(): record.chmod(0o777)
 result=inspect_journal(active,'a'*32,owner_uid=os.getuid(),historical=True,**options)
 assert result['status']=='input-start-recorded-sensor-not-attempted'
 try: inspect_journal(active,'a'*32,owner_uid=os.getuid(),**options)
 except RuntimeError: pass
 else: raise AssertionError('Historical records admitted as live')
 assert active.exists()
''')

    def test_widened_expired_request_recovery_preserves_bytes(self):
        # Reuse the real boot recovery fixture in an isolated bundled process.
        self.child('sys.path.insert(0,'+repr(str(ROOT/'tests'))+')\n'+'''
from test_unstarted_boot import RecoveryTests
test=RecoveryTests();test.setUp()
try:
 for folder in (test.a,test.b):
  folder.chmod(0o777)
  for p in folder.iterdir(): p.chmod(0o777)
 # Bundled records use the single app ID, while the legacy fixture uses a/b.
 for name in ('request.json','controller-start.json'):
  p=test.b/name;value=json.loads(p.read_text());value['appId']=bundle.APP
  test.put(test.b,name,value,0o777)
 before=(test.b/'request.json').read_bytes()
 assert test.run_recovery()['priorOutcome']=='not-started-before-reboot'
 assert (test.b/('request-unstarted-'+test.run+'.json')).read_bytes()==before
 assert not list(test.b.glob('receiver-result-*'))
finally: test.tearDown()
''')

    def test_legacy_runtime_does_not_gain_bundled_permissions(self):
        self.child('''
import state_permissions
assert 0o777 not in state_permissions.directory_modes()
assert 0o777 not in state_permissions.retained_modes(0o640)
''', bundled=False)


if __name__ == '__main__':
    unittest.main()
