"""Explicit one-shot local maintenance request; offline candidate only.

The request is a trusted developer's assertion of an independent serial read,
not direct proof of the remote state. A durable intent prevents replay.
"""
import json,os,re,stat,time
from pathlib import Path
from next_guard import RUN
from next_maintenance import execute
REQUEST='serial-zero-archive-next-request.json'

def read_request(state,*,developer_uid=5415,state_uid=5999,group=5000,clock=time.time):
 d=os.open(Path(state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or (ds.st_uid,ds.st_gid)!=(state_uid,group) or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe request directory')
  try:f=os.open(REQUEST,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
  except FileNotFoundError:return None
  try:
   s=os.fstat(f);raw=os.read(f,2049);end=os.fstat(f);named=os.stat(REQUEST,dir_fd=d,follow_symlinks=False)
   key=lambda x:(x.st_dev,x.st_ino,x.st_uid,x.st_gid,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or ((s.st_uid,s.st_gid)!=(developer_uid,group) or stat.S_IMODE(s.st_mode) not in (0o640,0o775)) or s.st_size>2048 or len(raw)!=s.st_size or key(s)!=key(end) or key(s)!=key(named):raise RuntimeError('unsafe request')
  finally:os.close(f)
  def unique(pairs):
   out={}
   for k,v in pairs:
    if k in out:raise ValueError('duplicate key')
    out[k]=v
   return out
  q=json.loads(raw,object_pairs_hook=unique)
  if type(q) is not dict or set(q)!={'schema','run','operation','expiresEpochMs','sensor'} or type(q['schema']) is not int or q['schema']!=1 or q['run']!=RUN or type(q['operation']) is not str or re.fullmatch('[0-9a-f]{32}',q['operation']) is None or type(q['expiresEpochMs']) is not int:raise RuntimeError('invalid request')
  remaining=q['expiresEpochMs']-int(clock()*1000)
  if remaining<=0:return None
  # A widened, expired request is inert after a TV boot. Never execute it.
  if stat.S_IMODE(s.st_mode)!=0o640:raise RuntimeError("live request permissions changed")
  if remaining>45000:raise RuntimeError('invalid request expiry')
  return q
 finally:os.close(d)

def write_record(state,name,value,*,state_uid=5999,group=5000):
 d=os.open(Path(state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or (ds.st_uid,ds.st_gid)!=(state_uid,group) or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe record directory')
  f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=d)
  try:
   os.fchmod(f,0o640);s=os.fstat(f)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid() or s.st_gid!=group:raise RuntimeError('unsafe record')
   with os.fdopen(f,'wb',closefd=False) as stream:
    stream.write((json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode());stream.flush();os.fsync(stream.fileno())
  finally:os.close(f)
  os.fsync(d)
 finally:os.close(d)

def run_requested(*,state,lease,context,reader=read_request,writer=write_record,workflow=execute,clock=time.time):
 q=reader(state,clock=clock)
 if q is None:return None
 if lease.held() is not True:raise RuntimeError('supervisor lease unavailable')
 event={'schema':1,'run':RUN,'operation':q['operation']}
 writer(state,'serial-zero-archive-next-intent-'+RUN+'.json',event)
 try:
  if int(clock()*1000)>=q['expiresEpochMs'] or lease.held() is not True:raise RuntimeError('request expired')
  bounded=dict(context)
  original=bounded.get('profiles_idle')
  if not callable(original):raise RuntimeError('missing profile guard')
  bounded['profiles_idle']=lambda: int(clock()*1000)<q['expiresEpochMs'] and original() is True and int(clock()*1000)<q['expiresEpochMs']
  result=workflow(lease=lease,sensor_observation=q['sensor'],clock=clock,**bounded)
  if type(result) is not dict or result.get('status')!='archived' or result.get('run')!=RUN:raise RuntimeError('archive outcome unknown')
 except Exception as exc:
  diagnostic=str(exc) if str(exc) in {'maintenance-precondition-sensor-age','maintenance-precondition-lease','maintenance-precondition-process-or-package','maintenance-precondition-native-identity','maintenance-precondition-lease-binding','maintenance-precondition-controller-processes','maintenance-precondition-receiver-processes','maintenance-precondition-receiver-package','maintenance-precondition-process-check-error','maintenance-precondition-boot','maintenance-precondition-profiles','maintenance-precondition-recovery-evidence','maintenance-precondition-guard-error','request expired','archive outcome unknown'} else 'other'
  writer(state,'serial-zero-archive-next-result-'+RUN+'.json',{**event,'status':'attention','errorType':type(exc).__name__,'diagnostic':diagnostic})
  return {'status':'attention','run':RUN}
 writer(state,'serial-zero-archive-next-result-'+RUN+'.json',{**event,'status':'archived','gattLookup':'unknown'})
 return {'status':'archived','run':RUN}
