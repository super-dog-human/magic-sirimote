"""Read-only verification of one confirmed, non-archiving prior attempt."""
import hashlib,json,os,stat
from next_guard import RUN
OP='d6845420fb864690ada38437d1eddc9a'
DIGESTS={
 'serial-zero-archive-next-request.json':(5415,'cc3ff2c6334d1c23c08bac104ef9c71ca365525fc85136db0b2871776681ebb5'),
 'serial-zero-archive-next-intent-'+RUN+'.json':(6959,'216f5a9fa82dabc8c70418b010a8368a50d5659dd41bb5a9340bb04ebf13dcc2'),
 'serial-zero-archive-next-result-'+RUN+'.json':(6959,'fbaee160c11f9aef8dd0e72f464a38ae1d0114ffba0a97c27ce67108068f8cd1')}

def verify(state,*,digests=DIGESTS,state_uid=5999,group=5000):
 d=os.open(state,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or (ds.st_uid,ds.st_gid)!=(state_uid,group) or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('prior state mismatch')
  values={}
  for name,(owner,digest) in digests.items():
   before=os.stat(name,dir_fd=d,follow_symlinks=False);f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
   try:
    s=os.fstat(f);raw=os.read(f,8193);end=os.fstat(f)
    key=lambda x:(x.st_dev,x.st_ino,x.st_uid,x.st_gid,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))!=(owner,group,0o640) or s.st_size>8192 or len(raw)!=s.st_size or key(before)!=key(s) or key(s)!=key(end) or hashlib.sha256(raw).hexdigest()!=digest:raise RuntimeError('prior evidence mismatch')
    values[name]=json.loads(raw)
   finally:os.close(f)
  q=values['serial-zero-archive-next-request.json'];i=values['serial-zero-archive-next-intent-'+RUN+'.json'];r=values['serial-zero-archive-next-result-'+RUN+'.json']
  if any(type(x) is not dict or x.get('run')!=RUN or x.get('operation')!=OP for x in (q,i,r)) or r.get('status')!='attention' or r.get('errorType')!='RuntimeError' or r.get('diagnostic')!='maintenance-precondition-profiles':raise RuntimeError('prior outcome mismatch')
  return True
 finally:os.close(d)
