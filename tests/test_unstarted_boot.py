"""An accepted launch interrupted by reboot must not permanently block input."""
import json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime/vendor'))
import orphan_reconcile as mod
class RecoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.a=self.root/'a';self.b=self.root/'b';self.a.mkdir();self.b.mkdir()
  self.run='a'*32;self.uid=os.getuid();self.group=os.getgid();self.boot=int(time.time());self.intent={'run':self.run,'stage':'receiver-launch-intent','generation':1}
  self.put(self.a,'receiver-launch-intent.json',self.intent,0o640)
  self.put(self.b,'request.json',{'schema':1,'appId':'b','run':self.run,'expiresEpochMs':(self.boot-5)*1000},0o660)
  self.put(self.b,'controller-start.json',{'schema':1,'appId':'a','run':self.run,'process':{'pid':12345,'startTicks':6789,'status':{'Uid':' '.join([str(self.uid)]*4),'CapEff':'0000000000000000'}}},0o660)
  self.c=os.open(self.a,os.O_RDONLY);self.d=os.open(self.b,os.O_RDONLY)
  self.lease=type('Lease',(),{'dirfd':self.c,'held':lambda _s:True})()
  self.patches=[patch.object(mod,'_ended',return_value=True),patch.object(mod.att,'candidate_pids',return_value=[]),patch.object(mod.package,'package_matches',return_value=True)]
  for p in self.patches:p.start()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  os.close(self.c);os.close(self.d);self.tmp.cleanup()
 def put(self,folder,name,value,mode):
  p=folder/name;p.write_text(json.dumps(value));p.chmod(mode);os.utime(p,(self.boot-10,self.boot-10))
 def run_recovery(self):
  return mod._archive_unstarted_after_boot(c=self.c,b=self.d,intent=self.intent,intent_stat=(self.a/'receiver-launch-intent.json').stat(),controller_app=str(self.a),receiver_app=str(self.b),receiver_package='unused',pin={},lease=self.lease,owner=self.uid,group=self.group,boot_time=self.boot)
 def test_reboot_before_receiver_start_archives_without_success_receipt(self):
  originals={n:(self.b/n).read_bytes() for n in ('request.json','controller-start.json')}
  result=self.run_recovery();self.assertEqual(result['priorOutcome'],'not-started-before-reboot')
  for name,raw in originals.items():self.assertEqual((self.b/(name[:-5]+'-unstarted-'+self.run+'.json')).read_bytes(),raw)
  self.assertFalse((self.a/'receiver-launch-intent.json').exists());self.assertFalse(list(self.b.glob('receiver-result-*')))
 def test_historical_platform_modes(self):
  for p in [*self.a.iterdir(),*self.b.iterdir()]:p.chmod(0o775)
  self.assertEqual(self.run_recovery()['status'],'reconciled')
 def test_current_boot_intent_is_retained(self):
  os.utime(self.a/'receiver-launch-intent.json',(self.boot+1,self.boot+1))
  with self.assertRaises(RuntimeError):self.run_recovery()
  self.assertTrue((self.b/'request.json').exists())
 def test_unexpired_preboot_request_is_retained(self):
  p=self.b/'request.json';q=json.loads(p.read_text());q['expiresEpochMs']=(self.boot+10)*1000;self.put(self.b,p.name,q,0o660)
  with self.assertRaises(RuntimeError):self.run_recovery()
 def test_started_receiver_or_journal_not_reclaimed(self):
  for name in ['receiver-start-'+self.run+'.json','receiver-result-'+self.run+'.json','borrowed-active','recovery-request.json']:
   p=self.b/name;p.write_text('{}');self.assertIsNone(self.run_recovery());p.unlink()
  self.assertTrue((self.b/'request.json').exists())
 def test_live_receiver_not_reclaimed(self):
  mod.att.candidate_pids.return_value=[123]
  with self.assertRaises(RuntimeError):self.run_recovery()
 def test_package_mismatch_not_reclaimed(self):
  mod.package.package_matches.return_value=False
  with self.assertRaises(RuntimeError):self.run_recovery()
 def test_wrong_run_not_reclaimed(self):
  p=self.b/'request.json';q=json.loads(p.read_text());q['run']='b'*32;self.put(self.b,p.name,q,0o660)
  with self.assertRaises(RuntimeError):self.run_recovery()
 def test_partial_archive_resumes(self):
  old=os.rename;calls=[]
  def interrupted(*args,**kwargs):
   calls.append(args)
   if len(calls)==2:raise OSError('simulated interruption')
   return old(*args,**kwargs)
  with patch.object(mod.os,'rename',side_effect=interrupted):
   with self.assertRaises(OSError):self.run_recovery()
  self.assertTrue((self.a/'receiver-launch-intent.json').exists())
  self.assertEqual(self.run_recovery()['status'],'reconciled')
 def test_lease_loss_after_first_archive_stops(self):
  old=os.rename
  def lose(*args,**kwargs):
   old(*args,**kwargs);self.lease.held=lambda:False
  with patch.object(mod.os,'rename',side_effect=lose):
   with self.assertRaises(RuntimeError):self.run_recovery()
  self.assertTrue((self.a/'receiver-launch-intent.json').exists())
 def test_duplicate_archive_not_overwritten(self):
  p=self.b/('request-unstarted-'+self.run+'.json');p.write_text('preserve')
  with self.assertRaises(RuntimeError):self.run_recovery()
  self.assertEqual(p.read_text(),'preserve')
 def test_symlink_not_followed(self):
  p=self.b/'request.json';saved=p.read_text();p.unlink();target=self.root/'foreign';target.write_text(saved);p.symlink_to(target)
  with self.assertRaises(OSError):self.run_recovery()
 def test_missing_file_exception_is_logged(self):
  from boot_diagnostics import BootTrace
  trace=BootTrace();trace.add('bootstrap-takeover-error-FileNotFoundError');self.assertEqual(len(trace.events),1)
if __name__=='__main__':unittest.main()
