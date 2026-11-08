"""Early pointer output through the TV's verified built-in M-RCU device."""
import errno
import fcntl
import os
import stat
import struct

from output_bridge import VerifiedOutputs, EVENT, BTN_LEFT, _ioctl_bitmap, IOCG_KEY_STATE, _key_is_down
from output_devices import OutputCloseError, _same
from output_sysfs import inventory, InventoryUnavailable

NAME='LGE M-RCU - Builtin [0]'
SHOW,HIDE=1198,1199
ABS_INFO=struct.Struct('=6i')

class UnsupportedPointer(RuntimeError):
 pass

def read_ioctl(fd,nr,size,ioctl):
 data=bytearray(size)
 ioctl(fd,(2<<30)|(size<<16)|(ord('E')<<8)|nr,data,True)
 return bytes(data)

def axis(fd,code,ioctl):
 value,low,high,_,_,_=ABS_INFO.unpack(read_ioctl(fd,0x40+code,24,ioctl))
 if not (0<=low<high<=16384 and low<=value<=high):raise UnsupportedPointer('invalid absolute axis')
 return value,(low,high)

def visible_frame(x,y,limits):
 for value,(low,high) in zip((x,y),limits):
  if type(value) is not int or not low<=value<=high:raise ValueError('invalid absolute coordinate')
 alternate=lambda value,bounds:value-1 if value>bounds[0] else value+1
 # evdev drops unchanged ABS values, while redisplaying can reset the TV's
 # internal position. Deliver both final coordinates before the sole SYN.
 events=((1,SHOW,1),(1,SHOW,0),(3,0,alternate(x,limits[0])),
         (3,1,alternate(y,limits[1])),(3,0,x),(3,1,y),(0,0,0))
 return b''.join(EVENT.pack(0,0,*event) for event in events)

