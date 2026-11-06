import json, os, sys, tempfile, unittest, shutil
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
import preio_recovery as recovery
class PreioRecoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.c=self.root/'c';self.b=self.root/'b'
  for p in (self.c,self.b):p.mkdir();p.chmod(0o770)
  self.run='a'*32
  self.old={'pid':123,'startTicks':1,'status':{'Uid':' '.join([str(os.getuid())]*4),'CapEff':'0000000000000000'}}
  self.process={**self.old,'pid':456,'startTicks':2};self.prior={'process':self.old,'priorOutcome':'attention'}
  self.start={'schema':1,'appId':recovery.APP,'run':self.run,'stage':'starting','process':self.process,'rawReportsPersisted':False}
  self.result={'schema':1,'appId':recovery.APP,'run':self.run,'status':'attention','diagnostic':'other-RuntimeError','frameCounts':None,'readStats':None,'phase':None,'previousPhase':None,'failureType':'RuntimeError','sensorStopVerified':False,'journalArchived':False,'featureExclusivity':'cooperative-only-unproven','counts':None,'process':self.process,'rawReportsPersisted':False}
  self.write(self.b/('receiver-recovery-start-'+self.run+'.json'),self.start)
  self.write(self.b/('receiver-recovery-result-'+self.run+'.json'),self.result)
  self.write(self.b/('recovery-'+self.run+'-1.json'),{'run':self.run,'stage':'recovery-intent','priorSensorState':'uncertain','priorOutcome':'attention'})
  self.request={'schema':2,'appId':recovery.APP,'run':self.run,'expiresEpochMs':1000,'priorProcess':self.old,'gattLookupReply':{'returnValue':True}}
  self.write(self.b/'recovery-request.json',self.request,0o660)
  self.controller={'schema':1,'appId':recovery.CONTROLLER,'run':self.run,'process':self.old}
  self.write(self.b/'controller-start.json',self.controller,0o660)
  for kind in ('intent','reply','stable'):
   v={'run':self.run,'generation':1}
   if kind=='reply':v={'run':self.run,'ownership':'unproven','reply':self.request['gattLookupReply']}
   self.write(self.c/('recovery-gatt-'+self.run+'-'+kind+'.json'),v)
  (self.b/'borrowed-active').mkdir();(self.b/'borrowed-active'/'journal').write_text('UNCERTAIN - retain')
  self.args=dict(run=self.run,controller_state=self.c,receiver_state=self.b,controller_app='/c',receiver_app='/b',proof=lambda:True,prior=self.prior,state_uid=os.getuid(),group=os.getgid(),now_ms=2000,native_idle=lambda:True)
  for name in ('_ended','validate_reply'):
   p=patch.object(recovery,name,return_value=True);p.start();self.addCleanup(p.stop)
  self.before=self.contents()
 def write(self,p,v,mode=0o640):p.write_text(json.dumps(v));p.chmod(mode)
 def contents(self):return {str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
 def test_preflight_failure_can_retry_without_losing_original_journal(self):
  self.assertTrue(recovery.retire(**self.args));after=self.contents()
  self.assertEqual(sorted(after.values()),sorted(self.before.values()))
  for name in ('b/borrowed-active/journal','b/controller-start.json'):self.assertEqual(after[name],self.before[name])
  self.assertFalse((self.b/'recovery-request.json').exists())
 def test_takeover_record_is_archived_when_present(self):
  self.write(self.b/'recovery-controller-start.json',self.controller,0o660)
  self.assertTrue(recovery.retire(**self.args));self.assertFalse((self.b/'recovery-controller-start.json').exists())
  self.assertTrue((self.b/'controller-start.json').exists())
 def test_device_io_intent_or_unknown_lookup_blocks(self):
  for p in (self.b/('recovery-'+self.run+'-2.json'),self.b/'recovery-active',self.c/('recovery-gatt-'+self.run+'-unknown.json')):
   p.write_text('{}');before=self.contents()
   with self.assertRaises(RuntimeError):recovery.retire(**self.args)
   self.assertEqual(before,self.contents());p.unlink()
 def test_no_success_or_sensor_stop_is_inferred(self):
  path=self.b/('receiver-recovery-result-'+self.run+'.json')
  for key,value in [('sensorStopVerified',True),('status','recovered'),('phase','prepare'),('process',self.old),('readStats',{})]:
   self.write(path,{**self.result,key:value});before=self.contents()
   with self.assertRaises(RuntimeError):recovery.retire(**self.args)
   self.assertEqual(before,self.contents())
 def test_live_process_open_ui_or_lost_proof_blocks(self):
  for key in ('process','native_idle','proof'):
   args=dict(self.args)
   if key!='process':args[key]=lambda:False
   with patch.object(recovery,'_ended',return_value=key!='process'):
    with self.assertRaises(RuntimeError):recovery.retire(**args)
   self.assertEqual(self.before,self.contents())
 def test_bad_request_or_permissions_blocks(self):
  path=self.b/'recovery-request.json'
  for kind in ('expiry','prior','mode','missing'):
   v=dict(self.request)
   if kind=='expiry':v['expiresEpochMs']=2000
   if kind=='prior':v['priorProcess']=self.process
   self.write(path,v,0o666 if kind=='mode' else 0o660)
   if kind=='missing':path.unlink()
   before=self.contents()
   with self.assertRaises((RuntimeError,OSError)):recovery.retire(**self.args)
   self.assertEqual(before,self.contents())
 def test_interrupted_moves_resume_with_exact_bytes(self):
  rename=os.rename
  for count in range(1,8):
   with self.subTest(count=count):
    calls=[0]
    def interrupt(*a,**kw):
     rename(*a,**kw);calls[0]+=1
     if calls[0]==count:raise OSError('interrupted')
    with patch.object(recovery.os,'rename',side_effect=interrupt):
     with self.assertRaises(OSError):recovery.retire(**self.args)
    self.assertTrue(recovery.retire(**self.args))
    self.assertEqual(sorted(self.contents().values()),sorted(self.before.values()))
    for p in self.root.iterdir():shutil.rmtree(p)
    self.c.mkdir();self.b.mkdir();self.c.chmod(0o770);self.b.chmod(0o770)
    for name,raw in self.before.items():
     p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
     p.chmod(0o660 if p.name in ('recovery-request.json','controller-start.json') else 0o640)
 def test_receiver_records_require_receiver_owner_not_controller_owner(self):
  foreign=os.getuid()+17
  self.old={**self.old,'status':{**self.old['status'],'Uid':' '.join([str(foreign)]*4)}}
  self.prior['process']=self.old;self.process={**self.process,'status':dict(self.old['status'])}
  self.start['process']=self.process;self.result['process']=self.process;self.request['priorProcess']=self.old
  self.write(self.b/('receiver-recovery-start-'+self.run+'.json'),self.start)
  self.write(self.b/('receiver-recovery-result-'+self.run+'.json'),self.result)
  self.write(self.b/'recovery-request.json',self.request,0o660)
  original=recovery._read;seen=[]
  def read(fd,name,owner,group,mode,**kwargs):
   expected=foreign if 'receiver-recovery-' in name or name=='recovery-'+self.run+'-1.json' else os.getuid()
   self.assertEqual(owner,expected);seen.append(owner)
   return original(fd,name,os.getuid(),group,mode,**kwargs)
  with patch.object(recovery,'_read',side_effect=read):self.assertTrue(recovery.retire(**self.args))
  self.assertEqual(seen.count(foreign),3)
 def test_new_event_during_archive_stops_further_moves(self):
  rename=os.rename;calls=[]
  def extra(*a,**kw):
   rename(*a,**kw);calls.append(a);self.write(self.b/('recovery-'+self.run+'-2.json'),{'stage':'unexpected'})
  with patch.object(recovery.os,'rename',side_effect=extra):
   with self.assertRaises(RuntimeError):recovery.retire(**self.args)
  self.assertEqual(len(calls),1);self.assertTrue((self.b/'recovery-request.json').exists())
if __name__=='__main__':unittest.main()
