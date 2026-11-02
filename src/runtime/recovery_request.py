"""Exact, expiring post-connect receiver request for separate native apps.

No launch, Bluetooth, sensor or input work. State must be preinstalled and
owner-checked. Request ownership/cleanup across app UIDs needs device proof.
"""
import json,os,re,stat,time
from pathlib import Path
from receiver_result_receipt import APP
from recovery_lookup_handoff import validate_reply

def write_recovery_request(directory,run,expires_ms,*,prior_process,gatt_lookup_reply,now_ms=None,state_uid=5999,group=5000):
 now=int(time.time()*1000) if now_ms is None else now_ms
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run) or type(now) is not int or type(expires_ms) is not int or not 0<expires_ms-now<=120000:raise ValueError('invalid receiver request')
 if type(prior_process) is not dict or set(prior_process)!={'pid','startTicks','status'} or type(prior_process['pid']) is not int or prior_process['pid']<=0 or type(prior_process['startTicks']) is not int or prior_process['startTicks']<=0 or type(prior_process['status']) is not dict:raise ValueError('invalid prior receiver process')
 validate_reply(gatt_lookup_reply)
 data={'gattLookupReply':gatt_lookup_reply,'priorProcess':prior_process,'schema':2,'appId':APP,'run':run,'expiresEpochMs':expires_ms};d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  s=os.fstat(d)
  if not stat.S_ISDIR(s.st_mode) or s.st_uid!=state_uid or s.st_gid!=group or stat.S_IMODE(s.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe request directory')
  f=os.open('recovery-request.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o660,dir_fd=d)
  try:
   os.fchmod(f,0o660);x=os.fstat(f)
   if not stat.S_ISREG(x.st_mode) or x.st_nlink!=1 or x.st_uid!=os.getuid() or x.st_gid!=group:raise RuntimeError('unsafe request file')
   with os.fdopen(f,'wb') as stream:
    f=None;stream.write((json.dumps(data,sort_keys=True,separators=(',',':'))+'\n').encode());stream.flush();os.fsync(stream.fileno())
   os.fsync(d)
  finally:
   if f is not None:os.close(f)
 finally:os.close(d)
 return True

def read_recovery_request(directory,*,owner_uid,now_ms=None,state_uid=5999,group=5000):
 now=int(time.time()*1000) if now_ms is None else now_ms
 if type(now) is not int or type(owner_uid) is not int or owner_uid<=0:raise ValueError('invalid clock or expected owner')
 d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or ds.st_uid!=state_uid or ds.st_gid!=group or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe request directory')
  before=os.stat('recovery-request.json',dir_fd=d,follow_symlinks=False)
  if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=owner_uid or before.st_gid!=group or stat.S_IMODE(before.st_mode)!=0o660 or before.st_size>2048:raise RuntimeError('unsafe request')
  f=os.open('recovery-request.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
  try:
   s=os.fstat(f);raw=os.read(f,2049)
   if (s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_size)!=(before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_size) or len(raw)!=s.st_size:raise RuntimeError('request changed')
  finally:os.close(f)
  def unique(pairs):
   out={}
   for k,v in pairs:
    if k in out:raise ValueError('duplicate request key')
    out[k]=v
   return out
  obj=json.loads(raw,object_pairs_hook=unique)
  if type(obj) is not dict or set(obj)!={'schema','appId','run','expiresEpochMs','priorProcess','gattLookupReply'} or type(obj['schema']) is not int or obj['schema']!=2 or obj['appId']!=APP or type(obj['run']) is not str or not re.fullmatch('[a-f0-9]{32}',obj['run']) or type(obj['expiresEpochMs']) is not int or not 0<=obj['expiresEpochMs']-now<=120000:raise RuntimeError('request invalid or expired')
  validate_reply(obj['gattLookupReply'])
  prior=obj['priorProcess']
  if type(prior) is not dict or set(prior)!={'pid','startTicks','status'} or type(prior['pid']) is not int or prior['pid']<=0 or type(prior['startTicks']) is not int or prior['startTicks']<=0 or type(prior['status']) is not dict:raise RuntimeError('invalid prior receiver process')
  after=os.stat('recovery-request.json',dir_fd=d,follow_symlinks=False)
  if (after.st_dev,after.st_ino,after.st_uid,after.st_gid,after.st_size,after.st_mtime_ns,after.st_ctime_ns)!=(before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_size,before.st_mtime_ns,before.st_ctime_ns):raise RuntimeError('request changed after read')
  return obj
 finally:os.close(d)
