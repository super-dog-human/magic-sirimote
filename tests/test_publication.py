"""Public build/configuration checks, with no network or TV access."""
import hashlib,io,json,shutil,struct,subprocess,sys,tarfile,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import build,build_support,ir_packets
from system_buttons import SystemButtons

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.config=json.loads((ROOT/'config.example.json').read_text())
    def load(self,q,example=False):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'config.json';p.write_text(json.dumps(q))
            return build.load_config(p,example)
    def test_example_requires_explicit_flag(self):
        with self.assertRaises(ValueError):self.load(self.config)
        self.assertEqual(self.load(self.config,True),self.config)
    def test_invalid_target_fields_fail(self):
        for key,value in [('remoteName',"a'; do something"),('remoteAddress','ff:ff:ff:ff:ff:ff'),
                          ('controllerUid',True),('devmodeMaintenance','automatic'),('schema',True)]:
            with self.subTest(key=key),self.assertRaises(ValueError):self.load({**self.config,key:value},True)
        with self.assertRaises(ValueError):self.load({**self.config,'password':'do-not-accept'},True)
    def test_configuration_replaces_only_whole_uid_literals(self):
        q={**self.config,'developerUid':6001,'controllerUid':6002,'receiverUid':6003}
        self.assertEqual(build.configured('5415 6959 5636 a5415 54150',q),b'6001 6002 6003 a5415 54150')
    def test_buttons_hold_and_chord_do_not_duplicate(self):
        actions=[];d=SystemButtons(actions.append);d.bind(1)
        for mask in [0,32,32,0,16,16,0,48,32,0,1,0,8]:d.feed(1,bytes([0xfc,0,mask]))
        self.assertEqual(actions,['settings','back','home','playpause'])
    def test_ir_encoder_matches_observed_power_packet(self):
        self.assertEqual(ir_packets.encode_entry(1,2,bytes.fromhex('20df10ef')),bytes.fromhex('f001010201000000000020df10ef'))
        self.assertEqual(ir_packets.encode_delete(1,5),bytes.fromhex('f0020105'))
        with self.assertRaises(ValueError):ir_packets.encode_entry(3,2,b'abcd')
    @unittest.skipUnless(shutil.which('clang'),'Clang required for package verification')
    def test_packages_are_reproducible_and_pins_match_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=Path(tmp)/'one';second=Path(tmp)/'two'
            a=build.build(self.config,first,True);b=build.build(self.config,second,True)
            self.assertTrue(a['exampleOnly']);self.assertFalse(a['hardwareValidatedPublicBuild'])
            all_files={}
            for role in ('controller','receiver','scheduler'):
                row=a[role];raw=(first/row['package']).read_bytes()
                self.assertEqual(raw,(second/b[role]['package']).read_bytes())
                self.assertEqual(hashlib.sha256(raw).hexdigest(),row['packageSha256'])
                parts=build_support.read_ar(raw)
                with tarfile.open(fileobj=io.BytesIO(parts['data.tar.gz']),mode='r:gz') as tar:
                    files={m.name:tar.extractfile(m).read() for m in tar if m.isfile()}
                self.assertEqual({n:hashlib.sha256(v).hexdigest() for n,v in files.items()},row['files'])
                prefix='usr/palm/applications/'+row['appId']+'/'
                for name,digest in row['pin']['files'].items():
                    self.assertEqual(hashlib.sha256(files[prefix+name]).hexdigest(),digest)
                entry=files[prefix+'entry'];self.assertEqual(entry[:7],b'\x7fELF\x01\x01\x01')
                self.assertEqual(struct.unpack_from('<H',entry,18)[0],40)
                for name,content in files.items():
                    self.assertNotIn(b'/' + b'Users/',content)
                    if name.endswith('.py'):compile(content,name,'exec')
                all_files.update(files)
            root='usr/palm/services/'+build.S+'.service/'
            pins=all_files[root+'pins.js'].decode().split('module.exports=',1)[1].rstrip(';\n')
            self.assertEqual(json.loads(pins),{'controller':a['controller']['pin'],'receiver':a['receiver']['pin']})
            self.assertIn(b"expiryRun=require('./expiry-policy').run",all_files[root+'service.js'])
            self.assertIn(b"const POLICY='disabled'",all_files[root+'expiry-policy.js'])
            with self.assertRaises(ValueError):build.build(self.config,first,True)

if __name__=='__main__':unittest.main()
