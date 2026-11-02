"""Append-only, developer-authenticated, run-bound pre-sensor maintenance."""
import json,os,re,stat,time
from pathlib import Path
from generic_workflow import execute
from generic_guard import build_guard
from maintenance_request import write_record
NAME=re.compile(r'^generic-presensor-request-([a-f0-9]{32})(?:-([a-f0-9]{32}))?\.json$')
HEX=re.compile(r'^[a-f0-9]{32}$')

def read_request(state,*,developer_uid=5415,state_uid=5999,group=5000,clock=time.time):
 d=os.open(Path(state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or (ds.st_uid,ds.st_gid)!=(state_uid,group) or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe request directory')
  names=sorted(n for n in os.listdir(d) if NAME.fullmatch(n))
  if len(names)>128:raise RuntimeError('too many requests')
  live=[]
  for name in names:
   f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
   try:
    s=os.fstat(f);raw=os.read(f,8193);end=os.fstat(f);named=os.stat(name,dir_fd=d,follow_symlinks=False)
    key=lambda x:(x.st_dev,x.st_ino,x.st_uid,x.st_gid,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
    if not stat.S_ISREG(s.st_mode) or ((s.st_uid,s.st_gid,s.st_nlink)!=(developer_uid,group,1) or stat.S_IMODE(s.st_mode) not in (0o640,0o775)) or s.st_size>8192 or len(raw)!=s.st_size or key(s)!=key(end) or key(s)!=key(named):raise RuntimeError('unsafe request')
   finally:os.close(f)
   def unique(pairs):
    out={}
    for k,v in pairs:
     if k in out:raise ValueError('duplicate key')
     out[k]=v
    return out
   q=json.loads(raw,object_pairs_hook=unique)
   if type(q) is not dict or set(q)!={'schema','run','operation','expiresEpochMs','sensor','boot','expected'} or type(q['schema']) is not int or q['schema']!=1 or q['run']!=NAME.fullmatch(name).group(1) or type(q['operation']) is not str or HEX.fullmatch(q['operation']) is None or (NAME.fullmatch(name).group(2) is not None and q['operation']!=NAME.fullmatch(name).group(2)) or type(q['expiresEpochMs']) is not int or type(q['sensor']) is not dict or type(q['boot']) is not dict or set(q['boot'])!={'bootId','btime'} or type(q['boot']['bootId']) is not str or type(q['boot']['btime']) is not int or type(q['expected']) is not dict:raise RuntimeError('invalid request')
   remaining=q['expiresEpochMs']-int(clock()*1000)
   if remaining<=0:continue
   # Boot-widened expired requests are inert; a live request stays strict.
   if stat.S_IMODE(s.st_mode)!=0o640:raise RuntimeError("live request permissions changed")
   if remaining>45000:raise RuntimeError('invalid request expiry')
   live.append(q)
  if len(live)>1:raise RuntimeError('multiple active requests')
  return live[0] if live else None
 finally:os.close(d)

def prior_attempts(state,run,*,state_uid=5999,owner_uid=6959,group=5000):
 if type(run) is not str or HEX.fullmatch(run) is None:raise ValueError('invalid run')
 d=os.open(Path(state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or (ds.st_uid,ds.st_gid)!=(state_uid,group) or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe prior directory')
  pattern=re.compile(r'^generic-presensor-intent-'+run+r'(?:-([a-f0-9]{32}))?\.json$')
  names=sorted(n for n in os.listdir(d) if pattern.fullmatch(n))
  if len(names)>128:raise RuntimeError('too many prior attempts')
  def read(name):
   before=os.stat(name,dir_fd=d,follow_symlinks=False);f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
   try:
    s=os.fstat(f);raw=os.read(f,4097);end=os.fstat(f);named=os.stat(name,dir_fd=d,follow_symlinks=False)
    key=lambda x:(x.st_dev,x.st_ino,x.st_uid,x.st_gid,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
    if not stat.S_ISREG(s.st_mode) or (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_nlink)!=(owner_uid,group,0o640,1) or s.st_size>4096 or len(raw)!=s.st_size or key(before)!=key(s) or key(s)!=key(end) or key(end)!=key(named):raise RuntimeError('prior evidence changed')
    def unique(pairs):
     out={}
     for k,v in pairs:
      if k in out:raise ValueError('duplicate key')
      out[k]=v
     return out
    return json.loads(raw,object_pairs_hook=unique)
   finally:os.close(f)
  for name in names:
   suffix=pattern.fullmatch(name).group(1);intent=read(name)
   result_name='generic-presensor-result-'+run+('-'+suffix if suffix else '')+'.json'
   result=read(result_name)
   if type(intent) is not dict or type(result) is not dict or intent.get('schema')!=1 or result.get('schema')!=1 or intent.get('run')!=run or result.get('run')!=run or type(intent.get('operation')) is not str or HEX.fullmatch(intent['operation']) is None or result.get('operation')!=intent['operation'] or (suffix is not None and intent['operation']!=suffix) or result.get('status')!='attention':raise RuntimeError('prior attempt unresolved')
  return True
 finally:os.close(d)

def run_requested(*,state,lease,context_for,reader=read_request,writer=write_record,workflow=execute,prior=prior_attempts,clock=time.time):
 q=reader(state,clock=clock)
 if q is None:return None
 if lease.held() is not True or not callable(context_for):raise RuntimeError('supervisor lease unavailable')
 run=q['run']
 if prior(state,run) is not True:raise RuntimeError('prior attempts unavailable')
 context=context_for(q)
 gate=build_guard(lease=lease,sensor_observation=q['sensor'],run=run,clock=clock,**context.pop('gate'))
 def guard():
  guard.last_failure=None
  if int(clock()*1000)>=q['expiresEpochMs']:
   guard.last_failure='request-expired';return False
  if gate() is not True:
   guard.last_failure=gate.last_failure;return False
  return True
 guard.last_failure=None
 event={'schema':1,'run':run,'operation':q['operation']}
 writer(state,'generic-presensor-intent-'+run+'-'+q['operation']+'.json',event)
 try:
  if guard() is not True:raise RuntimeError('generic-precondition-'+str(guard.last_failure))
  result=workflow(run=run,expected=q['expected'],guard=guard,**context)
  if type(result) is not dict or result.get('status')!='archived' or result.get('run')!=run:raise RuntimeError('archive outcome unknown')
 except Exception as exc:
  allowed={'generic-precondition-sensor-age','generic-precondition-lease','generic-precondition-process-or-package','generic-precondition-boot','generic-precondition-profiles','generic-precondition-guard-error','generic-precondition-request-expired','generic-precondition-guard','generic-precondition-recovery-present','generic-evidence-invalid','archive outcome unknown','quiescence unavailable','quiescence changed','archive proof changed','journal changed','file proof unavailable'}
  diagnostic=str(exc) if str(exc) in allowed else 'other'
  writer(state,'generic-presensor-result-'+run+'-'+q['operation']+'.json',{**event,'status':'attention','errorType':type(exc).__name__,'diagnostic':diagnostic})
  return {'status':'attention','run':run}
 writer(state,'generic-presensor-result-'+run+'-'+q['operation']+'.json',{**event,'status':'archived','gattLookup':'unknown'})
 return {'status':'archived','run':run}
