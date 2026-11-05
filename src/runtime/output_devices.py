"""Strict bounded discovery/open for the two existing input output sinks."""
import copy,errno,fcntl,json,os,re,stat,time
from output_sysfs import InventoryUnavailable
from pathlib import Path
from output_bridge import VerifiedOutputs

# TV hardware probe confirmed RCU arrows hide the pointer and select 5-way mode.
KEY_NAME='LGE RCU'
MOUSE_NAME='ClickableMouse'
MAX_EVENT_NODES=128
KEY_BYTES=96
def _report(value):
 try:print(json.dumps(value),flush=True)
 except OSError:pass

class OutputCloseError(RuntimeError):
 pass
class OutputSelectionChanged(RuntimeError):
 pass
class OutputInventoryIncomplete(RuntimeError):
 def __init__(self,*,complete,counts,errors,unavailable):
  self.details={'complete':complete,'counts':counts,'errors':errors,'unavailableEventSlots':unavailable}
  super().__init__('output-node-inventory-incomplete-or-nonunique:'+str(self.details))
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
def _caps(fd,ioctl_fn,*,name=None):
 return {'name':_cstr(_ioctl(fd,EV_NAME(256),256,ioctl_fn)) if name is None else name,
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
def _open_verified_outputs_once(root='/dev/input',*,lstat_fn=os.lstat,open_fn=os.open,fstat_fn=os.fstat,ioctl_fn=fcntl.ioctl,close_fn=os.close,clock=time.monotonic,timeout=20,allow_missing_mouse=False,sysfs_inventory=None,sysfs_check=None,unregistered_check=None):
 if type(allow_missing_mouse) is not bool:raise ValueError('invalid deferred mouse policy')
 deadline=clock()+timeout
 candidates={KEY_NAME:[],MOUSE_NAME:[]};errors={};complete=True;unavailable_event_slots=0;seen=set();skipped=set()
 for i in range(MAX_EVENT_NODES):
  if clock()>deadline:raise TimeoutError('output-node-inventory-deadline')
  path=os.path.join(root,'event'+str(i))
  try:before=lstat_fn(path)
  except OSError as e:
   k=errno.errorcode.get(e.errno,'OTHER');errors[k]=errors.get(k,0)+1
   if e.errno!=errno.ENOENT:complete=False
   continue
  if stat.S_ISLNK(before.st_mode) or not stat.S_ISCHR(before.st_mode):complete=False;continue
  if sysfs_inventory is not None and i not in sysfs_inventory and _known_unbound_event_slot(before,i):
   if unregistered_check(i) is not True:raise InventoryUnavailable('kernel event registration ambiguous')
   after=lstat_fn(path)
   if not _same(before,after):
    raise InventoryUnavailable('unbound event node changed')
   unavailable_event_slots+=1;skipped.add(i)
   continue
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
   name=_cstr(_ioctl(fd,EV_NAME(256),256,ioctl_fn))
   if sysfs_inventory is not None:
    if i not in sysfs_inventory or not _known_unbound_event_slot(opened,i) or name!=sysfs_inventory[i][0]:
     raise InventoryUnavailable('kernel and device inventory differ')
    seen.add(i)
   # Every accessible node is still identified. Only the two exact output
   # names need capability queries; unrelated devices cannot be candidates.
   if name not in candidates:continue
   c=_caps(fd,ioctl_fn,name=name)
   if clock()>deadline:raise TimeoutError('output-node-inventory-deadline')
   if c['name'] in candidates:
    if not _matches(c):complete=False
    else:candidates[c['name']].append((path,(opened.st_dev,opened.st_ino,opened.st_rdev),opened,c))
  except OSError as e:
   k=errno.errorcode.get(e.errno,'OTHER');errors[k]=errors.get(k,0)+1;complete=False
  except InventoryUnavailable:raise
  except BaseException:complete=False
  finally:
   if fd is not None:
    try:close_fn(fd)
    except BaseException:raise OutputCloseError('output-descriptor-close-unconfirmed')
 if sysfs_inventory is not None and (seen!=set(sysfs_inventory) or sysfs_check()!=sysfs_inventory or any(unregistered_check(i) is not True for i in skipped)):raise InventoryUnavailable('kernel inventory changed or incomplete')
 if not complete or len(candidates[KEY_NAME])!=1 or len(candidates[MOUSE_NAME]) not in ((0,1) if allow_missing_mouse else (1,)):
  raise OutputInventoryIncomplete(complete=complete,counts={k:len(v) for k,v in candidates.items()},errors=errors,unavailable=unavailable_event_slots)
 outputs,records=_reopen_outputs(candidates,deadline=deadline,lstat_fn=lstat_fn,open_fn=open_fn,fstat_fn=fstat_fn,ioctl_fn=ioctl_fn,close_fn=close_fn,clock=clock,allow_missing_mouse=allow_missing_mouse)
 return outputs,records,{'candidateCounts':{k:len(v) for k,v in candidates.items()},'inventoryComplete':True,'errors':errors,'unavailableEventSlots':unavailable_event_slots,'inventorySource':'sysfs-verified' if sysfs_inventory is not None else 'full-device-scan'}

def _reopen_outputs(candidates,*,deadline,lstat_fn,open_fn,fstat_fn,ioctl_fn,close_fn,clock,allow_missing_mouse=False):
 opened=[]
 try:
  records=[]
  for name in (KEY_NAME,MOUSE_NAME):
   if name==MOUSE_NAME and allow_missing_mouse and not candidates[name]:continue
   if clock()>deadline:raise TimeoutError('output-node-reopen-deadline')
   path,identity,expected,caps=candidates[name][0]
   fd=open_fn(path,os.O_RDWR|os.O_NONBLOCK|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0));opened.append(fd)
   now=fstat_fn(fd);after=lstat_fn(path)
   verified_caps=_caps(fd,ioctl_fn)
   if clock()>deadline:raise TimeoutError('output-node-reopen-deadline')
   if not _same(expected,now) or not _same(now,after) or verified_caps['name']!=name or not _matches(verified_caps):
    raise OutputSelectionChanged('output-node-changed-on-rw-reopen:'+name)
   rec={'path':path,'name':name,'dev':now.st_dev,'inode':now.st_ino,'rdev':now.st_rdev,'uid':now.st_uid,'gid':now.st_gid,'mode':oct(stat.S_IMODE(now.st_mode)),'capabilitiesVerified':True}
   if name==KEY_NAME:rec.update(eventTypes=[0,1],keyCodes=sorted(__import__('output_bridge').KEY_CODES))
   else:rec.update(eventTypes=[0,1,2],keyCodes=[__import__('output_bridge').BTN_LEFT],relativeCodes=[0,1])
   records.append(rec)
  options={'allow_missing_mouse':True} if allow_missing_mouse else {}
  outputs=VerifiedOutputs(opened[0],opened[1] if len(opened)>1 else None,ioctl_fn=ioctl_fn,**options)
  return outputs,records
 except BaseException:
  close_failed=False
  for fd in reversed(opened):
   try:close_fn(fd)
   except BaseException:close_failed=True
  if close_failed:raise OutputCloseError('output-descriptor-close-unconfirmed')
  raise


