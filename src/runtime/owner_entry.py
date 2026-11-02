"""Request-bound, one-shot app-owned permission repair, offline candidate.

The caller embeds an independently checked plan in its app package. The
request can only select the exact role/run; it cannot supply paths, hashes or
commands. A durable intent blocks replay even if the app exits unexpectedly.
"""
import json,os,re,stat,time
from pathlib import Path
from owner_workflow import run
REQUEST='owner-mode-repair-request.json'

def _request(state,role,run_id,*,developer_uid=5415,group=5000,state_uid=5999,now=time.time):
 d=os.open(Path(state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or (ds.st_uid,ds.st_gid)!=(state_uid,group) or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('invalid request directory')
  try:f=os.open(REQUEST,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
  except FileNotFoundError:return None
  try:
   s=os.fstat(f);raw=os.read(f,2049);end=os.fstat(f)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or (s.st_uid,s.st_gid)!=(developer_uid,group) or stat.S_IMODE(s.st_mode)!=0o640 or s.st_size>2048 or len(raw)!=s.st_size or (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)!=(end.st_dev,end.st_ino,end.st_size,end.st_mtime_ns,end.st_ctime_ns):raise RuntimeError('invalid request file')
  finally:os.close(f)
  def unique(pairs):
   x={}
   for k,v in pairs:
    if k in x:raise ValueError('duplicate request key')
    x[k]=v
   return x
  q=json.loads(raw,object_pairs_hook=unique)
  if type(q) is not dict or set(q)!={'schema','role','run','operation','expiresEpochMs'} or q.get('schema')!=1 or q.get('role')!=role or q.get('run')!=run_id or type(q.get('operation')) is not str or re.fullmatch('[a-f0-9]{32}',q['operation']) is None or type(q.get('expiresEpochMs')) is not int or not 0<q['expiresEpochMs']-int(now()*1000)<=180000:raise RuntimeError('request binding invalid')
  return q
 finally:os.close(d)

def _write(state,name,value,*,group=5000,state_uid=5999):
 d=os.open(Path(state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or (ds.st_uid,ds.st_gid)!=(state_uid,group) or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('invalid receipt directory')
  f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=d)
  try:
   os.fchmod(f,0o640);s=os.fstat(f)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid() or s.st_gid!=group:raise RuntimeError('invalid receipt owner')
   raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
   with os.fdopen(f,'wb',closefd=False) as stream:stream.write(raw);stream.flush();os.fsync(f)
  finally:os.close(f)
  os.fsync(d)
 finally:os.close(d)

def execute_if_requested(role,plan,*,controller_state,receiver_state,journal_state,guard,developer_uid=5415,group=5000,state_uid=5999,now=time.time,workflow=run):
 if role not in ('controller','receiver') or type(plan) is not dict or not callable(guard) or not callable(workflow):raise ValueError('invalid entry context')
 state=controller_state if role=='controller' else receiver_state
 q=_request(state,role,plan['run'],developer_uid=developer_uid,group=group,state_uid=state_uid,now=now)
 if q is None:return None
 if guard() is not True:raise RuntimeError('repair process not exclusive')
 event={'schema':1,'role':role,'run':plan['run'],'operation':q['operation']}
 _write(state,'owner-repair-intent-'+q['operation']+'.json',event,group=group,state_uid=state_uid)
 try:
  result=workflow(role,plan,controller_state=controller_state,receiver_state=receiver_state,journal_state=journal_state,guard=guard,apply=True)
  if type(result) is not dict or result.get('status')!='repaired' or result.get('run')!=plan['run'] or result.get('role')!=role or result.get('sensorState')!='unverified':raise RuntimeError('repair result invalid')
 except Exception as exc:
  _write(state,'owner-repair-result-'+q['operation']+'.json',{**event,'status':'attention','errorType':type(exc).__name__},group=group,state_uid=state_uid)
  return {'status':'attention','role':role}
 _write(state,'owner-repair-result-'+q['operation']+'.json',{**event,'status':'repaired','sensorState':'unverified'},group=group,state_uid=state_uid)
 return {'status':'repaired','role':role}
