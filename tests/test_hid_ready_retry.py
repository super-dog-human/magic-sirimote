import copy,stat,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
from postconnect_receiver_device import open_target,_inventory_evidence,_kernel_hid_nodes

EMPTY={'inventoryComplete':True,'allOpenedFdsClosed':True,'targetCandidateIndexes':[],'nodes':[],'errnoBuckets':{'ENOENT':32}}

class Tests(unittest.TestCase):
 def fixture(self,inventory):
  now=[0.];wait=Mock(side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds))
  node=SimpleNamespace(st_mode=stat.S_IFCHR|0o600,st_ino=10,st_dev=1,st_rdev=12)
  return dict(inventory=inventory,lstat=Mock(return_value=node),open_fn=Mock(return_value=7),
   fstat=Mock(return_value=node),identity_fn=Mock(return_value={'matches':True,'product':0x0266}),close_fn=Mock(),
   allow_retry=Mock(return_value=True),wait=wait,clock=lambda:now[0],report=Mock()),now

 def test_delayed_registration_opens_without_restarting_input(self):
  inventory=Mock(side_effect=[copy.deepcopy(EMPTY),copy.deepcopy(EMPTY),{**EMPTY,'targetCandidateIndexes':[2]}])
  args,now=self.fixture(inventory)
  self.assertEqual(open_target(**args),7)
  self.assertEqual(inventory.call_count,3);self.assertAlmostEqual(now[0],.1)
  args['open_fn'].assert_called_once();args['identity_fn'].assert_called_once_with(7)
  args['close_fn'].assert_not_called()

 def test_ready_device_has_no_added_wait(self):
  args,_=self.fixture(Mock(return_value={**EMPTY,'targetCandidateIndexes':[2]}))
  self.assertEqual(open_target(**args),7);args['wait'].assert_not_called()

 def test_preinitialization_absence_does_not_wait_for_registration(self):
  args,now=self.fixture(Mock(return_value=copy.deepcopy(EMPTY)))
  with self.assertRaisesRegex(RuntimeError,'target not present'):
   open_target(**args,wait_for_target=False)
  args['inventory'].assert_called_once();args['wait'].assert_not_called()
  args['open_fn'].assert_not_called();self.assertEqual(now[0],0.)

 def test_missing_target_times_out_without_opening_any_descriptor(self):
  args,now=self.fixture(Mock(return_value=copy.deepcopy(EMPTY)))
  with self.assertRaisesRegex(RuntimeError,'target not present'):open_target(**args)
  self.assertLessEqual(args['inventory'].call_count,41);self.assertAlmostEqual(now[0],2.)
  args['open_fn'].assert_not_called()

 def test_incomplete_or_ambiguous_inventory_does_not_retry(self):
  for change in ({'inventoryComplete':False},{'allOpenedFdsClosed':False},
                 {'targetCandidateIndexes':[1,2]}):
   args,_=self.fixture(Mock(return_value={**EMPTY,**change}))
   with self.assertRaises(RuntimeError):open_target(**args)
   args['inventory'].assert_called_once();args['wait'].assert_not_called()

 def test_guard_loss_and_clock_rollback_stop_rescanning(self):
  for reason in ('guard','clock'):
   args,now=self.fixture(Mock(return_value=copy.deepcopy(EMPTY)))
   if reason=='guard':args['allow_retry'].side_effect=[True,False]
   else:args['wait'].side_effect=lambda _:now.__setitem__(0,-1.)
   with self.assertRaisesRegex(RuntimeError,'target not present'):open_target(**args)
   args['inventory'].assert_called_once();args['open_fn'].assert_not_called()

 def test_evidence_omits_identifying_strings(self):
  value=_inventory_evidence({**EMPTY,'nodes':[{'index':2,'rdevMajor':240,'rdevMinor':2,
   'targetIdentity':{'matches':True,'name':'PRIVATE-NAME','uniq':'PRIVATE-ADDRESS'},
   'inspectionErrno':'UNEXPECTED-PRIVATE'}]})
  self.assertEqual(value,{'complete':True,'nodes':[{'index':2,'rdevMajor':240,'rdevMinor':2,'matches':True}]})

 def test_failed_inventory_reports_once_without_changing_failure(self):
  args,_=self.fixture(Mock(return_value=copy.deepcopy(EMPTY)))
  args['report'].side_effect=RuntimeError('diagnostic unavailable')
  with self.assertRaisesRegex(RuntimeError,'target not present'):open_target(**args)
  args['report'].assert_called_once_with(EMPTY,args['inventory'].call_count,'failed')
  args['open_fn'].assert_not_called()

 def test_diagnostic_failure_does_not_lose_open_descriptor(self):
  args,_=self.fixture(Mock(return_value={**EMPTY,'targetCandidateIndexes':[2]}))
  args['report'].side_effect=RuntimeError('diagnostic unavailable')
  self.assertEqual(open_target(**args),7)
  args['report'].assert_called_once();args['close_fn'].assert_not_called()

 def test_kernel_inventory_reports_numeric_registration_and_unreadable_nodes(self):
  import tempfile
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   (root/'hidraw1').mkdir();(root/'hidraw1/dev').write_text('240:1\n')
   (root/'hidraw2').mkdir();(root/'hidraw2/dev').write_text('invalid')
   self.assertEqual(_kernel_hid_nodes(root),[{'index':1,'major':240,'minor':1},{'index':2,'unreadable':True}])


if __name__=='__main__':unittest.main()
