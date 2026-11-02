"""Experimental semantic key sink using an independently validated FD.

No device discovery/open occurs here. The caller must verify the actual FD is
the intended LGE RCU and revalidate its identity before use. The output path was physically tested on the documented G3 baseline;
other devices require their own validation.
"""
import fcntl,os,struct
EVENT=struct.Struct('=iiHHi') # 32-bit Linux input_event, as in TV candidate
# The TV profile maps separate Play and Pause keys. The media-aware layer
# selects one only for a fresh known state.
KEYS={'settings':139,'back':412,'home':773,'play':207,'pause':119}
KEY_BYTES=160
def identity_matches(meta):
 """Match observed G3 LGE RCU attributes, never a guessed event number."""
 return (type(meta) is dict and all(type(meta.get(k)) is int for k in ('major','uid','gid','mode','bus','vendor','product','version')) and meta.get('name')=='LGE RCU' and meta.get('characterDevice') is True and
         meta.get('major')==13 and meta.get('uid')==0 and meta.get('gid')==505 and meta.get('mode')==0o660 and
         (meta.get('bus'),meta.get('vendor'),meta.get('product'),meta.get('version'))==(3,1,1,4))
def _ior(nr):return (2<<30)|(KEY_BYTES<<16)|(ord('E')<<8)|nr
EVIOCGBIT_KEY=_ior(0x21);EVIOCGKEY=_ior(0x18)
def _bitmap(fd,request,ioctl):
 value=bytearray(KEY_BYTES);ioctl(fd,request,value,True);return value
def _frame(code,value):return EVENT.pack(0,0,1,code,value)+EVENT.pack(0,0,0,0,0)
class SystemKeySink:
 def __init__(self,fd,*,identity_check,ioctl=fcntl.ioctl,write=os.write):
  if type(fd) is not int or fd<0 or not all(callable(x) for x in (identity_check,ioctl,write)):raise ValueError('invalid sink')
  self.fd=fd;self.identity_check=identity_check;self.ioctl=ioctl;self.write=write;self.failed=False
  self._identity()
  cap=_bitmap(fd,EVIOCGBIT_KEY,ioctl)
  if not all(cap[code//8]&(1<<(code%8)) for code in KEYS.values()):raise RuntimeError('system key capability missing')
 def _identity(self):
  if self.identity_check(self.fd) is not True:raise RuntimeError('device identity unverified')
 def verify_released(self):
  self._identity();state=_bitmap(self.fd,EVIOCGKEY,self.ioctl)
  return not any(state[code//8]&(1<<(code%8)) for code in KEYS.values())
 def pulse(self,action):
  if self.failed:raise RuntimeError('output disabled')
  if action not in KEYS:raise ValueError('unknown action')
  code=KEYS[action]
  first=None;down_attempted=False
  try:
   self._identity()
   state=_bitmap(self.fd,EVIOCGKEY,self.ioctl)
   # Shared RCU state includes the TV's power latch. Do not alter it.
   if any(state[c//8]&(1<<(c%8)) for c in KEYS.values()):raise RuntimeError('managed system key already held')
   down=_frame(code,1);up=_frame(code,0)
   down_attempted=True
   if self.write(self.fd,down)!=len(down):raise OSError('short key press')
  except BaseException as exc:first=exc
  finally:
   # Exactly one release after any attempted down, including an uncertain
   # short write; never issue a second press or repeated release.
   if down_attempted:
    try:
     self._identity()
     if self.write(self.fd,up)!=len(up):raise OSError('short key release')
    except BaseException as exc:
     if first is None:first=exc
  if down_attempted:
   try:
    self._identity();state=_bitmap(self.fd,EVIOCGKEY,self.ioctl)
    if state[code//8]&(1<<(code%8)):raise RuntimeError('key release unconfirmed')
   except BaseException as exc:
    if first is None:first=exc
  if first is not None:self.failed=True;raise first
