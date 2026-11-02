"""Open the fixed run-bound shared session from an app-owned request."""
import json,os,re,stat
from shared_session_store import SharedStore
def open_from_request(state,app_id,run):
 if not isinstance(run,str) or not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('invalid run')
 path=os.path.join(str(state),'request.json');s=os.lstat(path)
 if not stat.S_ISREG(s.st_mode) or stat.S_ISLNK(s.st_mode) or s.st_gid!=5000 or stat.S_IMODE(s.st_mode)!=0o660 or s.st_size>4096:raise RuntimeError('invalid request metadata')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  f=os.fstat(fd)
  if (f.st_dev,f.st_ino,f.st_size)!=(s.st_dev,s.st_ino,s.st_size):raise RuntimeError('request changed')
  with os.fdopen(fd,'rb') as inp:fd=None;raw=inp.read(4097)
 finally:
  if fd is not None:os.close(fd)
 if len(raw)>4096:raise RuntimeError('request too large')
 def unique(items):
  out={}
  for k,v in items:
   if k in out:raise ValueError('duplicate key')
   out[k]=v
  return out
 q=json.loads(raw,object_pairs_hook=unique);expected='/dev/shm/codex-siri-session-'+run
 if not isinstance(q,dict) or q.get('appId')!=app_id or q.get('run')!=run or q.get('sharedPath')!=expected:raise RuntimeError('request identity mismatch')
 return SharedStore(expected,run,q.get('sharedIdentity'))
def publish(store,kind,record):
 if not isinstance(record,dict):raise ValueError('record must be object')
 store.publish(kind,{**record,'rawReportsPersisted':False})
