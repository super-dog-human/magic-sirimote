"""Strict bounded discovery/open for the two existing input output sinks."""
import errno,fcntl,os,stat,time
from pathlib import Path
from output_bridge import VerifiedOutputs

# TV hardware probe confirmed RCU arrows hide the pointer and select 5-way mode.
KEY_NAME='LGE RCU'
MOUSE_NAME='ClickableMouse'
MAX_EVENT_NODES=128
KEY_BYTES=96
class OutputCloseError(RuntimeError):
 pass
def _ioc(d,t,n,s):return (d<<30)|(s<<16)|(ord(t)<<8)|n
def _ior(n,s):return _ioc(2,'E',n,s)
EV_NAME=lambda size:_ior(0x06,size)
EV_BITS=lambda ev,size:_ior(0x20+ev,size)
def _ioctl(fd,req,size,ioctl_fn):
 b=bytearray(size);ioctl_fn(fd,req,b,True);return bytes(b)
def _cstr(b):return b.split(b'\0',1)[0].decode('utf-8','replace')
def _same(a,b):return (a.st_dev,a.st_ino,a.st_rdev,a.st_mode,a.st_uid,a.st_gid)==(b.st_dev,b.st_ino,b.st_rdev,b.st_mode,b.st_uid,b.st_gid)
def _known_unbound_event_slot(st,index):
 return (stat.S_ISCHR(st.st_mode) and os.major(st.st_rdev)==13 and
         os.minor(st.st_rdev)==64+index)
def _caps(fd,ioctl_fn):
 return {'name':_cstr(_ioctl(fd,EV_NAME(256),256,ioctl_fn)),
  'events':_ioctl(fd,EV_BITS(0,KEY_BYTES),KEY_BYTES,ioctl_fn),
  'keys':_ioctl(fd,EV_BITS(1,KEY_BYTES),KEY_BYTES,ioctl_fn),
  'relative':_ioctl(fd,EV_BITS(2,KEY_BYTES),KEY_BYTES,ioctl_fn)}
def _matches(c):
 from output_bridge import has_capability,KEY_CODES,BTN_LEFT
 if c['name']==KEY_NAME:return all(has_capability(c['events'],n) for n in (0,1)) and all(has_capability(c['keys'],n) for n in KEY_CODES)
 if c['name']==MOUSE_NAME:
  return (all(has_capability(c['events'],n) for n in (0,1,2)) and
          all(has_capability(c['relative'],n) for n in (0,1)) and
          has_capability(c['keys'],BTN_LEFT))
 return False
