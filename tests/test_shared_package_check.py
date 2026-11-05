import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import runtime_bundle as bundle
from controller_preload import revalidate

class Tests(unittest.TestCase):
 def fixture(self,root):
  files={'services.json':json.dumps({'id':bundle.SERVICE,'services':[{'name':bundle.SERVICE}]}).encode(),
         'package.json':json.dumps({'name':bundle.SERVICE}).encode(),
         'roles/controller/native_probe.py':b'controller\n','roles/receiver/native_probe.py':b'receiver\n',
         'runtime/shared.py':b'content\n','runtime/__pycache__/shared.cpython-312.pyc':b'bytecode\n'}
  for name,data in files.items():
   path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
  pin={'schema':'bundled-role-v1','appId':bundle.APP,'files':{n:hashlib.sha256(d).hexdigest() for n,d in files.items()},'serviceInfoSha256':hashlib.sha256(files['package.json']).hexdigest()}
  return {role:{**copy.deepcopy(pin),'role':role} for role in ('controller','receiver')}
 def test_one_fresh_read_per_shared_file_with_both_roles_validated(self):
  from package_read_batch import PackageReadBatch
  original=PackageReadBatch.read
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)/bundle.SERVICE;pins=self.fixture(root)
   with patch.object(bundle,'ROOT',root),patch.object(PackageReadBatch,'read',autospec=True,side_effect=original) as read:
    self.assertTrue(bundle.packages_match(pins))
   names=[call.args[1] for call in read.call_args_list]
   self.assertEqual(names.count('runtime/shared.py'),1)
   self.assertEqual(names.count('runtime/__pycache__/shared.cpython-312.pyc'),1)
 def test_different_role_pins_or_changed_source_cache_wrapper_are_rejected(self):
  for failure in ('pin','metadata','source','cache','wrapper','role'):
   with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)/bundle.SERVICE;pins=self.fixture(root)
    if failure=='pin':pins['receiver']['files']['runtime/shared.py']='0'*64
    elif failure=='metadata':pins['receiver']['serviceInfoSha256']='0'*64
    elif failure=='role':pins['receiver']['role']='controller'
    else:
     name={'source':'runtime/shared.py','cache':'runtime/__pycache__/shared.cpython-312.pyc','wrapper':'roles/receiver/native_probe.py'}[failure]
     (root/name).write_bytes(b'changed')
    with patch.object(bundle,'ROOT',root):
     if failure=='role':
      with self.assertRaises(ValueError):bundle.packages_match(pins)
     else:self.assertFalse(bundle.packages_match(pins))
 def test_release_rechecks_both_pins_and_fresh_shared_files(self):
  pins={role:{'role':role} for role in ('controller','receiver')};values={'setting':1}
  for failure in (None,'pin','files'):
   read=Mock(side_effect=lambda role:{'changed':True} if failure=='pin' and role=='receiver' else pins[role])
   pair=Mock(return_value=failure!='files');separate=Mock()
   args=dict(load_values=lambda:dict(values),read_pin=read,verify_package=separate,verify_pair=pair,verify_process=lambda:True,check_conflicts=lambda:None)
   if failure:
    with self.assertRaises(RuntimeError):revalidate(values,pins,**args)
   else:revalidate(values,pins,**args)
   self.assertEqual(read.call_count,2);separate.assert_not_called()
   if failure=='pin':pair.assert_not_called()
   else:pair.assert_called_once_with(pins)

if __name__=='__main__':unittest.main()
