"""Run-bound shared directory for future TV-local receiver coordination.

No directory is created here. Caller independently verifies and supplies the
directory identity; arbitrary filenames are rejected. The caller must omit raw
remote reports; the explicit flag is checked but cannot prove their absence.
"""
import json,os,re,secrets,stat
NAMES={'a-ready','b-ready','cue','abort','a-result','b-result'}
MAX_BYTES=65536
class SharedStore:
 def __init__(self,path,run,identity,group=5000):
  if not isinstance(run,str) or not re.fullmatch('[a-f0-9]{32}',run) or not isinstance(identity,dict) or set(identity)!={'dev','ino','uid','gid'}:raise ValueError('invalid configuration')
  if identity['gid']!=group or any(type(x) is not int for x in identity.values()):raise ValueError('invalid directory identity')
  self.run=run;self.identity=identity.copy();self.group=group;self.path=str(path)
  self.fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
  try:self._check()
  except BaseException:os.close(self.fd);raise
 def _check(self):
  s=os.fstat(self.fd)
  if not stat.S_ISDIR(s.st_mode) or stat.S_IMODE(s.st_mode)!=0o770 or (s.st_dev,s.st_ino,s.st_uid,s.st_gid)!=(self.identity['dev'],self.identity['ino'],self.identity['uid'],self.group):raise RuntimeError('shared-directory-changed')
 def _name(self,kind):
  if kind not in NAMES:raise ValueError('invalid record kind')
  return kind+'-'+self.run+'.json'
 def publish(self,kind,record):
  name=self._name(kind);self._check()
  if not isinstance(record,dict) or record.get('run')!=self.run or record.get('rawReportsPersisted') is not False:raise ValueError('invalid record identity')
  raw=(json.dumps(record,sort_keys=True,separators=(',',':'))+'\n').encode()
  if len(raw)>MAX_BYTES:raise ValueError('record too large')
  temp='.session-'+secrets.token_hex(16);fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o660,dir_fd=self.fd)
  try:
   os.fchmod(fd,0o660)
   with os.fdopen(fd,'wb') as f:
    fd=None;f.write(raw);f.flush();os.fsync(f.fileno())
   self._check();os.link(temp,name,src_dir_fd=self.fd,dst_dir_fd=self.fd,follow_symlinks=False)
  finally:
   if fd is not None:os.close(fd)
   try:os.unlink(temp,dir_fd=self.fd)
   except FileNotFoundError:pass
 def read(self,kind):
  name=self._name(kind);self._check()
  try:st=os.stat(name,dir_fd=self.fd,follow_symlinks=False)
  except FileNotFoundError:return None
  if not stat.S_ISREG(st.st_mode) or st.st_gid!=self.group or stat.S_IMODE(st.st_mode)!=0o660 or st.st_size>MAX_BYTES:raise RuntimeError('record-metadata-invalid')
  f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self.fd)
  try:
   s=os.fstat(f)
   if (s.st_dev,s.st_ino,s.st_size)!=(st.st_dev,st.st_ino,st.st_size):raise RuntimeError('record-changed')
   with os.fdopen(f,'rb') as x:raw=x.read(MAX_BYTES+1)
  except BaseException:
   try:os.close(f)
   except OSError:pass
   raise
  if len(raw)>MAX_BYTES:raise RuntimeError('record-too-large')
  def unique(pairs):
   out={}
   for k,v in pairs:
    if k in out:raise ValueError('duplicate key')
    out[k]=v
   return out
  obj=json.loads(raw,object_pairs_hook=unique)
  if not isinstance(obj,dict) or obj.get('run')!=self.run or obj.get('rawReportsPersisted') is not False:raise RuntimeError('record-identity-invalid')
  return obj
 def close(self):os.close(self.fd)
