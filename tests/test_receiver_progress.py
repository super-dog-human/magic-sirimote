import json,os,tempfile,unittest
from pathlib import Path
from receiver_progress import BoundedProgress,snapshot,valid,write_progress
from test_receive_diagnostics import View,sample
import test_receive_diagnostics as fixture
from unittest.mock import patch
from borrowed_mode_session import BorrowedModeSession
from borrowed_sustained_receive import receive_sustained

class Tests(unittest.TestCase):
 def session(self):
  s=BorrowedModeSession(View(),read_mode=lambda:0,read_stop_mode=lambda:0,write_mode=lambda _:True,control_valid=lambda:True,record=lambda _:True)
  s.state='active';return s
 def test_frequency_and_lifetime_bound(self):
  now=[0.];rows=[];p=BoundedProgress(lambda r:rows.append(r) or True,clock=lambda:now[0])
  for i in range(30000):
   now[0]=i*.01;p.maybe(lambda:{})
  self.assertEqual(len(rows),25)
 def test_diagnostic_failure_is_disabled_without_retry(self):
  calls=[]
  def fail(v):calls.append(v);raise OSError('failure')
  p=BoundedProgress(fail,clock=lambda:0.)
  for _ in range(10):p.maybe(lambda:{})
  self.assertTrue(p.disabled);self.assertEqual(len(calls),1)
 def test_snapshots_never_copy_raw_data(self):
  v=snapshot({'raw':'secret','current':{'router':{'pointer':{'raw':'secret','calibrated':True}}}})
  self.assertTrue(valid(v));self.assertNotIn('secret',json.dumps(v))
  self.assertFalse(valid({**v,'raw':'secret'}))
 def test_atomic_receipt_updates_and_rejects_symlink(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);root.chmod(0o770);run='a'*32;s=self.session();v=snapshot({})
   kw=dict(state_uid=os.getuid(),group=os.getgid(),clock=lambda:1.,start_ticks=lambda:7)
   self.assertTrue(write_progress(root,run,s,v,**kw));v['pointerCalibrated']=True
   self.assertTrue(write_progress(root,run,s,v,**kw))
   f=root/('receiver-progress-'+run+'.json');self.assertTrue(json.loads(f.read_text())['pointerCalibrated'])
   self.assertLess(f.stat().st_size,2048);self.assertEqual(f.stat().st_mode&0o777,0o640)
   f.unlink();other=root/'other';other.write_text('keep');f.symlink_to(other)
   with self.assertRaises(RuntimeError):write_progress(root,run,s,v,**kw)
   self.assertEqual(other.read_text(),'keep');self.assertFalse(Path(str(f)+'.tmp').exists())
 def test_real_pipeline_observes_calibration_and_ends_cleanly(self):
  now=[0.];rows=[];stats={};out=fixture.Tests().outputs()
  def read(*args):now[0]+=.01;return sample()
  r=receive_sustained(self.session(),out,3,duration=None,abort=lambda:now[0]>=6,clock=lambda:now[0],read_fn=read,stats=stats,on_progress=lambda v:rows.append(v) or True)
  self.assertEqual(r['status'],'complete');self.assertEqual(len(rows),2)
  self.assertFalse(rows[0]['pointerCalibrated']);self.assertTrue(rows[1]['pointerCalibrated'])
  self.assertTrue(out.verify_released())
 def test_progress_io_failure_does_not_stop_real_input(self):
  now=[0.];out=fixture.Tests().outputs();calls=[]
  def read(*args):now[0]+=.01;return sample()
  def fail(value):calls.append(value);raise OSError('unavailable')
  r=receive_sustained(self.session(),out,3,duration=None,abort=lambda:now[0]>=6,clock=lambda:now[0],read_fn=read,on_progress=fail)
  self.assertEqual(r['status'],'complete');self.assertEqual(len(calls),1)
 def test_entry_forwards_live_session_and_media_progress(self):
  import postconnect_receiver_entry as entry
  class Watch:
   def snapshot(self):return {'generation':1}
  class Sink:
   def pulse(self,*args):return True
   def verify_released(self):return True
  out=fixture.Tests().outputs();out.close=lambda:None
  session=self.session();seen=[]
  def run(prepare,receive,**kwargs):return receive(session)
  def media(s,outputs,fd,**kwargs):
   self.assertIs(s,session);self.assertTrue(kwargs['on_ready']())
   self.assertTrue(kwargs['on_progress'](snapshot({})))
   return {'status':'complete'}
  with patch.object(entry.borrowed_runtime,'initialize_input',return_value=object()),patch.object(entry,'run_once',side_effect=run),patch.object(entry,'receive_with_media',side_effect=media):
   r=entry.run_connected_once(watch=Watch(),lease=None,paired_check=lambda:True,external_feature_guard=lambda:True,record=lambda _:True,open_target=lambda:3,open_outputs=lambda:out,close_target=lambda _:None,duration=None,abort=lambda:False,clock=lambda:0.,open_system_keys=lambda:(Sink(),4),close_system_keys=lambda _:None,on_progress=lambda s,v:seen.append((s,v)) or True)
  self.assertEqual(r['status'],'complete');self.assertEqual(len(seen),1);self.assertIs(seen[0][0],session)

if __name__=='__main__':unittest.main()
