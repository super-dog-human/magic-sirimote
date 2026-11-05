import copy,errno,os,stat,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
import output_devices as mod

class ReopenTests(unittest.TestCase):
 def fixture(self):
  stats=[SimpleNamespace(st_dev=5,st_ino=7+i,st_rdev=os.makedev(13,64+i),st_uid=0,st_gid=5000,st_mode=stat.S_IFCHR|0o660) for i in range(2)]
  records=[dict(path='/dev/input/event'+str(i),name=name,dev=5,inode=7+i,rdev=stats[i].st_rdev,uid=0,gid=5000,mode='0o660',capabilitiesVerified=True) for i,name in enumerate((mod.KEY_NAME,mod.MOUSE_NAME))]
  args=dict(lstat_fn=Mock(side_effect=lambda path:stats[int(path[-1])]),open_fn=Mock(side_effect=[10,11]),
   fstat_fn=Mock(side_effect=lambda fd:stats[fd-10]),ioctl_fn=Mock(),close_fn=Mock(),clock=lambda:0.)
  caps=Mock(side_effect=lambda fd,ioctl:{'name':records[fd-10]['name']})
  return records,args,stats,caps
 def test_reopens_only_exact_two_paths_and_rechecks_neutral_state(self):
  records,args,_,caps=self.fixture()
  with patch.object(mod,'_caps',caps),patch.object(mod,'_matches',return_value=True),patch.object(mod,'VerifiedOutputs') as bridge:
   out,current=mod.reopen_selected_outputs(records,**args)
   self.assertIs(out,bridge.return_value);bridge.assert_called_once_with(10,11,ioctl_fn=args['ioctl_fn'])
   self.assertEqual([c.args[0] for c in args['open_fn'].call_args_list],[r['path'] for r in records])
   self.assertEqual(caps.call_count,2);self.assertEqual(current[0]['inode'],records[0]['inode'])
  args['close_fn'].assert_not_called()
 def test_changed_node_or_invalid_record_never_opens_rw(self):
  for change in ({'inode':99},{'uid':9},{'path':'/dev/input/../event0'},{'mode':'0o666'},{'name':'wrong'},{'capabilitiesVerified':False}):
   records,args,_,_=self.fixture();records[0].update(change)
   with self.assertRaises((ValueError,mod.OutputSelectionChanged)):mod.reopen_selected_outputs(records,**args)
   args['open_fn'].assert_not_called()
 def test_reopen_race_or_wrong_name_closes_before_failure(self):
  for reason in ('stat','name','capabilities','held'):
   records,args,stats,caps=self.fixture()
   if reason=='stat':args['fstat_fn'].side_effect=lambda fd:SimpleNamespace(**{**vars(stats[fd-10]),'st_ino':99})
   if reason=='name':caps.side_effect=lambda fd,ioctl:{'name':mod.MOUSE_NAME}
   with patch.object(mod,'_caps',caps),patch.object(mod,'_matches',return_value=reason!='capabilities'),patch.object(mod,'VerifiedOutputs',side_effect=RuntimeError('held') if reason=='held' else None):
    with self.assertRaises(RuntimeError):mod.reopen_selected_outputs(records,**args)
   expected=[11,10] if reason=='held' else [10]
   self.assertEqual([c.args[0] for c in args['close_fn'].call_args_list],expected)
 def test_second_open_failure_closes_first_and_close_failure_is_distinct(self):
  for close_error in (False,True):
   records,args,_,caps=self.fixture();args['open_fn'].side_effect=[10,OSError(errno.ENODEV,'gone')]
   if close_error:args['close_fn'].side_effect=OSError('cannot close')
   with patch.object(mod,'_caps',caps),patch.object(mod,'_matches',return_value=True):
    with self.assertRaises(mod.OutputCloseError if close_error else OSError):mod.reopen_selected_outputs(records,**args)
   args['close_fn'].assert_called_once_with(10)

class SelectionTests(unittest.TestCase):
 def fixture(self):
  records=[{'name':'key'},{'name':'mouse'}];output=Mock()
  scan=Mock(return_value=(output,records,{'inventoryComplete':True}));reopen=Mock(return_value=(output,copy.deepcopy(records)))
  selection=mod.OutputSelection(scan=scan,reopen=reopen);guard=Mock(return_value=True)
  return selection,scan,reopen,records,dict(allow_retry=guard,wait=Mock())
 def test_same_worker_selection_is_detached_and_not_reused_by_new_worker(self):
  selection,scan,reopen,records,args=self.fixture();selection.open(**args)
  records[0]['name']='caller-mutated';selection.open(**args)
  self.assertEqual(reopen.call_args.args[0][0]['name'],'key');scan.assert_called_once()
  mod.OutputSelection(scan=scan,reopen=reopen).open(**args);self.assertEqual(scan.call_count,2)
 def test_changed_or_gone_device_requires_complete_inventory(self):
  for error in (mod.OutputSelectionChanged('changed'),OSError(errno.ENOENT,'gone'),OSError(errno.ENODEV,'gone'),OSError(errno.ENXIO,'gone')):
   selection,scan,reopen,_,args=self.fixture();selection.open(**args);reopen.side_effect=error
   selection.open(**args);self.assertEqual(scan.call_count,2)
 def test_permission_neutral_or_close_failure_cannot_fall_back(self):
  for error in (PermissionError(errno.EACCES,'denied'),OSError(errno.EIO,'read failed'),RuntimeError('held'),mod.OutputCloseError('close failed')):
   selection,scan,reopen,_,args=self.fixture();selection.open(**args);reopen.side_effect=error
   with self.assertRaises(type(error)):selection.open(**args)
   scan.assert_called_once();self.assertIsNone(selection.records)
 def test_lost_guard_prevents_reopen(self):
  selection,scan,reopen,_,args=self.fixture();selection.open(**args);args['allow_retry'].return_value=False
  with self.assertRaisesRegex(RuntimeError,'guard-lost'):selection.open(**args)
  reopen.assert_not_called();scan.assert_called_once()

if __name__=='__main__':unittest.main()