def _open_with_sysfs(root='/dev/input',*,inventory_fn=None,unregistered_fn=None,**kwargs):
 from output_sysfs import inventory,unregistered
 read=inventory if inventory_fn is None else inventory_fn
 try:first=read()
 except (OSError,ValueError,InventoryUnavailable):first=None
 def recheck():
  try:return read()
  except (OSError,ValueError,InventoryUnavailable) as error:raise InventoryUnavailable('sysfs recheck unavailable') from error
 if first is not None:
  try:
   return _open_verified_outputs_once(root,sysfs_inventory=first,sysfs_check=recheck,unregistered_check=unregistered_fn or unregistered,**kwargs)
  except InventoryUnavailable:pass
 # Unknown/changed metadata never authorizes a skipped device. The original
 # complete scan handles permissions, missing nodes and nonunique targets.
 return _open_verified_outputs_once(root,**kwargs)


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
 attempt=attempt_fn or _open_with_sysfs
 started=clock();deadline=started+retry_window;previous=started
 for index in range(13):
  if allow_retry is not None and allow_retry() is not True:raise RuntimeError('output-startup-guard-lost')
  try:
   result=attempt(root,clock=clock,timeout=min(timeout,max(.01,deadline-clock())) if allow_retry is not None else timeout,**kwargs)
   _report({'stage':'output-discovery-ready','attempts':index+1,'elapsedMs':round((clock()-started)*1000),'inventorySource':result[2].get('inventorySource','unknown') if type(result) is tuple and len(result)==3 and type(result[2]) is dict else 'unknown'})
   return result
  except OutputCloseError:raise
  except (OSError,RuntimeError) as exc:
   now=clock()
   if allow_retry is None or index==12 or now<previous or now>=deadline or allow_retry() is not True:raise
   report={'stage':'output-discovery-retry','attempt':index+1,'elapsedMs':round((now-started)*1000),'reason':failure_code(exc)}
   if isinstance(exc,OutputInventoryIncomplete):report['inventory']=exc.details
   _report(report)
   previous=now
   delay=min(1.,deadline-now)
   if (attempt_fn is None and isinstance(exc,OutputInventoryIncomplete)
       and exc.details['complete'] is True
       and exc.details['counts']=={KEY_NAME:1,MOUSE_NAME:0}):
    from output_sysfs import wait_for_mouse
    if wait_for_mouse(delay,wait=wait,guard=allow_retry,clock=clock):
     _report({'stage':'pointer-kernel-ready-hint','elapsedMs':round((clock()-started)*1000)})
   else:wait(delay)
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


