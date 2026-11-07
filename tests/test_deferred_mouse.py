import errno,json,os,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from types import SimpleNamespace
import output_devices as devices
from deferred_mouse import DeferredMouse,verify_records
from output_bridge import VerifiedOutputs,KEY_ENTER,BTN_LEFT,EVENT,_frame
from grouped_prefix_output import GroupedPrefixOutput
from fixture_devices import MemoryDevices
from test_rcu_output_device import Inventory


def open_inventory(f,**options):
 return devices.open_verified_outputs(lstat_fn=f.lstat,open_fn=f.open,fstat_fn=f.fstat,
  ioctl_fn=f.ioctl,close_fn=f.close,clock=lambda:0.,**options)

class DiscoveryTests(unittest.TestCase):
 def test_navigation_only_requires_explicit_permission(self):
  f=Inventory();del f.names[9]
  with self.assertRaises(devices.OutputInventoryIncomplete):open_inventory(f)
  out,records,_=open_inventory(f,allow_missing_mouse=True)
  self.assertEqual(len(records),1);self.assertFalse(out.pointer_ready)
  self.assertTrue(out.verify_released());self.assertTrue(out.best_effort_release())
  closed=[];out.close(close_fn=closed.append);self.assertEqual(closed,[100])
 def test_partial_mode_does_not_allow_invalid_inventory(self):
  for defect in ('duplicate','capability','unreadable'):
   f=Inventory();del f.names[9]
   if defect=='duplicate':f.names[12]='LGE RCU'
   elif defect=='capability':f.missing_enter=True
   else:
    original=f.open
    def blocked(path,flags):
     if path.endswith('event4'):raise PermissionError(errno.EACCES,'denied')
     return original(path,flags)
    f.open=blocked
   with self.assertRaises(devices.OutputInventoryIncomplete):open_inventory(f,allow_missing_mouse=True)
   self.assertEqual(f.rw,[])
 def test_partial_selection_is_not_reused_after_idle(self):
  f=Inventory();del f.names[9];reopen=Mock()
  select=devices.OutputSelection(scan=lambda **kwargs:open_inventory(f,**kwargs),reopen=reopen)
  out,records=select.open(allow_retry=lambda:True,wait=lambda _:None,allow_missing_mouse=True)
  self.assertIsNone(select.records);out.close(close_fn=f.close)
  f.names[9]='ClickableMouse'
  out,records=select.open(allow_retry=lambda:True,wait=lambda _:None,allow_missing_mouse=True)
  reopen.assert_not_called();self.assertEqual(len(select.records),2);out.close(close_fn=f.close)

class DeferredTests(unittest.TestCase):
 def make(self,**options):
  self.key={'path':'/dev/input/event0'}
  self.candidate=Mock(key_fd=11,mouse_fd=12,closed=False)
  self.candidate._managed_key_down.return_value=False
  self.owner=Mock(key_fd=1,mouse_fd=None,spare_key_fd=None)
  self.owner._managed_key_down.return_value=False
  self.records=[dict(self.key),{'path':'/dev/input/event9'}]
  self.verify=Mock();self.live=True
  return DeferredMouse(self.key,lambda:self.live,scan=lambda **_: (self.candidate,self.records,{}),verify=self.verify,**options)
 def test_transfers_once_and_preserves_held_key_destination(self):
  d=self.make();d.start();d.thread.join(2);self.assertFalse(d.thread.is_alive())
  self.owner._managed_key_down.return_value=True;d.poll(self.owner)
  self.assertIsNone(self.owner.mouse_fd);self.verify.assert_not_called()
  self.owner._managed_key_down.return_value=False
  d.poll(self.owner);d.poll(self.owner)
  self.assertEqual((self.owner.mouse_fd,self.owner.spare_key_fd),(12,11));self.verify.assert_called_once()
  d.close();self.candidate.close.assert_not_called();self.assertTrue(self.candidate.closed)
  self.assertIsNone(self.candidate.mouse_fd)
 def test_cancellation_joins_scan_and_closes_late_candidate(self):
  d=self.make();entered=threading.Event()
  def delayed(**kwargs):
   entered.set();kwargs['wait'](5)
   return self.candidate,self.records,{}
  d.scan=delayed;d.start();self.assertTrue(entered.wait(2))
  d.poll(self.owner);self.assertIsNone(self.owner.mouse_fd)
  d.close();d.close();self.assertFalse(d.thread.is_alive());self.candidate.close.assert_called_once()
 def test_final_owner_closes_all_transferred_descriptors_once(self):
  d=self.make();dev=MemoryDevices()
  owner=VerifiedOutputs(1,None,allow_missing_mouse=True,ioctl_fn=dev.ioctl)
  owner.mouse_provider=d;d.start();d.thread.join(2)
  self.assertTrue(owner.pointer_ready)
  closed=[];owner.close(close_fn=closed.append);owner.close(close_fn=closed.append)
  self.assertEqual(closed,[12,1,11]);self.candidate.close.assert_not_called()
 def test_guard_loss_cannot_adopt(self):
  d=self.make();d.start();d.thread.join(2);self.live=False
  with self.assertRaisesRegex(RuntimeError,'guard lost'):d.poll(self.owner)
  self.assertIsNone(self.owner.mouse_fd);d.close();self.candidate.close.assert_called_once()
 def test_changed_navigation_is_closed_not_adopted(self):
  d=self.make();self.records[0]['path']='/dev/input/event2';d.start();d.thread.join(2)
  with self.assertRaisesRegex(RuntimeError,'navigation output changed'):d.poll(self.owner)
  d.close();self.candidate.close.assert_called_once()
 def test_failed_fresh_verification_keeps_ownership_for_cleanup(self):
  d=self.make();self.verify.side_effect=RuntimeError('node changed');d.start();d.thread.join(2)
  with self.assertRaisesRegex(RuntimeError,'node changed'):d.poll(self.owner)
  self.assertIsNone(self.owner.mouse_fd);d.close();self.candidate.close.assert_called_once()
 def test_uncertain_discard_close_is_not_lost(self):
  d=self.make();self.candidate.close.side_effect=OSError('close failed')
  def revoked_during_scan(**kwargs):
   self.live=False
   return self.candidate,self.records,{}
  d.scan=revoked_during_scan
  d.start();d.thread.join(2)
  with self.assertRaises(OSError):d.poll(self.owner)
  with self.assertRaises(OSError):d.close()
 def test_scan_error_propagates_without_acquiring_descriptors(self):
  d=self.make();d.scan=Mock(side_effect=devices.OutputCloseError('uncertain'))
  d.start();d.thread.join(2)
  with self.assertRaises(devices.OutputCloseError):d.poll(self.owner)
  with self.assertRaises(devices.OutputCloseError):d.close()
 def test_fresh_verification_checks_saved_permissions(self):
  f=Inventory();out,records,_=open_inventory(f)
  with patch('deferred_mouse.os.fstat',f.fstat),patch('deferred_mouse.os.lstat',f.lstat):
   verify_records(out,records)
   records[1]['mode']='0o666'
   with self.assertRaisesRegex(RuntimeError,'mode changed'):verify_records(out,records)
  out.close(close_fn=f.close)

