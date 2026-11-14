"""Run-bound controller startup self-report for post-connect handoff.

The reader must independently validate the sender package and live PID before
trusting this record. No launch or device operation occurs here.
"""
import state_permissions
import json,os,re,stat
from pathlib import Path
from receiver_request_auth import CONTROLLER

def write_record(directory,run,process,*,state_uid=5999,group=5000,name='controller-start.json'):
 if name not in ('controller-start.json','recovery-controller-start.json'):raise ValueError('invalid controller record name')
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run) or type(process) is not dict or set(process)!={'pid','startTicks','status'} or type(process.get('pid')) is not int or process['pid']!=os.getpid() or type(process.get('startTicks')) is not int or process['startTicks']<=0 or type(process.get('status')) is not dict:raise ValueError('invalid controller record')
 data={'schema':1,'appId':CONTROLLER,'run':run,'process':process};raw=(json.dumps(data,sort_keys=True,separators=(',',':'))+'\n').encode()
 if len(raw)>4096:raise ValueError('controller record too large')
 d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  s=os.fstat(d)
  if not stat.S_ISDIR(s.st_mode) or s.st_uid!=state_uid or s.st_gid!=group or stat.S_IMODE(s.st_mode) not in state_permissions.directory_modes():raise RuntimeError('unsafe controller destination')
  f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o660,dir_fd=d)
  try:
   os.fchmod(f,0o660);x=os.fstat(f)
   if not stat.S_ISREG(x.st_mode) or x.st_nlink!=1 or x.st_uid!=os.getuid() or x.st_gid!=group:raise RuntimeError('unsafe controller file')
   with os.fdopen(f,'wb') as stream:
    f=None;stream.write(raw);stream.flush();os.fsync(stream.fileno())
   os.fsync(d)
  finally:
   if f is not None:os.close(f)
 finally:os.close(d)
 return True

def read_record(directory,run=None,*,state_uid=5999,group=5000,name='controller-start.json',historical=False):
 if name not in ('controller-start.json','recovery-controller-start.json'):raise ValueError('invalid controller record name')
 if run is not None and (type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run)):raise ValueError('invalid run')
 d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or ds.st_uid!=state_uid or ds.st_gid!=group or stat.S_IMODE(ds.st_mode) not in state_permissions.directory_modes():raise RuntimeError('unsafe controller destination')
  before=os.stat(name,dir_fd=d,follow_symlinks=False)
  if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_gid!=group or before.st_uid<=0 or stat.S_IMODE(before.st_mode) not in (state_permissions.retained_modes(0o660) if historical is True else (0o660,)) or before.st_size>4096:raise RuntimeError('unsafe controller record')
  f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
  try:
   s=os.fstat(f);raw=os.read(f,4097)
   if (s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_size)!=(before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_size) or len(raw)!=s.st_size:raise RuntimeError('controller record changed')
  finally:os.close(f)
  def unique(pairs):
   out={}
   for k,v in pairs:
    if k in out:raise ValueError('duplicate controller key')
    out[k]=v
   return out
  record=json.loads(raw,object_pairs_hook=unique);p=record.get('process') if type(record) is dict else None
  if type(record) is not dict or set(record)!={'schema','appId','run','process'} or type(record['schema']) is not int or record['schema']!=1 or record['appId']!=CONTROLLER or type(record['run']) is not str or not re.fullmatch('[a-f0-9]{32}',record['run']) or (run is not None and record['run']!=run) or type(p) is not dict or set(p)!={'pid','startTicks','status'} or type(p['pid']) is not int or p['pid']<=0 or type(p['startTicks']) is not int or p['startTicks']<=0 or type(p['status']) is not dict:raise RuntimeError('controller record invalid')
  uids=p['status'].get('Uid','').split()
  if len(uids)!=4 or uids!=[str(before.st_uid)]*4:raise RuntimeError('controller owner mismatch')
  after=os.stat(name,dir_fd=d,follow_symlinks=False)
  if (after.st_dev,after.st_ino,after.st_uid,after.st_gid,after.st_size,after.st_mtime_ns,after.st_ctime_ns)!=(before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_size,before.st_mtime_ns,before.st_ctime_ns):raise RuntimeError('controller record changed after read')
  return record
 finally:os.close(d)
