import copy,stat,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
from postconnect_receiver_device import _open_target_once

ORPHAN={'index':0,'rdevMajor':240,'rdevMinor':0,'inspectionErrno':'ENODEV','openedReadOnly':False,'identityChecked':False}
TARGET={'index':2,'rdevMajor':240,'rdevMinor':2,'openedReadOnly':True,'identityChecked':True,'fdClosed':True}
INVENTORY={'inventoryComplete':False,'allOpenedFdsClosed':True,'targetCandidateIndexes':[2],'nodes':[ORPHAN,TARGET],'errnoBuckets':{}}

class Tests(unittest.TestCase):
 def fixture(self):
  node=SimpleNamespace(st_mode=stat.S_IFCHR|0o600,st_ino=10,st_dev=1,st_rdev=12)
  return dict(inventory=Mock(return_value=copy.deepcopy(INVENTORY)),lstat=Mock(return_value=node),
   open_fn=Mock(return_value=7),fstat=Mock(return_value=node),identity_fn=Mock(return_value={'matches':True,'product':0x0266}),
   close_fn=Mock(),allow_retry=Mock(return_value=True),wait=Mock(),orphan_check=Mock(return_value=True))

 def test_proven_orphans_skip_delay_but_repeat_inventory_and_recheck_after_open(self):
  args=self.fixture();self.assertEqual(_open_target_once(**args),7)
  self.assertEqual(args['inventory'].call_count,2);args['wait'].assert_not_called()
  self.assertEqual(args['orphan_check'].call_count,3)
  args['identity_fn'].assert_called_once_with(7);args['close_fn'].assert_not_called()

 def test_unknown_registration_keeps_delay_and_never_hides_incomplete_scan(self):
  args=self.fixture();args['orphan_check'].return_value=False
  with self.assertRaisesRegex(RuntimeError,'inventory incomplete'):_open_target_once(**args)
  args['wait'].assert_called_once_with(.2);args['open_fn'].assert_not_called()

 def test_orphan_registered_before_second_scan_rejects_fast_path(self):
  args=self.fixture();args['orphan_check'].side_effect=[True,False]
  with self.assertRaisesRegex(RuntimeError,'inventory incomplete'):_open_target_once(**args)
  args['open_fn'].assert_not_called();args['wait'].assert_not_called()

 def test_registration_after_open_closes_descriptor(self):
  args=self.fixture();args['orphan_check'].side_effect=[True,True,False]
  with self.assertRaisesRegex(RuntimeError,'orphan proof changed'):_open_target_once(**args)
  args['close_fn'].assert_called_once_with(7)

 def test_new_second_target_or_permission_failure_cannot_be_ignored(self):
  second=copy.deepcopy(INVENTORY);second['nodes'][0]['inspectionErrno']='EACCES'
  for next_scan in (second,{**INVENTORY,'targetCandidateIndexes':[1,2]}):
   args=self.fixture();args['inventory'].side_effect=[copy.deepcopy(INVENTORY),copy.deepcopy(next_scan)]
   with self.assertRaises(RuntimeError):_open_target_once(**args)
   args['open_fn'].assert_not_called()

 def test_missing_target_keeps_settle_delay(self):
  args=self.fixture();first=copy.deepcopy(INVENTORY);first['targetCandidateIndexes']=[]
  args['inventory'].side_effect=[first,copy.deepcopy(INVENTORY)]
  self.assertEqual(_open_target_once(**args),7);args['wait'].assert_called_once_with(.2)

 def test_guard_loss_before_second_scan_stops_without_opening(self):
  args=self.fixture();args['allow_retry'].side_effect=[True,False]
  with self.assertRaisesRegex(RuntimeError,'inventory incomplete'):_open_target_once(**args)
  args['inventory'].assert_called_once();args['open_fn'].assert_not_called()

if __name__=='__main__':unittest.main()
