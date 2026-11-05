import os,stat,sys,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
import system_key_device as device
import postconnect_receiver_app as app

class ReopenTests(unittest.TestCase):
 def fixture(self):
  st=SimpleNamespace(st_dev=5,st_ino=7,st_rdev=os.makedev(13,64),st_uid=0,st_gid=5000,st_mode=stat.S_IFCHR|0o660)
  record={'path':'/dev/input/event0','name':'LGE RCU','dev':5,'inode':7,'rdev':st.st_rdev,'uid':0,'gid':5000,'mode':'0o660','capabilitiesVerified':True}
  args=dict(lstat=Mock(return_value=st),fstat=Mock(return_value=st),open_fn=Mock(return_value=12),ioctl=Mock(),close=Mock(),write=Mock(),clock=lambda:0.)
  return st,record,args
 def test_reuses_inventory_but_rechecks_identity_capabilities_and_neutral_keys(self):
  st,record,args=self.fixture()
  with patch.object(device,'_identity',return_value={}) as identity,patch.object(device,'identity_matches',return_value=True),patch.object(device,'_supported',return_value=True) as caps,patch.object(device,'SystemKeySink') as sink:
   value,fd=device.open_system_key_from_record(record,**args)
   self.assertIs(value,sink.return_value);self.assertEqual(fd,12)
   self.assertTrue(sink.call_args.kwargs['identity_check'](12))
   self.assertFalse(sink.call_args.kwargs['identity_check'](13))
  args['open_fn'].assert_called_once();self.assertEqual(args['open_fn'].call_args.args[0],record['path'])
  self.assertGreaterEqual(identity.call_count,2);self.assertGreaterEqual(caps.call_count,2)
  args['write'].assert_not_called();args['close'].assert_not_called()
 def test_invalid_or_changed_record_never_opens_for_write(self):
  for changes in ({'inode':8},{'uid':1},{'mode':'0o666'},{'path':'/dev/input/../event0'},{'name':'other'},{'capabilitiesVerified':False},{'dev':True}):
   _,record,args=self.fixture();record.update(changes)
   with self.assertRaises((ValueError,RuntimeError)):device.open_system_key_from_record(record,**args)
   args['open_fn'].assert_not_called();args['write'].assert_not_called()
 def test_reopen_identity_capability_neutral_or_path_failure_closes_fd(self):
  for failure in ('path','identity','capability','held'):
   st,record,args=self.fixture()
   if failure=='path':args['lstat'].side_effect=[st,SimpleNamespace(**{**vars(st),'st_ino':8})]
   with patch.object(device,'_identity',return_value={}),patch.object(device,'identity_matches',return_value=failure!='identity'),patch.object(device,'_supported',return_value=failure!='capability'),patch.object(device,'SystemKeySink',side_effect=RuntimeError('held') if failure=='held' else None):
    with self.assertRaises(RuntimeError):device.open_system_key_from_record(record,**args)
   args['close'].assert_called_once_with(12);args['write'].assert_not_called()
 def test_permission_failure_does_not_search_other_devices(self):
  _,record,args=self.fixture();args['open_fn'].side_effect=PermissionError('denied')
  with self.assertRaises(PermissionError):device.open_system_key_from_record(record,**args)
  args['open_fn'].assert_called_once();args['write'].assert_not_called()

class SharedSetupTests(unittest.TestCase):
 def run_setup(self,fail=False):
  pump=Mock();pump.tracker=pump;pump.snapshot.return_value={'generation':1};pump.stop.return_value=True
  lease=Mock();lease.held.return_value=True;journal=Mock();journal.archive_completed.return_value=True
  outputs=Mock();record={'name':'LGE RCU'};sink=Mock();seen=[]
  ready=threading.Event()
  def scan(**kwargs):
   ready.set()
   if fail:raise RuntimeError('incomplete inventory')
   return outputs,[record],{'inventoryComplete':True}
  def session(**kwargs):
   # Start the dependent side first, proving it waits for this scan's result.
   def system():
    try:seen.append(kwargs['open_system_keys']())
    except Exception as e:seen.append(type(e))
   thread=threading.Thread(target=system);thread.start()
   try:
    if fail:
     with self.assertRaises(RuntimeError):kwargs['open_outputs']()
    else:self.assertIs(kwargs['open_outputs'](),outputs)
   finally:thread.join(2)
   self.assertFalse(thread.is_alive())
   return {'status':'not-ready'}
  with patch.object(app,'open_verified_outputs',side_effect=scan) as inventory,patch('hid_retry_guard.make_guard',return_value=lambda:True),patch.object(device,'open_system_key_from_record',return_value=(sink,12)) as reopen:
   result=app.run_once(state_path='/state',run='a'*32,external_feature_guard=lambda:True,duration=None,system_buttons=True,
    pump_factory=lambda:pump,lease_factory=lambda _:lease,journal_factory=lambda *_:journal,
    session_runner=session,identity_check=lambda:None)
  inventory.assert_called_once()
  if fail:reopen.assert_not_called();self.assertEqual(seen,[RuntimeError])
  else:reopen.assert_called_once_with(record);self.assertEqual(seen,[(sink,12)])
 def test_two_sinks_share_one_complete_scan(self):self.run_setup()
 def test_failed_scan_unblocks_dependent_setup_without_opening_system_sink(self):self.run_setup(True)

if __name__=='__main__':unittest.main()
