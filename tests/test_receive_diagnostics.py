import copy,importlib.util,json,os,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).resolve().parent

from output_bridge import VerifiedOutputs,KEYS
from borrowed_mode_session import BorrowedModeSession
from borrowed_sustained_receive import receive_sustained
from connected_status_watch import ConnectedStatusWatch,BoundConnectedView
from borrowed_control_guard import BorrowedControlGuard
from borrowed_gatt_view import TARGET,ADAPTER
from receive_diagnostics import valid,record_shape,KINDS,POINTER
from receiver_result_receipt import write_receipt
from receiver_result_reader import read_receipt
import fixture_devices as fixture
class View:
 generation=1
 def close(self):pass
class Lease:
 def held(self):return True

def sample():return b'\xfc\x04\x00'+struct.pack('<3f',0.,0.,0.)+b'\x00'*6

def details():
 return dict(endReason='control-or-policy-ended',receiverStopReason='control-lost',controlFailure='snapshot',watchState='stale',watchAgeMs=3001,reportShapes=[{'id':252,'length':21,'count':1}],shapeOverflow=0,decodedKinds=dict.fromkeys(KINDS,0),pointer=dict.fromkeys(POINTER,0),pointerCalibrated=False)

class Tests(unittest.TestCase):
 def outputs(self,sleep=lambda n:None):
  self.dev=fixture.MemoryDevices()
  return VerifiedOutputs(1,2,ioctl_fn=self.dev.ioctl,write_fn=self.dev.write,sleep_fn=sleep)
 def test_pulse_holds_before_release(self):
  seen=[]
  out=self.outputs(lambda n:seen.append((n,set(self.dev.held[1]))))
  out.key_pulse('right')
  self.assertEqual(seen,[(.08,{KEYS['right']})]);self.assertEqual(self.dev.held[1],set());self.assertEqual(out.key_writes,2)
 def test_interrupted_hold_still_releases(self):
  def interrupted(n):raise KeyboardInterrupt()
  out=self.outputs(interrupted)
  with self.assertRaises(KeyboardInterrupt):out.key_pulse('up')
  self.assertTrue(out.failed);self.assertEqual(self.dev.held[1],set())
 def test_short_down_does_not_wait_and_attempts_release(self):
  waits=[];out=self.outputs(waits.append);calls=[]
  original=out.write_fn
  def short(fd,packet):
   calls.append(packet)
   return len(packet)-1 if len(calls)==1 else original(fd,packet)
  out.write_fn=short
  with self.assertRaises(OSError):out.key_pulse('down')
  self.assertEqual(waits,[]);self.assertEqual(len(calls),2);self.assertEqual(self.dev.held[1],set())
 def test_sustained_real_pipeline_retains_shapes_and_parser_counts_on_control_loss(self):
  now=[0.];live=[True];stats={};out=self.outputs();frames=iter([sample(),b'\x01\x02'])
  session=BorrowedModeSession(View(),read_mode=lambda:0,read_stop_mode=lambda:0,write_mode=lambda _:True,control_valid=lambda:live[0],record=lambda _:True)
  session.state='active';session.control_diagnostic=lambda:{'failure':'snapshot','watchState':'stale','watchAgeMs':3001}
  def read(fd,size):
   try:return next(frames)
   except StopIteration:live[0]=False;raise BlockingIOError()
  with self.assertRaisesRegex(RuntimeError,'receive-unconfirmed'):
   receive_sustained(session,out,3,duration=None,abort=lambda:False,clock=lambda:now[0],read_fn=read,sleep_fn=lambda n:now.__setitem__(0,now[0]+n),stats=stats)
  d=stats['receiveDiagnostics'];self.assertTrue(valid(d));self.assertEqual(d['endReason'],'control-or-policy-ended');self.assertEqual(d['receiverStopReason'],'control-lost');self.assertEqual(d['watchState'],'stale');self.assertEqual(d['decodedKinds'],{'no-touch':1,'one-touch':0,'two-touch':0,'rejected':1});self.assertEqual(d['pointer']['validPose'],1);self.assertEqual(stats['bytesReceived'],23)
  self.assertEqual(d['reportShapes'],[{'id':252,'length':21,'count':1},{'id':1,'length':2,'count':1}]);self.assertTrue(out.verify_released())
 def test_first_control_failure_not_overwritten_by_cleanup(self):
  now=[0.];stats={};out=self.outputs();live=[True]
  session=BorrowedModeSession(View(),read_mode=lambda:0,read_stop_mode=lambda:0,write_mode=lambda _:True,control_valid=lambda:live[0],record=lambda _:True);session.state='active'
  session.control_diagnostic=lambda:{'failure':'external'}
  def read(fd,size):live[0]=False;return sample()
  with self.assertRaisesRegex(RuntimeError,'receive-unconfirmed'):
   receive_sustained(session,out,3,duration=None,abort=lambda:False,clock=lambda:now[0],read_fn=read,sleep_fn=lambda n:now.__setitem__(0,now[0]+n),stats=stats)
  session.state='attention';self.assertEqual(stats['receiveDiagnostics']['controlFailure'],'external')
 def test_requested_stop_remains_complete(self):
  stats={};out=self.outputs();session=BorrowedModeSession(View(),read_mode=lambda:0,read_stop_mode=lambda:0,write_mode=lambda _:True,control_valid=lambda:True,record=lambda _:True);session.state='active'
  r=receive_sustained(session,out,3,duration=None,abort=lambda:True,clock=lambda:0.,stats=stats)
  self.assertEqual(r['status'],'complete');self.assertEqual(stats['receiveDiagnostics']['endReason'],'stop-requested');self.assertEqual(stats['bytesReceived'],0)
 def test_shape_storage_is_bounded_and_has_no_payloads(self):
  stats={'reportShapes':[],'shapeOverflow':0}
  for i in range(30):record_shape(stats,bytes([i])+b'private payload')
  record_shape(stats,b'\0private payload')
  self.assertEqual(len(stats['reportShapes']),12);self.assertEqual(stats['shapeOverflow'],18);self.assertEqual(stats['reportShapes'][0]['count'],2)
  self.assertNotIn('private',json.dumps(stats))
 def test_watch_diagnostics_do_not_refresh_stale_state(self):
  now=[0.];w=ConnectedStatusWatch(clock=lambda:now[0]);p=dict(returnValue=True,address=TARGET,adapterAddress=ADAPTER,connected=True,connecting=False,connectRequest=False,subscribed=True)
  for role in ('hid','gatt'):w.event(role,p)
  w.commit_poll(w.begin_poll(),p,p);bound=BoundConnectedView(w,'012');g=BorrowedControlGuard(generation=1,client_id='012',lease=Lease(),profiles=bound.snapshot,clock=lambda:now[0])
  self.assertTrue(g());now[0]=3.001;self.assertFalse(g());self.assertEqual(g.last_failure,'snapshot');self.assertEqual(w.diagnostic(1)['watchState'],'stale');self.assertIsNone(w.snapshot())
  w.event('hid',{**p,'connected':False});self.assertEqual(w.diagnostic(1)['watchState'],'generation-changed');self.assertFalse(g());w.close();self.assertEqual(w.diagnostic(1)['watchState'],'closed')
 def test_validated_diagnostics_reject_extra_payload_and_invalid_counts(self):
  d=details();self.assertTrue(valid(d));d['raw']=b'secret';self.assertFalse(valid(d))
  d=details();d['pointer']['blocked']=True;self.assertFalse(valid(d))
  d=details();d['reportShapes']*=2;self.assertFalse(valid(d))
 def test_receipt_roundtrip_and_legacy_compatibility(self):
  for extended in (False,True):
   with self.subTest(extended=extended),tempfile.TemporaryDirectory() as t:
    directory=Path(t);directory.chmod(0o770);run='a'*32
    result=dict(run=run,status='attention',featureExclusivity='cooperative-only-unproven',readStats={})
    if extended:result['readStats']['receiveDiagnostics']=details()
    info=lambda:{'pid':os.getpid(),'startTicks':1,'status':{'Uid':' '.join([str(os.getuid())]*4),'Gid':'5000 5000 5000 5000','Groups':'5000','CapEff':'0000000000000000'}}
    write_receipt(directory,run,result,state_uid=os.getuid(),group=os.getgid(),process_info=info)
    path=directory/('receiver-result-'+run+'.json');self.assertLess(path.stat().st_size,4096)
    read=read_receipt(directory,run,state_uid=os.getuid(),group=os.getgid());self.assertEqual('receiveDiagnostics' in read,extended)
    if extended:
     read['receiveDiagnostics']['rawPayload']='private';path.write_text(json.dumps(read))
     with self.assertRaisesRegex(RuntimeError,'receive diagnostics invalid'):read_receipt(directory,run,state_uid=os.getuid(),group=os.getgid())
if __name__=='__main__':unittest.main()
