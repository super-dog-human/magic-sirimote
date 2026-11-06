import errno
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from early_navigation import EarlyNavigation
from borrowed_mode_session import BorrowedModeSession
from output_bridge import VerifiedOutputs, KEY_ENTER
from fixture_devices import MemoryDevices
from test_swipe_click import touch
from normalize import normalize

class Tests(unittest.TestCase):
 def setUp(self):
  self.now=0.;self.allowed=True;self.aborted=False;self.queue=[]
  self.device=MemoryDevices()
  self.outputs=VerifiedOutputs(1,2,ioctl_fn=self.device.ioctl,write_fn=self.device.write,sleep_fn=lambda _:None)
  self.reads=0
  def read(fd,size):
   self.assertEqual((fd,size),(8,4096));self.reads+=1
   if not self.queue:raise BlockingIOError()
   return self.queue.pop(0)
  self.early=EarlyNavigation(self.outputs,8,generation=7,guard=lambda:self.allowed,abort=lambda:self.aborted,clock=lambda:self.now,read_fn=read)
  self.early.start()
 def feed(self,report):
  self.now+=.02;self.queue.append(report);self.early.pump()
 def keys(self):return [(fd,code,value) for fd,events in self.device.writes for _,_,kind,code,value in events if kind==1]
 def swipe(self):
  self.feed(b'\xfc\0\0')
  for value in (touch(-1500,-200,state=3),touch(-1000,-200,state=4),touch(-1000,-200,state=7)):
   self.feed(b'\xfc'+value)
  self.now+=.1;self.early.pump()
 def session(self,generation=7):
  view=SimpleNamespace(generation=generation,close=lambda:None)
  session=BorrowedModeSession(view,read_mode=lambda:0,read_stop_mode=lambda:0,write_mode=lambda _:True,control_valid=lambda:True,record=lambda _:True)
  session.state='active';return session
 def adopt(self,session=None):
  return self.early.adopt(session or self.session(),live=lambda:True,outputs=self.outputs,fd=8)
 def test_legacy_swipe_outputs_before_sensor_mode_is_ready(self):
  self.swipe();self.assertEqual(self.keys(),[(1,106,1),(1,106,0)])
  self.assertFalse(self.early.rolling.receiver.bridge.sensor_input_verified)
 def test_no_motion_output_or_tracking_before_sensor_confirmation(self):
  for angle in (0.,.01,.02,.1,.2):
   frame=b'\xfc\x04\0'+struct.pack('<3f',angle,0.,0.)+bytes(6)
   self.feed(frame)
  self.assertEqual(self.device.writes,[])
  self.assertFalse(self.early.rolling.receiver.bridge.sensor_input_verified)
  self.assertEqual(self.early.rolling.complete_frames,0)
  self.assertIsNone(self.early.rolling.receiver.router.pose.last_pose)
 def test_press_spans_adoption_without_duplicate_or_lost_release(self):
  self.swipe();self.feed(b'\xfc\0\x80')
  original=self.early.receiver
  pipeline=self.adopt();self.assertIs(pipeline,original)
  self.now+=.02;pipeline.feed_raw(1,b'\xfc\0\0');pipeline.tick()
  self.assertEqual(self.keys()[-2:],[(1,KEY_ENTER,1),(1,KEY_ENTER,0)])
  self.assertTrue(self.outputs.verify_released())
  prior=self.reads;self.early.pump();self.assertEqual(self.reads,prior)
 def test_stale_generation_cannot_adopt(self):
  with self.assertRaises(RuntimeError):self.adopt(self.session(8))
  self.assertFalse(self.early.adopted)
 def test_unverified_sensor_session_cannot_adopt(self):
  session=self.session();session.state='starting'
  with self.assertRaises(RuntimeError):self.adopt(session)
 def test_guard_loss_releases_held_selection_without_more_reads(self):
  self.swipe();self.feed(b'\xfc\0\x80');prior=self.reads;self.allowed=False
  with self.assertRaises(RuntimeError):self.early.pump()
  self.assertEqual(self.reads,prior);self.assertTrue(self.outputs.verify_released())
 def test_guard_changes_during_read_discards_report(self):
  def read(*args):self.allowed=False;return b'\xfc\0\x80'
  self.early.read=read
  with self.assertRaises(RuntimeError):self.early.pump()
  self.assertEqual(self.device.writes,[])
 def test_read_disconnect_closes_pipeline(self):
  def read(*args):raise OSError(errno.EIO,'disconnect')
  self.early.read=read
  with self.assertRaises(OSError):self.early.pump()
  self.assertTrue(self.early.closed);self.assertTrue(self.outputs.verify_released())
 def test_stop_is_idempotent(self):
  self.swipe();self.feed(b'\xfc\0\x80');self.early.stop();writes=list(self.device.writes)
  self.early.stop();self.early.pump();self.assertEqual(self.device.writes,writes)
 def test_foreign_audio_and_malformed_touch_not_normalized(self):
  for frame in (b'\xfc\x10\0',b'\xfc'+touch(-1000,-200)[:-1],b'\xfb'+touch(-1000,-200),b'\xfc\0\0\0'):
   self.assertIsNone(normalize(frame))
 def test_legacy_frames_never_manufacture_orientation(self):
  for frame in (b'\xfc\0\0',b'\xfc'+touch(-1000,-200)):
   self.assertIsNone(normalize(frame)['orientation3'])
 def test_motion_only_opens_on_new_frame_after_active_handoff(self):
  pipeline=self.adopt()
  self.assertFalse(self.early.rolling.receiver.bridge.sensor_input_verified)
  pipeline.feed_raw(1,b'\xfc\x04\0'+struct.pack('<3f',0.,0.,0.)+bytes(6))
  self.assertTrue(self.early.rolling.receiver.bridge.sensor_input_verified)

