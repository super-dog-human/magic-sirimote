import errno,os,stat,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import output_devices as devices
import output_sysfs
from test_rcu_output_device import Inventory

class StubInventory(Inventory):
 def __init__(self):
  super().__init__();self.opened=[];self.closed=[];self.unbound={1,2,3,5};self.denied=None
 def info(self,index):
  if index in self.unbound:
   return SimpleNamespace(st_dev=6,st_ino=100+index,st_rdev=os.makedev(13,64+index),st_mode=stat.S_IFCHR|0o660,st_uid=0,st_gid=505)
  return super().info(index)
 def open(self,path,flags):
  i=int(path.rsplit('event',1)[1]);self.opened.append(i)
  if i==self.denied:raise PermissionError(errno.EACCES,'denied')
  if i in self.unbound:raise OSError(errno.ENXIO,'unbound')
  return super().open(path,flags)
 def close(self,fd):self.closed.append(fd)
 def hint(self):return {i:(n,7,200+i) for i,n in self.names.items()}
 def fast(self,read=None,unregistered=None):
  return devices._open_with_sysfs(inventory_fn=read or self.hint,unregistered_fn=unregistered or (lambda i:i in self.unbound),lstat_fn=self.lstat,open_fn=self.open,fstat_fn=self.fstat,ioctl_fn=self.ioctl,close_fn=self.close,clock=lambda:0.)

class FastInventoryTests(unittest.TestCase):
 def test_skips_only_proven_unregistered_slots_and_keeps_all_real_name_queries(self):
  f=StubInventory();out,records,meta=f.fast()
  self.assertTrue(set(f.opened).isdisjoint(f.unbound));self.assertEqual(set(f.opened),set(f.names))
  self.assertEqual(f.rw,[0,9]);self.assertEqual(meta['unavailableEventSlots'],4);self.assertEqual(meta['inventorySource'],'sysfs-verified')
  self.assertEqual([r['name'] for r in records],['LGE RCU','ClickableMouse']);out.close(close_fn=f.close)
 def test_unavailable_sysfs_falls_back(self):
  f=StubInventory()
  def read():raise PermissionError(errno.EACCES,'metadata unavailable')
  out,_,_=f.fast(read);self.assertTrue(f.unbound<=set(f.opened));out.close(close_fn=f.close)
 def test_changed_inventory_falls_back_before_write_open(self):
  f=StubInventory();calls=[0]
  def read():
   calls[0]+=1;value=f.hint()
   if calls[0]>1:value[4]=('changed',7,204)
   return value
  out,_,_=f.fast(read);self.assertTrue(f.unbound<=set(f.opened));self.assertEqual(f.rw,[0,9]);out.close(close_fn=f.close)
 def test_unreadable_recheck_falls_back(self):
  f=StubInventory();calls=[0]
  def read():
   calls[0]+=1
   if calls[0]>1:raise OSError(errno.EIO,'lost sysfs')
   return f.hint()
  out,_,_=f.fast(read);self.assertTrue(f.unbound<=set(f.opened));out.close(close_fn=f.close)
 def test_incomplete_or_mismatched_hints_do_not_hide_a_duplicate(self):
  for mismatched in (False,True):
   f=StubInventory();f.names[12]='LGE RCU'
   def read():
    v=f.hint()
    if mismatched:v[12]=('other',7,212)
    else:del v[12]
    return v
   with self.assertRaises(devices.OutputInventoryIncomplete):f.fast(read)
   self.assertEqual(f.rw,[])
 def test_permission_error_on_real_node_still_rejects(self):
  f=StubInventory();f.denied=4
  with self.assertRaises(devices.OutputInventoryIncomplete):f.fast()
  self.assertEqual(f.rw,[])
 def test_capability_failure_still_rejects(self):
  f=StubInventory();f.missing_arrow=True
  with self.assertRaises(devices.OutputInventoryIncomplete):f.fast()
  self.assertEqual(f.rw,[])
 def test_new_registration_during_scan_falls_back(self):
  f=StubInventory();calls={}
  def absent(index):
   calls[index]=calls.get(index,0)+1
   return calls[index]==1
  out,_,_=f.fast(unregistered=absent);self.assertTrue(f.unbound<=set(f.opened));out.close(close_fn=f.close)
 def test_close_failure_is_never_retried(self):
  f=StubInventory()
  def close(fd):raise OSError('close failed')
  f.close=close
  with self.assertRaises(devices.OutputCloseError):f.fast()
  self.assertEqual(f.rw,[])

class SysfsReaderTests(unittest.TestCase):
 def make(self,root,index,name='LGE RCU',dev=None):
  p=root/('event'+str(index));(p/'device').mkdir(parents=True)
  (p/'dev').write_text(dev or '13:'+str(64+index)+'\n');(p/'device/name').write_text(name+'\n')
 def test_reads_complete_bounded_metadata(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);self.make(p,0);self.make(p,9,'ClickableMouse')
   value=output_sysfs.inventory(d);self.assertEqual(set(value),{0,9});self.assertEqual(value[9][0],'ClickableMouse')
 def test_missing_oversized_wrong_device_and_out_of_range_reject(self):
  for failure in ('missing','oversized','device','range'):
   with tempfile.TemporaryDirectory() as d:
    p=Path(d);index=128 if failure=='range' else 0;self.make(p,index)
    if failure=='missing':(p/'event0/device/name').unlink()
    if failure=='oversized':(p/'event0/device/name').write_text('x'*300)
    if failure=='device':(p/'event0/dev').write_text('13:99')
    with self.assertRaises((OSError,output_sysfs.InventoryUnavailable)):output_sysfs.inventory(d)
 def test_empty_index_rejects(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(output_sysfs.InventoryUnavailable):output_sysfs.inventory(d)
 def test_absence_requires_visible_populated_character_index(self):
  directory=SimpleNamespace(st_mode=stat.S_IFDIR|0o755)
  def missing(path):raise FileNotFoundError(errno.ENOENT,'absent',path)
  with patch.object(output_sysfs.os,'stat',return_value=directory),patch.object(output_sysfs.os,'lstat',side_effect=missing):
   self.assertTrue(output_sysfs.unregistered(5))
  with patch.object(output_sysfs.os,'stat',side_effect=missing):self.assertFalse(output_sysfs.unregistered(5))

if __name__=='__main__':unittest.main()