def reopen_selected_outputs(records,root='/dev/input',*,lstat_fn=os.lstat,open_fn=os.open,
                            fstat_fn=os.fstat,ioctl_fn=fcntl.ioctl,close_fn=os.close,
                            clock=time.monotonic):
 """Reopen the exact in-memory selection, checking identity and neutral state.

 Records must come from this worker's earlier complete unique inventory. No
 live descriptors or authority survive idle; the caller still guards each
 session. Changed nodes require a new full inventory, not guessed replacements.
 """
 if type(records) is not list or len(records)!=2:raise ValueError('invalid output selection')
 candidates={KEY_NAME:[],MOUSE_NAME:[]};deadline=clock()+5
 for name,record in zip((KEY_NAME,MOUSE_NAME),records):
  if (type(record) is not dict or record.get('name')!=name or record.get('capabilitiesVerified') is not True
      or type(record.get('path')) is not str
      or not re.fullmatch(re.escape(root)+r'/event(?:[0-9]|[1-9][0-9]|1[01][0-9]|12[0-7])',record['path'])):
   raise ValueError('invalid output selection')
  expected=lstat_fn(record['path'])
  fields={'dev':expected.st_dev,'inode':expected.st_ino,'rdev':expected.st_rdev,'uid':expected.st_uid,'gid':expected.st_gid}
  if (not stat.S_ISCHR(expected.st_mode)
      or any(type(record.get(k)) is not int or record[k]!=v for k,v in fields.items())
      or record.get('mode')!=oct(stat.S_IMODE(expected.st_mode))):
   raise OutputSelectionChanged('output-selection-changed')
  candidates[name].append((record['path'],None,expected,None))
 return _reopen_outputs(candidates,deadline=deadline,lstat_fn=lstat_fn,open_fn=open_fn,
                        fstat_fn=fstat_fn,ioctl_fn=ioctl_fn,close_fn=close_fn,clock=clock)


class OutputSelection:
 """An in-memory path hint scoped to one receiver worker, never a saved grant."""
 def __init__(self,scan=open_verified_outputs,reopen=reopen_selected_outputs):
  self.scan=scan;self.reopen=reopen;self.records=None
 def open(self,*,allow_retry,wait,allow_missing_mouse=False):
  if allow_retry() is not True:raise RuntimeError('output-startup-guard-lost')
  previous=self.records;self.records=None
  if previous is not None:
   try:
    outputs,records=self.reopen(previous)
   except OutputSelectionChanged:pass
   except OSError as exc:
    if exc.errno not in (errno.ENOENT,errno.ENODEV,errno.ENXIO):raise
   else:
    self.records=copy.deepcopy(records);return outputs,records
  options={'allow_missing_mouse':True} if allow_missing_mouse else {}
  outputs,records,_=self.scan(allow_retry=allow_retry,wait=wait,**options)
  if len(records)==2:self.records=copy.deepcopy(records)
  return outputs,records