class CleanupTests(unittest.TestCase):
 def test_navigation_stops_before_sensor_cleanup_even_if_release_fails(self):
  from borrowed_session_runner import run_once
  events=[]
  class Session:
   def start(self):events.append('start');raise RuntimeError('start failed')
   def stop(self):events.append('sensor-stop');return {'status':'stopped','modeZeroVerified':True,'gattDisconnectCalls':0,'clientOwnership':'unproven'}
  def stop_input():events.append('input-stop');raise OSError('release failed')
  result=run_once(lambda:Session(),lambda _:None,before_stop=stop_input)
  self.assertEqual(events,['start','input-stop','sensor-stop']);self.assertTrue(result['sensorStopVerified'])


class EntryIntegrationTests(unittest.TestCase):
 def test_navigation_is_processed_during_prepare_and_pipeline_survives_activation(self):
  import postconnect_receiver_entry as entry
  from borrowed_gatt_view import TARGET,ADAPTER
  from unittest.mock import Mock
  now=[0.];active=[False];stopped=[False];effects=[]
  device=MemoryDevices();outputs=VerifiedOutputs(1,2,ioctl_fn=device.ioctl,write_fn=device.write,sleep_fn=lambda _:None)
  original_close=outputs.close;outputs.close=lambda:original_close(close_fn=lambda _:None)
  packets=[b'\xfc\0\0',b'\xfc'+touch(-1500,-200,state=3),b'\xfc'+touch(-1000,-200,state=4),b'\xfc'+touch(-1000,-200,state=7),b'\xfc\0\x80',b'\xfc\0\0']
  def read(fd,size):
   now[0]+=.02
   if packets:return packets.pop(0)
   stopped[0]=True;raise BlockingIOError()
  profile={'returnValue':True,'address':TARGET,'adapterAddress':ADAPTER,'connected':True,'connecting':False,'connectRequest':False}
  watch=Mock();watch.snapshot.side_effect=lambda:{'generation':7,'observedAt':now[0],'hid':dict(profile),'gatt':dict(profile)}
  lease=Mock();lease.held.return_value=True
  def prepare(**kwargs):
   pump=kwargs['pump']
   for _ in range(5):pump()
   # Both swipe and press-down have already happened before sensor start.
   effects.append([(code,value) for _,events in device.writes for _,_,kind,code,value in events if kind==1])
   mode=[0]
   def read_mode():
    if mode[0]==1:active[0]=True
    return mode[0]
   def write_mode(value):mode[0]=value;return True
   return BorrowedModeSession(SimpleNamespace(generation=7,close=lambda:None),read_mode=read_mode,read_stop_mode=lambda:mode[0],write_mode=write_mode,control_valid=lambda:True,record=lambda _:True)
  with patch('runtime_bundle.active',return_value=True),patch.object(entry.borrowed_runtime,'initialize_input',return_value=object()),patch.object(entry.borrowed_runtime,'prepare',side_effect=prepare):
   result=entry.run_connected_once(watch=watch,lease=lease,paired_check=lambda:True,external_feature_guard=lambda:True,record=lambda _:True,open_target=lambda:8,open_outputs=lambda:outputs,close_target=lambda _:None,duration=None,abort=lambda:stopped[0],clock=lambda:now[0],read_fn=read,sleep_fn=lambda _:None,on_ready=lambda _:active[0])
  self.assertEqual(effects,[[(106,1),(106,0),(KEY_ENTER,1)]])
  keys=[(code,value) for _,events in device.writes for _,_,kind,code,value in events if kind==1]
  self.assertEqual(keys,[(106,1),(106,0),(KEY_ENTER,1),(KEY_ENTER,0)])
  self.assertEqual(result['status'],'complete',result)
  self.assertTrue(result['sensorStopVerified']);self.assertTrue(outputs.verify_released())
  self.assertEqual(result['readStats']['earlyInput']['reports'],5)

if __name__=='__main__':unittest.main()
