import errno,os,stat,unittest
from types import SimpleNamespace
import output_devices as devices
from output_bridge import KEYS,KEY_CODES,KEY_ENTER,BTN_LEFT,IOCG_KEY_STATE

def bits(size,codes):
 b=bytearray(size)
 for c in codes:b[c//8]|=1<<(c%8)
 return b

class Inventory:
 def __init__(self):
  self.names={0:'LGE RCU',4:'LGE M-RCU - Builtin [1]',9:'ClickableMouse'};self.rw=[];self.missing_arrow=False;self.missing_enter=False
 def info(self,index):
  if index not in self.names:raise FileNotFoundError(errno.ENOENT,'absent')
  return SimpleNamespace(st_dev=6,st_ino=100+index,st_rdev=os.makedev(13,64+index),st_mode=stat.S_IFCHR|0o660,st_uid=0,st_gid=505)
 def lstat(self,path):return self.info(int(path.rsplit('event',1)[1]))
 def open(self,path,flags):
  i=int(path.rsplit('event',1)[1]);self.info(i)
  if flags&os.O_RDWR:self.rw.append(i)
  return 100+i
 def fstat(self,fd):return self.info(fd-100)
 def close(self,fd):pass
 def ioctl(self,fd,request,buf,mutate):
  i=fd-100
  if request==devices.EV_NAME(256):value=self.names[i].encode()+b'\0'
  elif request==IOCG_KEY_STATE:value=bytes(len(buf))
  elif request==devices.EV_BITS(0,len(buf)):value=bits(len(buf),(0,1,2))
  elif request==devices.EV_BITS(1,len(buf)):
   codes=[BTN_LEFT] if i==9 else list(KEY_CODES)
   if self.missing_arrow and i==0:codes.remove(KEYS['down'])
   if self.missing_enter and i==0:codes.remove(KEY_ENTER)
   value=bits(len(buf),codes)
  elif request==devices.EV_BITS(2,len(buf)):value=bits(len(buf),(0,1))
  else:raise AssertionError(request)
  buf[:]=value.ljust(len(buf),b'\0');return 0
 def run(self):
  return devices.open_verified_outputs(lstat_fn=self.lstat,open_fn=self.open,fstat_fn=self.fstat,ioctl_fn=self.ioctl,close_fn=self.close,clock=lambda:0.)

class Tests(unittest.TestCase):
 def test_rcu_chosen_while_previous_builtin_device_is_present(self):
  f=Inventory();out,records,inv=f.run()
  self.assertEqual(f.rw,[0,9]);self.assertEqual(records[0]['name'],'LGE RCU')
  self.assertEqual(out.key_fd,100);self.assertTrue(inv['inventoryComplete']);out.close(close_fn=f.close)
 def test_previous_builtin_is_not_a_fallback_when_rcu_absent(self):
  f=Inventory();del f.names[0]
  with self.assertRaises(RuntimeError):f.run()
  self.assertEqual(f.rw,[])
 def test_duplicate_rcu_identity_is_rejected_before_write_open(self):
  f=Inventory();f.names[1]='LGE RCU'
  with self.assertRaises(RuntimeError):f.run()
  self.assertEqual(f.rw,[])
 def test_rcu_without_all_directions_is_rejected(self):
  f=Inventory();f.missing_arrow=True
  with self.assertRaises(RuntimeError):f.run()
  self.assertEqual(f.rw,[])

 def test_rcu_without_enter_is_rejected(self):
  f=Inventory();f.missing_enter=True
  with self.assertRaises(RuntimeError):f.run()
  self.assertEqual(f.rw,[])

if __name__=='__main__':unittest.main()