class EarlyInputTests(unittest.TestCase):
 def make(self):
  self.now=0.;self.dev=MemoryDevices()
  self.out=VerifiedOutputs(1,None,allow_missing_mouse=True,ioctl_fn=self.dev.ioctl,write_fn=self.dev.write,sleep_fn=lambda _:None)
  self.r=GroupedPrefixOutput(self.out,clock=lambda:self.now,sensor_input_verified=True)
  self.r.bind(1);self.r.router.press.feed(1,b'\0\0')
 def test_enter_release_is_not_moved_when_mouse_arrives(self):
  self.make();self.r._emit('center',True);self.out.mouse_fd=2;self.r._emit('center',False)
  self.r._emit('center',True);self.r._emit('center',False)
  keys=[(fd,code,value) for fd,events in self.dev.writes for _,_,kind,code,value in events if kind==1]
  self.assertEqual(keys,[(1,KEY_ENTER,1),(1,KEY_ENTER,0),(2,BTN_LEFT,1),(2,BTN_LEFT,0)])
  self.r.stop();self.assertTrue(self.out.verify_released())
 def test_motion_is_not_queued_while_mouse_absent(self):
  self.make();self.r.router.pose.last_pose=(0.,0.);self.r.router.tick=lambda:(15,2)
  for _ in range(20):self.now+=.02;self.r.tick()
  self.assertEqual(self.dev.writes,[]);self.assertEqual(len(self.r.transport.queue),0)
  self.r._emit('right',True);self.r._emit('right',False)
  self.assertEqual(len(self.dev.writes),2)
  self.out.mouse_fd=2;self.now+=.02;self.r.router.tick=lambda:(1,0);self.r.tick()
  events=[e for fd,packet in self.dev.writes if fd==2 for e in packet if e[2]==2]
  self.assertEqual(sum(e[4] for e in events if e[3]==0),1)
  self.assertEqual(sum(e[4] for e in events if e[3]==1),0)
  self.r.stop()
 def test_stop_without_mouse_releases_enter(self):
  self.make();self.r._emit('center',True);self.r.stop()
  self.assertTrue(self.out.verify_released());self.assertTrue(all(fd==1 for fd,_ in self.dev.writes))

class ReadyTests(unittest.TestCase):
 def test_navigation_ready_does_not_claim_mouse_is_ready(self):
  from borrowed_mode_session import BorrowedModeSession
  from receiver_ready_receipt import write_ready
  view=Mock(generation=1)
  session=BorrowedModeSession(view,read_mode=Mock(side_effect=[0,1]),read_stop_mode=lambda:0,write_mode=lambda _:True,control_valid=lambda:True,record=lambda _:True)
  session.start()
  with tempfile.TemporaryDirectory() as directory:
   os.chmod(directory,0o770)
   group=os.stat(directory).st_gid
   write_ready(directory,'a'*32,session,state_uid=os.getuid(),group=group,start_ticks=lambda:123,pointer_ready=False)
   result=json.loads((Path(directory)/('receiver-ready-'+'a'*32+'.json')).read_text())
   self.assertTrue(result['navigationReady']);self.assertFalse(result['pointerReady'])

if __name__=='__main__':unittest.main()
