import unittest,importlib.util,tempfile,json,hashlib,os
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('resume_evidence',Path(__file__).resolve().parents[2]/'src/scheduler/resume-evidence.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.root=self.base/'apps';self.proc=self.base/'proc';self.proc.mkdir();(self.proc/'uptime').write_text('100.00 0.0');self.a=self.root/m.A/'state';self.b=self.root/m.B/'state';self.a.mkdir(parents=True);self.b.mkdir(parents=True);self.run='a'*32;self.instance='b'*32
  self.cp={'pid':100,'startTicks':1000,'status':{'Uid':'6959\t6959\t6959\t6959'}};self.rp={'pid':101,'startTicks':1100,'status':{'Uid':'5636\t5636\t5636\t5636'}}
  self.write(self.b/('receiver-ready-'+self.run+'.json'),{'appId':m.B,'run':self.run,'stage':'receiver-ready','pid':101,'startTicks':1100,'epochMs':950000})
  self.write(self.b/('receiver-result-'+self.run+'.json'),{'appId':m.B,'run':self.run,'status':'complete','sensorStopVerified':True,'journalArchived':True,'process':self.rp})
  self.write(self.b/'controller-start.json',{'appId':m.A,'run':self.run,'process':self.cp})
  self.write(self.a/('controller-instance-'+self.instance+'.json'),{'pid':100,'startTicks':1000,'instance':self.instance})
  j=self.b/('borrowed-complete-'+self.run);j.mkdir();self.write(j/'01.json',{'run':self.run,'stage':'sensor-zero-confirmed'})
  self.readpatch=patch.object(m,'read',lambda p,*a,**k:(m.strict(p.read_bytes()),hashlib.sha256(p.read_bytes()).hexdigest()));self.readpatch.start()
  self.statpatch=patch.object(m.os,'stat',wraps=os.stat)
  # Only the completed directory's ownership differs on the test host.
  self.original_lstat=Path.lstat
  def lstat(p,*a,**k):
   s=self.original_lstat(p,*a,**k)
   if p==j:
    class Meta:st_mode=s.st_mode;st_uid=5636;st_gid=5000
    return Meta()
   return s
  self.lstatpatch=patch.object(Path,'lstat',lstat);self.lstatpatch.start()
 def tearDown(self):self.lstatpatch.stop();self.readpatch.stop();self.tmp.cleanup()
 def write(self,p,v):p.write_text(json.dumps(v))
 def result(self):return m.inspect(self.root,self.proc,now=lambda:1000.)
 def test_clean_current_boot_run_eligible(self):self.assertTrue(self.result()['eligible'])
 def test_manual_stop_not_restarted(self):self.write(self.a/('developer-stop-'+self.instance+'.json'),{});self.assertEqual(self.result()['reason'],'manual-stop-retained')
 def test_current_controller_running_not_restarted(self):
  p=self.proc/'100';p.mkdir();(p/'cmdline').write_bytes(str(self.root/m.A/'native_probe.py').encode()+b'\0');self.assertEqual(self.result()['reason'],'input-program-live')
 def test_active_journal_blocks_restart(self):(self.b/'borrowed-active').mkdir();self.assertFalse(self.result()['eligible'])
 def test_uncertain_sensor_stop_blocks_restart(self):
  f=self.b/('receiver-result-'+self.run+'.json');v=json.loads(f.read_text());v['sensorStopVerified']=False;self.write(f,v);self.assertFalse(self.result()['eligible'])
 def test_previous_boot_run_not_eligible(self):
  f=self.b/('receiver-ready-'+self.run+'.json');v=json.loads(f.read_text());v['epochMs']=800000;self.write(f,v);self.assertFalse(self.result()['eligible'])
 def test_newest_ready_without_result_prevents_older_resume(self):
  v=json.loads((self.b/('receiver-ready-'+self.run+'.json')).read_text());v.update(run='c'*32,epochMs=960000);self.write(self.b/('receiver-ready-'+v['run']+'.json'),v);self.assertEqual(self.result()['reason'],'result-unavailable')
 def test_archived_controller_record_is_supported(self):
  (self.b/'controller-start.json').rename(self.b/('controller-start-complete-'+self.run+'.json'));self.assertTrue(self.result()['eligible'])
 def test_newer_intent_blocks_restart(self):self.write(self.a/'receiver-launch-intent.json',{'run':'c'*32});self.assertFalse(self.result()['eligible'])
 def test_journal_missing_zero_rejected(self):
  self.write(self.b/('borrowed-complete-'+self.run)/'01.json',{'run':self.run,'stage':'sensor-stop-intent'})
  with self.assertRaises(ValueError):self.result()
if __name__=='__main__':unittest.main()
