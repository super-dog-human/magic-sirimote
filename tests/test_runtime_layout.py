"""The runtime inventory must be connected to the two real entrypoints."""
import ast,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from retired_requests import RETIRED,reject_retired_requests
ROOT=Path(__file__).resolve().parents[1]

class LayoutTests(unittest.TestCase):
 def test_all_packaged_modules_are_reachable_and_local_imports_resolve(self):
  runtime=ROOT/'src/runtime'
  files={p.stem:p for p in runtime.rglob('*.py')}
  inventory=json.loads((ROOT/'src/runtime-files.json').read_text())
  self.assertEqual({p.name for p in files.values()},set(inventory))
  edges={name:set() for name in files}
  for name,p in files.items():
   for n in ast.walk(ast.parse(p.read_text())):
    imports=[]
    if isinstance(n,ast.Import):imports=[a.name for a in n.names]
    elif isinstance(n,ast.ImportFrom) and n.module:imports=[n.module]
    elif isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='__import__':
     self.assertIsInstance(n.args[0],ast.Constant);imports=[n.args[0].value]
    for module in imports:
     if module in files:edges[name].add(module)
  seen=set();todo=['resident_controller_entry','postconnect_receiver_native_entry']
  while todo:
   name=todo.pop()
   if name in seen:continue
   seen.add(name);todo+=list(edges[name]-seen)
  self.assertEqual(set(files),seen,'Remove unused modules instead of bundling them')
  # Import every module in a clean process to catch missing imports
  # without starting entrypoints or touching native devices.
  import subprocess,sys,os
  env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(runtime))
  subprocess.run([sys.executable,'-B','-c','import importlib; [importlib.import_module(n) for n in '+repr(sorted(files))+']'],check=True,env=env,cwd=ROOT)
 def test_retired_requests_are_retained_and_blocked_including_broken_symlink(self):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)
   for name in sorted(RETIRED)+['generic-presensor-request-'+('a'*32)+'.json','generic-presensor-request-'+('a'*32)+'-'+('b'*32)+'.json']:
    f=p/name;f.write_text('old request')
    with self.assertRaisesRegex(RuntimeError,'retired-maintenance-request-retained'):reject_retired_requests(p)
    self.assertEqual(f.read_text(),'old request');f.unlink()
   f=p/'owner-mode-repair-request.json';f.symlink_to(p/'missing')
   with self.assertRaises(RuntimeError):reject_retired_requests(p)
   self.assertTrue(f.is_symlink())
 def test_current_stop_recovery_and_archive_records_are_not_retired_requests(self):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)
   for name in ('recovery-request.json','receiver-launch-intent.json','developer-stop-'+('a'*32)+'.json','completed-owner-mode-repair-request.json'):(p/name).write_text('{}')
   reject_retired_requests(p)
 def test_controller_stops_before_native_checks_or_bluetooth_if_old_request_exists(self):
  import resident_controller_entry as controller
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory);(p/'serial-zero-archive-request.json').write_text('{}')
   with patch.object(controller,'STATE',p),patch.object(controller,'ordinary') as ordinary,patch.object(controller,'load_config') as pin:
    with self.assertRaisesRegex(RuntimeError,'retired-maintenance'):controller.main()
    ordinary.assert_not_called();pin.assert_not_called()
 def test_receiver_stops_before_signal_registration_if_old_request_exists(self):
  import postconnect_receiver_native_entry as receiver
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory);state=p/receiver.APP/'state';state.mkdir(parents=True)
   (state/'owner-mode-repair-request.json').write_text('{}')
   with patch.object(receiver,'ROOT',p),patch.object(receiver.signal,'signal') as signal,patch.object(receiver,'controller_pin') as pin:
    with self.assertRaisesRegex(RuntimeError,'retired-maintenance'):receiver.main()
    signal.assert_not_called();pin.assert_not_called()

if __name__=='__main__':unittest.main()
