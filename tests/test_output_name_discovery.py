import errno,unittest
from unittest.mock import patch
import output_devices as devices
from test_rcu_output_device import Inventory

class NameDiscoveryTests(unittest.TestCase):
 def test_unrelated_devices_need_only_the_name_query(self):
  f=Inventory();original=f.ioctl;queries=[]
  def ioctl(fd,request,buf,mutate):
   queries.append((fd,request))
   if fd==104 and request!=devices.EV_NAME(256):
    raise OSError(errno.EINVAL,'Unrelated capabilities unavailable')
   return original(fd,request,buf,mutate)
  f.ioctl=ioctl
  outputs,records,_=f.run()
  self.assertEqual([req for fd,req in queries if fd==104],[devices.EV_NAME(256)])
  self.assertEqual(f.rw,[0,9]);outputs.close(close_fn=f.close)
 def test_unreadable_name_does_not_count_as_an_unrelated_device(self):
  f=Inventory();original=f.ioctl
  def ioctl(fd,request,buf,mutate):
   if fd==104:raise OSError(errno.EIO,'private diagnostic')
   return original(fd,request,buf,mutate)
  f.ioctl=ioctl
  with self.assertRaises(devices.OutputInventoryIncomplete) as raised:f.run()
  self.assertFalse(raised.exception.details['complete'])
  self.assertEqual(raised.exception.details['errors']['EIO'],1);self.assertEqual(f.rw,[])
 def test_target_capability_failure_still_blocks_write_open(self):
  f=Inventory();original=f.ioctl
  def ioctl(fd,request,buf,mutate):
   if fd==109 and request!=devices.EV_NAME(256):raise OSError(errno.EINVAL,'private diagnostic')
   return original(fd,request,buf,mutate)
  f.ioctl=ioctl
  with self.assertRaises(devices.OutputInventoryIncomplete) as raised:f.run()
  self.assertFalse(raised.exception.details['complete']);self.assertEqual(f.rw,[])
 def test_missing_and_duplicate_targets_remain_distinguishable(self):
  for duplicate in (False,True):
   f=Inventory()
   if duplicate:f.names[12]='LGE RCU'
   else:del f.names[9]
   with self.assertRaises(devices.OutputInventoryIncomplete) as raised:f.run()
   self.assertTrue(raised.exception.details['complete'])
   self.assertEqual(raised.exception.details['counts'],{'LGE RCU':2 if duplicate else 1,'ClickableMouse':1 if duplicate else 0})
   self.assertEqual(f.rw,[])
 def test_retry_record_contains_fixed_inventory_metadata_only(self):
  f=Inventory();del f.names[9];now=[0.];calls=[0]
  def attempt(*args,**kwargs):
   calls[0]+=1
   if calls[0]==2:f.names[9]='ClickableMouse'
   return f.run()
  with patch.object(devices,'_report') as report:
   outputs,_,_=devices.open_verified_outputs(attempt_fn=attempt,allow_retry=lambda:True,clock=lambda:now[0],wait=lambda delay:now.__setitem__(0,now[0]+delay))
  retry=next(c.args[0] for c in report.call_args_list if c.args[0]['stage']=='output-discovery-retry')
  self.assertEqual(retry['inventory']['counts'],{'LGE RCU':1,'ClickableMouse':0})
  self.assertEqual(set(retry['inventory']),{'complete','counts','errors','unavailableEventSlots'})
  outputs.close(close_fn=f.close)

if __name__=='__main__':unittest.main()
