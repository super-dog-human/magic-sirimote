"""Narrow output adapters for already-open, identity-verified evdev FDs.

Discovery/open/ownership are intentionally supplied by the caller. This
module never scans or opens /dev and never touches Bluetooth.
"""
import errno
import fcntl
import os
import struct
import time

from action_pipeline import has_capability, require_clickable_mouse_capabilities

EV_SYN, EV_KEY, EV_REL = 0, 1, 2
SYN_REPORT, BTN_LEFT = 0, 0x110
KEY_ENTER = 28
KEYS = {'up':103,'down':108,'left':105,'right':106}
EVENT = struct.Struct('=iiHHi')
KEY_CODES = tuple(KEYS.values()) + (KEY_ENTER,)
KEY_BYTES=96

def _ior(nr,size): return (2<<30)|(size<<16)|(ord('E')<<8)|nr
IOCG_KEY_BITS=_ior(0x20+EV_KEY,KEY_BYTES)
IOCG_EVENT_BITS=_ior(0x20,KEY_BYTES)
IOCG_REL_BITS=_ior(0x20+EV_REL,KEY_BYTES)
IOCG_KEY_STATE=_ior(0x18,KEY_BYTES)

def _ioctl_bitmap(fd,request,ioctl_fn=fcntl.ioctl):
 buf=bytearray(KEY_BYTES)
 ioctl_fn(fd,request,buf,True)
 return bytes(buf)

def _frame(code,value):
 return EVENT.pack(0,0,EV_KEY,code,value)+EVENT.pack(0,0,EV_SYN,SYN_REPORT,0)

def _key_is_down(bitmap,code): return has_capability(bitmap,code)

