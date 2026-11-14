"""Archive only this controller's completed handoff files.

Caller independently verifies the receiver completed and exited, and holds the
supervisor lease. File renames are individually atomic, not a transaction;
failures retain the launch intent for recovery and must not trigger a retry.
"""
import state_permissions
import json,os,re,stat
from pathlib import Path
from receiver_result_receipt import APP
from receiver_request_auth import CONTROLLER

def archive_recovered(directory,run,*,owner_uid,state_uid=5999,group=5000):
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run) or type(owner_uid) is not int or owner_uid<=0:raise ValueError('invalid handoff identity')
 d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or ds.st_uid!=state_uid or ds.st_gid!=group or stat.S_IMODE(ds.st_mode) not in state_permissions.directory_modes():raise RuntimeError('unsafe handoff directory')
  originals={}
  for name,app in (('request.json',APP),('controller-start.json',CONTROLLER),('recovery-request.json',APP)):
   b=os.stat(name,dir_fd=d,follow_symlinks=False)
   if not stat.S_ISREG(b.st_mode) or b.st_nlink!=1 or b.st_uid!=owner_uid or b.st_gid!=group or stat.S_IMODE(b.st_mode)!=0o660 or b.st_size>4096:raise RuntimeError('unsafe handoff file')
   f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
   try:
    s=os.fstat(f);raw=os.read(f,4097)
    if (b.st_dev,b.st_ino,b.st_uid,b.st_gid,b.st_size)!=(s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_size) or len(raw)!=s.st_size:raise RuntimeError('handoff file changed')
   finally:os.close(f)
   def unique(pairs):
    out={}
    for k,v in pairs:
     if k in out:raise ValueError('duplicate handoff key')
     out[k]=v
    return out
   obj=json.loads(raw,object_pairs_hook=unique)
   if type(obj) is not dict or obj.get('run')!=run or obj.get('appId')!=app:raise RuntimeError('handoff identity mismatch')
   destination=name[:-5]+'-recovered-'+run+'.json'
   try:os.stat(destination,dir_fd=d,follow_symlinks=False)
   except FileNotFoundError:pass
   else:raise RuntimeError('handoff archive exists')
   originals[name]=(b,destination)
  for name,(before,destination) in originals.items():
   after=os.stat(name,dir_fd=d,follow_symlinks=False)
   if (after.st_dev,after.st_ino,after.st_uid,after.st_gid,after.st_size,after.st_mtime_ns,after.st_ctime_ns)!=(before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_size,before.st_mtime_ns,before.st_ctime_ns):raise RuntimeError('handoff changed before archive')
   os.rename(name,destination,src_dir_fd=d,dst_dir_fd=d);os.fsync(d)
  return True
 finally:os.close(d)
