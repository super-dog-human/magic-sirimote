import errno,os,stat,unittest
from types import SimpleNamespace as S
from unittest.mock import Mock
from hid_input import scan_devices
from hid_nodes import indexes
from postconnect_receiver_device import _open_target_once,transient_disappeared

class Tests(unittest.TestCase):
 def fixture(self,names):
  node=S(st_mode=stat.S_IFCHR|0o600,st_ino=10,st_dev=1,st_rdev=os.makedev(242,64),st_uid=1,st_gid=5000)
  args=dict(listdir_fn=Mock(return_value=names),lstat_fn=Mock(return_value=node),open_fn=Mock(return_value=7),
   fstat_fn=Mock(return_value=node),identity_fn=Mock(return_value={'matches':True,'product':0x0266}),close_fn=Mock(),clock=lambda:0.)
  return node,args
 def test_high_number_is_discovered_and_opened_by_exact_identity(self):
  node,args=self.fixture(['hidraw64','null','hidraw-1','hidraw01','hidraw1/else'])
  inv=scan_devices(**args);self.assertTrue(inv['inventoryComplete']);self.assertEqual(inv['targetCandidateIndexes'],[64])
  args['open_fn'].assert_called_once();args['close_fn'].assert_called_once_with(7)
  opened=Mock(return_value=8)
  result=_open_target_once(inventory=lambda **_:inv,lstat=lambda _:node,open_fn=opened,
   fstat=lambda _:node,identity_fn=lambda _:dict(matches=True,product=0x0266),close_fn=Mock())
  self.assertEqual(result,8);self.assertEqual(opened.call_args.args[0],'/dev/hidraw64')
 def test_new_high_number_during_scan_invalidates_inventory(self):
  _,args=self.fixture(['hidraw1']);args['listdir_fn'].side_effect=[['hidraw1'],['hidraw1','hidraw64']]
  inv=scan_devices(**args);self.assertFalse(inv['inventoryComplete']);self.assertIn('INVENTORY_CHANGED',inv['errnoBuckets'])
  self.assertFalse(transient_disappeared(inv))
 def test_second_matching_high_number_is_ambiguous(self):
  _,args=self.fixture(['hidraw1','hidraw64']);inv=scan_devices(**args)
  with self.assertRaisesRegex(RuntimeError,'ambiguous'):_open_target_once(inventory=lambda **_:inv)
 def test_permission_failure_is_not_an_empty_inventory(self):
  _,args=self.fixture([]);args['listdir_fn'].side_effect=PermissionError(errno.EACCES,'denied')
  inv=scan_devices(**args);self.assertFalse(inv['inventoryComplete']);args['open_fn'].assert_not_called()
 def test_disappeared_and_returned_name_cannot_be_silently_omitted(self):
  _,args=self.fixture(['hidraw64']);args['lstat_fn'].side_effect=FileNotFoundError(errno.ENOENT,'gone')
  inv=scan_devices(**args);self.assertFalse(inv['inventoryComplete']);self.assertIn('INVENTORY_CHANGED',inv['errnoBuckets'])
 def test_symlink_is_never_opened(self):
  _,args=self.fixture(['hidraw64']);args['lstat_fn'].return_value=S(st_mode=stat.S_IFLNK|0o777)
  inv=scan_devices(**args);self.assertFalse(inv['inventoryComplete']);args['open_fn'].assert_not_called()
 def test_listing_is_bounded_without_silently_truncating(self):
  for names in ([f'hidraw{i}' for i in range(257)],['hidraw1048576'],['hidraw1','hidraw1']):
   with self.assertRaises(OSError):indexes('/dev',listdir=lambda _:names)
 def test_descriptor_closed_on_identity_failure(self):
  _,args=self.fixture(['hidraw64']);args['identity_fn'].side_effect=OSError(errno.EIO,'failed')
  inv=scan_devices(**args);self.assertFalse(inv['inventoryComplete']);args['close_fn'].assert_called_once_with(7)
 def test_orphan_proof_supports_high_index_with_same_checks(self):
  from hid_orphan import unregistered
  node=S(st_mode=stat.S_IFCHR|0o600,st_ino=10,st_dev=1,st_rdev=os.makedev(242,64))
  null=S(st_mode=stat.S_IFCHR,st_rdev=os.makedev(1,3))
  def lst(path):
   if path=='/dev/hidraw64':return node
   if path=='/sys/dev/char/1:3':return S()
   raise FileNotFoundError(errno.ENOENT,'missing')
  self.assertTrue(unregistered(index=64,major=242,minor=64,lstat=lst,stat_fn=lambda p:S(st_mode=stat.S_IFDIR) if p=='/sys/dev/char' else null))