class VerifiedOutputs:
 """Checked writer side for exact already-open Builtin and ClickableMouse.

 Callers must first open the exact node read/write and compare it to the
 verified path identity. Any uncertain output makes this bridge fail closed.
 """
 def __init__(self,key_fd,mouse_fd,*,ioctl_fn=fcntl.ioctl,write_fn=os.write,sleep_fn=time.sleep):
  self.key_fd,self.mouse_fd=key_fd,mouse_fd
  self.ioctl_fn,self.write_fn=ioctl_fn,write_fn
  self.sleep_fn=sleep_fn
  self.failed=False;self.closed=False
  self.key_writes=0;self.click_writes=0;self.motion_writes=0;self.emergency_release_attempts=0;self.emergency_release_verified=False;self.emergency_release_errors=[]
  key_caps=_ioctl_bitmap(key_fd,IOCG_KEY_BITS,ioctl_fn)
  key_events=_ioctl_bitmap(key_fd,IOCG_EVENT_BITS,ioctl_fn)
  if not all(has_capability(key_events,code) for code in (EV_SYN,EV_KEY)):
   raise RuntimeError('Builtin-missing-event-capability')
  if not all(_key_is_down(key_caps,code) for code in KEY_CODES):
   raise RuntimeError('Builtin-missing-arrow-capability')
  held=_ioctl_bitmap(key_fd,IOCG_KEY_STATE,ioctl_fn)
  if any(_key_is_down(held,code) for code in KEY_CODES): raise RuntimeError('Builtin-key-already-held')
  ev=_ioctl_bitmap(mouse_fd,IOCG_EVENT_BITS,ioctl_fn)
  rel=_ioctl_bitmap(mouse_fd,IOCG_REL_BITS,ioctl_fn)
  key=_ioctl_bitmap(mouse_fd,IOCG_KEY_BITS,ioctl_fn)
  require_clickable_mouse_capabilities(ev, key)
  if not all(_key_is_down(rel,code) for code in (0,1)):
   raise RuntimeError('ClickableMouse-missing-relative-capability')
  mouse_state=_ioctl_bitmap(mouse_fd,IOCG_KEY_STATE,ioctl_fn)
  if _key_is_down(mouse_state,BTN_LEFT): raise RuntimeError('ClickableMouse-BTN_LEFT-already-held')

 def _managed_key_down(self):
  # LGE RCU is shared with the TV. Its power key can remain latched after
  # boot; only our direction/Enter outputs belong to this bridge.
  state=_ioctl_bitmap(self.key_fd,IOCG_KEY_STATE,self.ioctl_fn)
  return any(_key_is_down(state,code) for code in KEY_CODES)

 def _write_exact(self,fd,packet):
  n=self.write_fn(fd,packet)
  if n!=len(packet): raise OSError(errno.EIO,'short-evdev-frame-write')

 def move_relative(self,dx,dy):
  """Write one complete relative frame; a short write is never retried."""
  if self.failed or self.closed:raise RuntimeError('output-bridge-not-active')
  if type(dx) is not int or type(dy) is not int or not all(-2147483648<=v<=2147483647 for v in (dx,dy)):
   raise ValueError('relative-delta-outside-int32')
  if dx==0 and dy==0:return
  packet=(EVENT.pack(0,0,EV_REL,0,dx)+EVENT.pack(0,0,EV_REL,1,dy)+
          EVENT.pack(0,0,EV_SYN,SYN_REPORT,0))
  try:self._write_exact(self.mouse_fd,packet);self.motion_writes+=1
  except BaseException:self.failed=True;raise

 def key_pulse(self,direction):
  if self.failed or self.closed: raise RuntimeError('output-bridge-not-active')
  if direction not in KEYS: raise ValueError('unrecognized-arrow')
  code=KEYS[direction];first=None;down_attempted=False
  try:
   if self._managed_key_down():
    raise RuntimeError('Builtin-key-held-before-pulse')
   down_attempted=True
   self._write_exact(self.key_fd,_frame(code,1));self.key_writes+=1
   # Match the fourway ioctl-fix trial whose visible arrows were confirmed.
   # The finally block still releases the key if this wait is interrupted.
   self.sleep_fn(.08)
  except BaseException as e:
   first=e
  finally:
   # One release attempt follows every down attempt, including a short write.
   if down_attempted:
    try:
     self._write_exact(self.key_fd,_frame(code,0));self.key_writes+=1
    except BaseException as e:
     if first is None:first=e
  try:
   if self._managed_key_down():
    if first is None:first=RuntimeError('Builtin-key-release-unverified')
  except BaseException as e:
   if first is None:first=e
  if first is not None:
   self.failed=True
   raise first

 def click_frame(self,packet):
  return self._button_frame(self.mouse_fd,BTN_LEFT,packet,'ClickableMouse-BTN_LEFT')

 def select_frame(self,packet):
  return self._button_frame(self.key_fd,KEY_ENTER,packet,'LGE-RCU-ENTER')

 def _button_frame(self,fd,code,packet,label):
  if self.failed or self.closed: raise RuntimeError('output-bridge-not-active')
  if type(packet) is not bytes or len(packet)!=32:
   self.failed=True;raise ValueError('invalid-click-frame-size')
  key=EVENT.unpack(packet[:16]);syn=EVENT.unpack(packet[16:])
  if key[:4]!=(0,0,EV_KEY,code) or key[4] not in (0,1) or syn!=(0,0,EV_SYN,SYN_REPORT,0):
   self.failed=True;raise ValueError(label+'-frame-outside-policy')
  current=_ioctl_bitmap(fd,IOCG_KEY_STATE,self.ioctl_fn)
  down=_key_is_down(current,code)
  if key[4] and down:
   self.failed=True;raise RuntimeError(label+'-already-held')
  if not key[4] and not down:
   self.failed=True;raise RuntimeError(label+'-release-without-owned-down')
  first=None
  try:
   self._write_exact(fd,packet);self.click_writes += int(fd==self.mouse_fd);self.key_writes += int(fd==self.key_fd)
   after=_ioctl_bitmap(fd,IOCG_KEY_STATE,self.ioctl_fn)
   if _key_is_down(after,code)!=(key[4]==1):raise RuntimeError(label+'-state-unverified')
   return len(packet)
  except BaseException as e:
   first=e
   # If this was an attempted press, make one release attempt then verify.
   if key[4]:
    try:
     self._write_exact(fd,_frame(code,0));self.click_writes += int(fd==self.mouse_fd);self.key_writes += int(fd==self.key_fd)
     if _key_is_down(_ioctl_bitmap(fd,IOCG_KEY_STATE,self.ioctl_fn),code):
      raise RuntimeError(label+'-release-unverified')
    except BaseException as release_error:
     first=RuntimeError('click-write-uncertain; release='+type(release_error).__name__)
   self.failed=True
   raise first

 def close(self,close_fn=os.close):
  if self.closed:return
  self.closed=True
  failures=[]
  for fd in (self.mouse_fd,self.key_fd):
   try:close_fn(fd)
   except BaseException as e:failures.append(type(e).__name__)
  if failures: raise RuntimeError('output-fd-close-failed:'+','.join(failures))

 def verify_released(self):
  if self._managed_key_down():
   raise RuntimeError('Builtin-keys-held-at-cleanup')
  if _key_is_down(_ioctl_bitmap(self.mouse_fd,IOCG_KEY_STATE,self.ioctl_fn),BTN_LEFT):
   raise RuntimeError('ClickableMouse-BTN_LEFT-held-at-cleanup')
  return True

 def best_effort_release(self,max_attempts=2):
  """Bounded final key-up pass on our exact, already-open output FDs.

  Called after pipeline shutdown even if TouchClick marked itself closed while
  BTN_LEFT was still down. A failed readback triggers at most two release
  frames per supported key; this never creates a new down event.
  """
  if self.closed: raise RuntimeError('output-bridge-closed-before-release')
  if type(max_attempts) is not int or not 1<=max_attempts<=2:raise ValueError('release-attempt-bound')
  self.emergency_release_verified=False
  for fd,codes,label in ((self.key_fd,KEY_CODES,'LGE RCU'),(self.mouse_fd,(BTN_LEFT,),'ClickableMouse')):
   try:
    state=_ioctl_bitmap(fd,IOCG_KEY_STATE,self.ioctl_fn)
    pending=[code for code in codes if _key_is_down(state,code)]
   except BaseException as e:
    self.emergency_release_errors.append(label+'-state-'+type(e).__name__);pending=list(codes)
   for code in pending:
    for _ in range(max_attempts):
     try:
      state=_ioctl_bitmap(fd,IOCG_KEY_STATE,self.ioctl_fn)
      if not _key_is_down(state,code):break
     except BaseException as e:
      self.emergency_release_errors.append(label+'-read-'+type(e).__name__)
     self.emergency_release_attempts+=1
     try:self._write_exact(fd,_frame(code,0));self.key_writes+=1 if fd==self.key_fd else 0;self.click_writes+=1 if fd==self.mouse_fd else 0
     except BaseException as e:self.emergency_release_errors.append(label+'-write-'+type(e).__name__)
  try:self.verify_released();self.emergency_release_verified=True
  except BaseException as e:self.emergency_release_errors.append('verify-'+type(e).__name__)
  return self.emergency_release_verified

 def summary(self):
  return {'keyFrameWrites':self.key_writes,'clickFrameWrites':self.click_writes,'motionFrameWrites':self.motion_writes,
          'failed':self.failed,'closed':self.closed,'rawReportsPersisted':False,
          'emergencyReleaseAttempts':self.emergency_release_attempts,'emergencyReleaseVerified':self.emergency_release_verified,'emergencyReleaseErrors':list(self.emergency_release_errors),
          'bluetoothWrites':0,'sensorWrites':0,'cccdWrites':0,'uinput':False}