class AbsoluteOutputs(VerifiedOutputs):
 absolute_motion=True
 # Absolute coordinates bypass the TV's relative-mouse amplification. Keep
 # this spatial conversion separate from pose filtering and update timing.
 MOTION_NUMERATOR=5
 MOTION_DENOMINATOR=2
 def _verify_mouse(self):
  fd=self.mouse_fd;ioctl=self.ioctl_fn
  name=read_ioctl(fd,0x06,256,ioctl).split(b'\0',1)[0]
  if name!=NAME.encode():raise UnsupportedPointer('absolute pointer name mismatch')
  events=int.from_bytes(read_ioctl(fd,0x20,8,ioctl),'little')
  keys=int.from_bytes(read_ioctl(fd,0x21,256,ioctl),'little')
  axes=int.from_bytes(read_ioctl(fd,0x23,8,ioctl),'little')
  if any(not events&(1<<code) for code in (0,1,3)) or axes&3!=3:
   raise UnsupportedPointer('absolute pointer event capabilities missing')
  if any(not keys&(1<<code) for code in (BTN_LEFT,SHOW,HIDE)):
   raise UnsupportedPointer('absolute pointer key capabilities missing')
  self.limits=tuple(axis(fd,code,ioctl)[1] for code in (0,1))
  self.motion_remainder=[0,0]
  self.last_target=None
  if _key_is_down(_ioctl_bitmap(fd,IOCG_KEY_STATE,ioctl),BTN_LEFT):
   raise RuntimeError('absolute pointer button already held')
 def move_relative(self,dx,dy):
  if self.failed or self.closed:raise RuntimeError('output-bridge-not-active')
  if type(dx) is not int or type(dy) is not int or not all(-2147483648<=v<=2147483647 for v in (dx,dy)):
   raise ValueError('relative-delta-outside-int32')
  if dx==0 and dy==0:return
  try:
   current=[axis(self.mouse_fd,code,self.ioctl_fn) for code in (0,1)]
   if tuple(item[1] for item in current)!=self.limits:raise RuntimeError('absolute pointer ranges changed')
   positions=[item[0] for item in current]
   if self.last_target is not None and positions!=self.last_target:
    self.motion_remainder=[0,0]
   target=[];remainder=[]
   for value,delta,carry,(low,high) in zip(positions,(dx,dy),self.motion_remainder,self.limits):
    step,rest=divmod(delta*self.MOTION_NUMERATOR+carry,self.MOTION_DENOMINATOR)
    value+=step;bounded=max(low,min(high,value))
    target.append(bounded)
    # Keep fractional pixels across frames, but never retain edge overshoot.
    remainder.append(rest if low<bounded<high else 0)
   self._write_exact(self.mouse_fd,visible_frame(*target,self.limits));self.motion_writes+=1
   self.motion_remainder=remainder;self.last_target=target
  except BaseException:self.failed=True;raise
 def center_pointer(self):
  """Show the cursor at the middle of the screen (used when motion re-activates it)."""
  if self.failed or self.closed:raise RuntimeError('output-bridge-not-active')
  try:
   target=[(low+high)//2 for low,high in self.limits]
   self._write_exact(self.mouse_fd,visible_frame(*target,self.limits));self.motion_writes+=1
   self.motion_remainder=[0,0];self.last_target=target
  except BaseException:self.failed=True;raise
 @property
 def cursor_visible(self):
  from cursor_visibility_probe import current_visibility
  return current_visibility()
 def click_frame(self,packet):
  return self._button_frame(self.mouse_fd,BTN_LEFT,packet,'LGE-MRCU-BTN_LEFT')
 def summary(self):
  return dict(super().summary(),pointerBackend='builtin-absolute')

def prefer_absolute(outputs,records,guard,*,read_inventory=inventory,lstat=os.lstat,
                    open_fd=os.open,fstat=os.fstat,close=os.close,ioctl=fcntl.ioctl):
 """Transfer ownership only after unique discovery, validation and a live guard.

 Unsupported hardware keeps the existing output backend. No input is emitted
 while selecting or constructing an output. A cleanup failure never falls back.
 """
 if guard() is not True:raise RuntimeError('absolute output guard lost')
 try:first=read_inventory()
 except (OSError,ValueError,InventoryUnavailable):return outputs,records
 matches=[index for index,entry in first.items() if entry[0]==NAME]
 if not matches:return outputs,records
 if len(matches)!=1:raise RuntimeError('absolute output not unique')
 index=matches[0];path='/dev/input/event'+str(index)
 fd=None;transferred=False
 try:
  before=lstat(path)
  if (not stat.S_ISCHR(before.st_mode) or os.major(before.st_rdev)!=13 or os.minor(before.st_rdev)!=64+index):
   raise RuntimeError('absolute output identity invalid')
  fd=open_fd(path,os.O_RDWR|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC)
  opened=fstat(fd);after=lstat(path)
  if not _same(before,opened) or not _same(opened,after) or read_inventory()!=first:
   raise RuntimeError('absolute output changed while opening')
  replacement=AbsoluteOutputs(outputs.key_fd,fd,ioctl_fn=ioctl,write_fn=outputs.write_fn,sleep_fn=outputs.sleep_fn)
  if guard() is not True:raise RuntimeError('absolute output guard lost')
  record={'path':path,'name':NAME,'dev':opened.st_dev,'inode':opened.st_ino,'rdev':opened.st_rdev,
          'uid':opened.st_uid,'gid':opened.st_gid,'mode':oct(stat.S_IMODE(opened.st_mode)),
          'capabilitiesVerified':True,'eventTypes':[0,1,3],'keyCodes':[BTN_LEFT,SHOW,HIDE],'absoluteCodes':[0,1]}
  if outputs.mouse_provider is not None or outputs.spare_key_fd is not None or outputs.closed:
   raise RuntimeError('absolute selection must precede receiver activation')
  previous=outputs.mouse_fd;outputs.mouse_fd=None
  if previous is not None:
   try:close(previous)
   except BaseException:raise OutputCloseError('prior mouse descriptor close unconfirmed')
  outputs.key_fd=None;outputs.closed=True;transferred=True
  return replacement,[dict(records[0]),record]
 except UnsupportedPointer:return outputs,records
 except OSError as error:
  if error.errno in (errno.ENOENT,errno.ENODEV,errno.ENXIO,errno.EACCES,errno.EPERM):return outputs,records
  raise
 finally:
  if fd is not None and not transferred:
   try:close(fd)
   except BaseException:raise OutputCloseError('absolute descriptor close unconfirmed')
