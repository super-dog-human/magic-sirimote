"""Bounded, owner-only permission repair for an explicitly pinned file set.

This is an offline primitive, not an installed app or a reboot policy. The
caller must independently stop the relevant applications, pin trusted hashes,
and serialize against all writers. File content and directory names are not
changed. Partial chmod is possible on an error and must be inspected.
"""
import hashlib,os,re,stat
from pathlib import Path

def repair(directory,entries,*,owner=None,group=5000,expected_directory_owner=5999,apply=False):
 if type(entries) is not dict or not entries or len(entries)>64 or type(apply) is not bool:raise ValueError('invalid repair plan')
 owner=os.getuid() if owner is None else owner
 if type(owner) is not int or owner!=os.getuid() or owner<=0:raise ValueError('owner identity unavailable')
 d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);fds=[]
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or ds.st_uid!=expected_directory_owner or ds.st_gid!=group or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe directory')
  for name,item in sorted(entries.items()):
   if type(name) is not str or re.fullmatch(r'[A-Za-z0-9._-]{1,160}',name) is None or name in ('.','..') or type(item) is not dict or set(item)!={'sha256','mode'} or type(item['sha256']) is not str or re.fullmatch('[0-9a-f]{64}',item['sha256']) is None or item['mode'] not in (0o600,0o640,0o660):raise ValueError('invalid repair entry')
   before=os.stat(name,dir_fd=d,follow_symlinks=False)
   if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or (before.st_uid,before.st_gid)!=(owner,group) or stat.S_IMODE(before.st_mode) not in (0o775,item['mode']) or before.st_size>32768:raise RuntimeError('unsafe file metadata')
   f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d);fds.append((name,item,f,before))
   opened=os.fstat(f);raw=os.read(f,32769);after=os.fstat(f)
   def identity(s):return (s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
   if identity(before)!=identity(opened) or identity(opened)!=identity(after) or len(raw)!=opened.st_size or hashlib.sha256(raw).hexdigest()!=item['sha256']:raise RuntimeError('file changed or hash mismatch')
  # All entries have passed before the first chmod. A caller must retain and
  # inspect a partial result if any subsequent operation raises.
  if apply:
   for name,item,f,before in fds:
    current=os.stat(name,dir_fd=d,follow_symlinks=False);opened=os.fstat(f)
    if identity(current)!=identity(opened) or identity(opened)!=identity(before):raise RuntimeError('file changed before chmod')
    os.fchmod(f,item['mode']);changed=os.fstat(f);named=os.stat(name,dir_fd=d,follow_symlinks=False)
    if stat.S_IMODE(changed.st_mode)!=item['mode'] or identity(changed)!=identity(named):raise RuntimeError('mode repair unconfirmed')
    os.fsync(f)
   os.fsync(d)
  return {'status':'repaired' if apply else 'validated','count':len(fds)}
 finally:
  for _,_,f,_ in fds:os.close(f)
  os.close(d)
