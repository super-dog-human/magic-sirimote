import base64,hashlib,io,json,os,shutil,subprocess,sys,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import build_bytecode,build_integrated,build_support,runtime_bundle

class BytecodeTests(unittest.TestCase):
 def test_cache_is_deterministic_and_checks_source_in_isolated_no_write_mode(self):
  sources={'runtime/probe.py':b'answer=7\n'}
  caches,meta=build_bytecode.compile_files(sources,sys.executable,'/installed')
  second,_=build_bytecode.compile_files(sources,sys.executable,'/installed')
  self.assertEqual(caches,second);self.assertEqual(meta['invalidation'],'checked-hash')
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   for name,data in {**sources,**caches}.items():
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
   def read():
    code='import sys,json\nsys.path.insert(0,'+repr(str(root/'runtime'))+')\ncompiled=[]\ndef audit(event,args):\n if event=="compile" and args[1]=='+repr(str(root/'runtime/probe.py'))+':compiled.append(1)\nsys.addaudithook(audit)\nimport probe\nprint(json.dumps([probe.answer,len(compiled)]))'
    return json.loads(subprocess.check_output([sys.executable,'-I','-B','-c',code]))
   self.assertEqual(read(),[7,0])
   (root/'runtime/probe.py').write_bytes(b'answer=9\n')
   self.assertEqual(read(),[9,1])
   # A different interpreter's bytecode cannot override the retained source.
   cache=root/next(iter(caches));cache.write_bytes(b'xxxx'+cache.read_bytes()[4:])
   self.assertEqual(read(),[9,1])
 def test_bad_paths_hashes_and_unchecked_cache_are_rejected(self):
  source=b'answer=1\n';request={'sources':{'runtime/probe.py':base64.b64encode(source).decode()},'installedRoot':'/installed'}
  original=build_bytecode._worker(request)
  for field,change in [('path','../probe.pyc'),('sourceSha256','0'*64),('data',None)]:
   value=json.loads(json.dumps(original))
   if field=='data':
    data=bytearray(base64.b64decode(value['files'][0]['data']));data[4:8]=(1).to_bytes(4,'little');change=base64.b64encode(data).decode()
   value['files'][0][field]=change
   with patch.object(build_bytecode.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(value),'')):
    with self.assertRaises(ValueError):build_bytecode.compile_files({'runtime/probe.py':source},sys.executable,'/installed')
 @unittest.skipUnless(shutil.which('clang'),'Clang required')
 def test_packaged_caches_are_pinned_and_missing_or_changed_cache_is_rejected(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);manifest=build_integrated.build(root/'package',bytecode_python=sys.executable)
   raw=(root/'package'/manifest['package']['package']).read_bytes()
   with tarfile.open(fileobj=io.BytesIO(build_support.read_ar(raw)['data.tar.gz']),mode='r:gz') as archive:
    for member in archive:
     if not member.isfile():continue
     path=root/'unpacked'/member.name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.extractfile(member).read())
   service=root/'unpacked/usr/palm/services'/runtime_bundle.SERVICE
   package=root/'unpacked/usr/palm/packages'/runtime_bundle.APP
   for role in ('controller','receiver'):
    raw=(service/'pins'/(role+'.json')).read_bytes();self.assertLessEqual(len(raw),runtime_bundle.MAX_PIN_BYTES)
    pin=json.loads(raw);runtime_bundle.validate_pin(pin,role)
    caches=[name for name in pin['files'] if name.endswith('.pyc')]
    self.assertEqual(len(caches),manifest['bytecode']['files']);self.assertGreater(len(caches),100)
    self.assertTrue(runtime_bundle.package_matches(service/'roles'/role,package,pin))
    target=service/caches[0];original=target.read_bytes();target.write_bytes(original+b'changed')
    self.assertFalse(runtime_bundle.package_matches(service/'roles'/role,package,pin));target.write_bytes(original)
    target.unlink()
    with self.assertRaises(OSError):runtime_bundle.package_matches(service/'roles'/role,package,pin)
    target.write_bytes(original)

if __name__=='__main__':unittest.main()