def _open_verified_outputs_once(root='/dev/input',*,lstat_fn=os.lstat,open_fn=os.open,fstat_fn=os.fstat,ioctl_fn=fcntl.ioctl,close_fn=os.close,clock=time.monotonic,timeout=20):
 deadline=clock()+timeout
 candidates={KEY_NAME:[],MOUSE_NAME:[]};errors={};complete=True;unavailable_event_slots=0
 for i in range(MAX_EVENT_NODES):
  if clock()>deadline:raise TimeoutError('output-node-inventory-deadline')
  path=os.path.join(root,'event'+str(i))
  try:before=lstat_fn(path)
  except OSError as e:
   k=errno.errorcode.get(e.errno,'OTHER');errors[k]=errors.get(k,0)+1
   if e.errno!=errno.ENOENT:complete=False
   continue
  if stat.S_ISLNK(before.st_mode) or not stat.S_ISCHR(before.st_mode):complete=False;continue
  fd=None
  try:fd=open_fn(path,os.O_RDONLY|os.O_NONBLOCK|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0))
  except OSError as e:
   k=errno.errorcode.get(e.errno,'OTHER');errors[k]=errors.get(k,0)+1
   if e.errno==errno.ENXIO and _known_unbound_event_slot(before,i):
    try:after=lstat_fn(path)
    except OSError as check_error:
     check_key=errno.errorcode.get(check_error.errno,'OTHER');errors[check_key]=errors.get(check_key,0)+1;complete=False
    else:
     if _same(before,after):unavailable_event_slots+=1
     else:complete=False
   else:complete=False
   continue
  try:
   opened=fstat_fn(fd);after=lstat_fn(path)
   if not _same(before,opened) or not _same(opened,after):complete=False;continue
   c=_caps(fd,ioctl_fn)
   if clock()>deadline:raise TimeoutError('output-node-inventory-deadline')
   if c['name'] in candidates:
    if not _matches(c):complete=False
    else:candidates[c['name']].append((path,(opened.st_dev,opened.st_ino,opened.st_rdev),opened,c))
  except OSError as e:
   k=errno.errorcode.get(e.errno,'OTHER');errors[k]=errors.get(k,0)+1;complete=False
  except BaseException:complete=False
  finally:
   if fd is not None:
    try:close_fn(fd)
    except BaseException:raise OutputCloseError('output-descriptor-close-unconfirmed')
 if not complete or len(candidates[KEY_NAME])!=1 or len(candidates[MOUSE_NAME])!=1:
  raise RuntimeError('output-node-inventory-incomplete-or-nonunique:'+str({'complete':complete,'counts':{k:len(v) for k,v in candidates.items()},'errors':errors,'unavailableEventSlots':unavailable_event_slots}))
 opened=[]
 try:
  records=[]
  for name in (KEY_NAME,MOUSE_NAME):
   if clock()>deadline:raise TimeoutError('output-node-reopen-deadline')
   path,identity,expected,caps=candidates[name][0]
   fd=open_fn(path,os.O_RDWR|os.O_NONBLOCK|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0));opened.append(fd)
   now=fstat_fn(fd);after=lstat_fn(path)
   verified_caps=_caps(fd,ioctl_fn)
   if clock()>deadline:raise TimeoutError('output-node-reopen-deadline')
   if not _same(expected,now) or not _same(now,after) or not _matches(verified_caps):
    raise RuntimeError('output-node-changed-on-rw-reopen:'+name)
   rec={'path':path,'name':name,'dev':now.st_dev,'inode':now.st_ino,'rdev':now.st_rdev,'uid':now.st_uid,'gid':now.st_gid,'mode':oct(stat.S_IMODE(now.st_mode)),'capabilitiesVerified':True}
   if name==KEY_NAME:rec.update(eventTypes=[0,1],keyCodes=sorted(__import__('output_bridge').KEY_CODES))
   else:rec.update(eventTypes=[0,1,2],keyCodes=[__import__('output_bridge').BTN_LEFT],relativeCodes=[0,1])
   records.append(rec)
  outputs=VerifiedOutputs(opened[0],opened[1],ioctl_fn=ioctl_fn)
  return outputs,records,{'candidateCounts':{k:len(v) for k,v in candidates.items()},'inventoryComplete':True,'errors':errors,'unavailableEventSlots':unavailable_event_slots}
 except BaseException:
  close_failed=False
  for fd in reversed(opened):
   try:close_fn(fd)
   except BaseException:close_failed=True
  if close_failed:raise OutputCloseError('output-descriptor-close-unconfirmed')
  raise


def open_verified_outputs(root='/dev/input',*,allow_retry=None,wait=time.sleep,
                          clock=time.monotonic,timeout=20,retry_window=12,
                          attempt_fn=None,**kwargs):
 """Re-check startup readiness without sending any input events.

 Every attempt performs the complete inventory and identity validation again.
 Retry only with a live connection/lease guard and confirmed descriptor cleanup.
 Both the attempt count and elapsed window are bounded; stop interrupts waiting.
 """
 if allow_retry is not None and not callable(allow_retry):raise ValueError('invalid output retry guard')
 if not 0<retry_window<=20:raise ValueError('invalid output retry window')
 attempt=attempt_fn or _open_verified_outputs_once
 started=clock();deadline=started+retry_window;previous=started
 for index in range(13):
  if allow_retry is not None and allow_retry() is not True:raise RuntimeError('output-startup-guard-lost')
  try:return attempt(root,clock=clock,timeout=min(timeout,max(.01,deadline-clock())) if allow_retry is not None else timeout,**kwargs)
  except OutputCloseError:raise
  except (OSError,RuntimeError) as exc:
   now=clock()
   if allow_retry is None or index==12 or now<previous or now>=deadline or allow_retry() is not True:raise
   previous=now
   wait(min(1.,deadline-now))
   now=clock()
   if now<previous or now>=deadline or allow_retry() is not True:raise exc
   previous=now


def failure_code(exc):
 """Fixed metadata only; no raw exception text is persisted."""
 if isinstance(exc,OutputCloseError):return 'output-open-close'
 if isinstance(exc,TimeoutError):return 'output-open-timeout'
 if isinstance(exc,OSError):
  if exc.errno in (errno.EACCES,errno.EPERM):return 'output-open-permission'
  if exc.errno in (errno.ENOENT,errno.ENODEV,errno.ENXIO):return 'output-open-unavailable'
  return 'output-open-io'
 text=str(exc)
 if text.startswith('output-node-inventory-incomplete-or-nonunique:'):return 'output-open-inventory'
 if text.startswith('output-node-changed-on-rw-reopen:'):return 'output-open-changed'
 if text=='Builtin-key-already-held':return 'output-open-key-held'
 if text=='ClickableMouse-BTN_LEFT-already-held':return 'output-open-mouse-held'
 if text=='output-startup-guard-lost':return 'output-open-guard'
 return 'output-open-other'
