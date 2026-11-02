"""Archive a pre-sensor retained run after independent zero and quiescence proof.

No contents are deleted, no radio operation is issued, and a GATT lookup
outcome remains unknown. The caller must hold a fresh independently verified
sensor-zero observation and provide a guard that rechecks live quiescence.
Partial archives are possible on failure and must be reconciled manually.
"""
import ctypes,hashlib,os,re,stat
from pathlib import Path

def archive(controller_state,receiver_state,*,run,expected,guard,group=5000,state_uid=5999,controller_uid=6959,receiver_uid=5636,rename_noreplace=None):
 if type(run) is not str or re.fullmatch('[0-9a-f]{32}',run) is None or type(expected) is not dict or not callable(guard):raise ValueError('invalid archive context')
 files=[('b','controller-start.json','controller-start-serial-zero-'+run+'.json',controller_uid,0o660),('b','request.json','request-serial-zero-'+run+'.json',controller_uid,0o660),('a','receiver-launch-intent.json','receiver-launch-serial-zero-'+run+'.json',controller_uid,0o640)]
 if set(expected)!={x[1] for x in files}|{'journal'} or type(expected['journal']) is not dict:raise ValueError('invalid archive plan')
 a=os.open(Path(controller_state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);b=os.open(Path(receiver_state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);j=None
 def directory(fd,uid):
  s=os.fstat(fd)
  if not stat.S_ISDIR(s.st_mode) or (s.st_uid,s.st_gid)!=(uid,group) or stat.S_IMODE(s.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe directory')
  return (s.st_dev,s.st_ino)
 def read_file(fd,name,uid,mode,digest):
  if type(digest) is not str or re.fullmatch('[a-f0-9]{64}',digest) is None:raise ValueError('invalid digest')
  before=os.stat(name,dir_fd=fd,follow_symlinks=False);f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
  try:
   s=os.fstat(f);raw=os.read(f,32769);end=os.fstat(f)
   def ident(x):return (x.st_dev,x.st_ino,x.st_uid,x.st_gid,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))!=(uid,group,mode) or s.st_size>32768 or ident(before)!=ident(s) or ident(s)!=ident(end) or len(raw)!=s.st_size or hashlib.sha256(raw).hexdigest()!=digest:raise RuntimeError('file proof unavailable')
   return (s.st_dev,s.st_ino)
  finally:os.close(f)
 def absent(fd,name):
  try:os.stat(name,dir_fd=fd,follow_symlinks=False)
  except FileNotFoundError:return True
  return False
 def rename(srcfd,src,dstfd,dst):
  if rename_noreplace is not None:return rename_noreplace(srcfd,src,dstfd,dst)
  libc=ctypes.CDLL(None,use_errno=True);fn=libc.renameat2
  fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int
  if fn(srcfd,os.fsencode(src),dstfd,os.fsencode(dst),1)!=0:
   err=ctypes.get_errno();raise OSError(err,os.strerror(err))
 try:
  directory(a,state_uid);directory(b,state_uid)
  if guard() is not True:raise RuntimeError('quiescence unavailable')
  planned=[]
  for role,src,dst,uid,mode in files:
   fd=a if role=='a' else b
   if not absent(fd,dst):raise RuntimeError('archive destination exists')
   planned.append((fd,src,dst,uid,mode,expected[src],read_file(fd,src,uid,mode,expected[src])))
  journal_name='borrowed-serial-zero-'+run
  if not absent(b,journal_name):raise RuntimeError('journal destination exists')
  j=os.open('borrowed-active',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=b);journal_id=directory(j,receiver_uid)
  names=sorted(os.listdir(j));want=['borrowed-'+run+'-%02d.json'%i for i in range(1,len(expected['journal'])+1)]
  if names!=want or set(names)!=set(expected['journal']):raise RuntimeError('journal entries differ')
  for name in names:read_file(j,name,receiver_uid,0o640,expected['journal'][name])
  if guard() is not True:raise RuntimeError('quiescence changed')
  # Archive the journal first. The A-side intent is archived last so any
  # partial result remains visibly blocked from normal receiver launch.
  current=os.stat('borrowed-active',dir_fd=b,follow_symlinks=False)
  if (current.st_dev,current.st_ino)!=journal_id or not absent(b,journal_name):raise RuntimeError('journal changed')
  rename(b,'borrowed-active',b,journal_name);os.fsync(b)
  for fd,src,dst,uid,mode,digest,identity in planned:
   if guard() is not True or not absent(fd,dst) or read_file(fd,src,uid,mode,digest)!=identity:raise RuntimeError('archive proof changed')
   rename(fd,src,fd,dst)
   saved=os.stat(dst,dir_fd=fd,follow_symlinks=False)
   if (saved.st_dev,saved.st_ino)!=identity or not absent(fd,src):raise RuntimeError('archive rename mismatch')
   os.fsync(fd)
  return {'status':'archived','run':run,'sensorZero':'independently-observed','gattLookup':'unknown','noDisconnect':True}
 finally:
  if j is not None:os.close(j)
  os.close(b);os.close(a)
