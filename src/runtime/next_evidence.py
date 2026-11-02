"""Run-specific bounded read-only verification for the recorded recovery."""
import hashlib,json,os,stat
from next_guard import RUN

DIGESTS={
 'receiver-result-'+RUN+'.json':'4c16595392e99f621697c2b04e052b5fd0937d9dd7d461cacba9c8e2d537becd',
 'receiver-recovery-start-'+RUN+'.json':'adcf5a9351ecc10c54c89e99f7c9cfd005add6ada671bc8027d73592affeab54',
 'receiver-recovery-result-'+RUN+'.json':'1277c9d53dcee90e98807caf7e969483adbde48fa45282eb038d65852481177d',
 'recovery-'+RUN+'-1.json':'8f42ef34369c1c0234bccb2b3e564f8f057eabed6b497e4b0df33e1e03562477',
 'recovery-'+RUN+'-2.json':'cc39591b427c5650dac401acfbc988d7c769e1d449137c6c7937ea62db20db5b',
}
def verify(state,*,digests=DIGESTS,state_uid=5999,owner_uid=5636,group=5000):
 d=os.open(state,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or (ds.st_uid,ds.st_gid)!=(state_uid,group) or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('recovery state mismatch')
  values={}
  for name,digest in digests.items():
   before=os.stat(name,dir_fd=d,follow_symlinks=False)
   f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
   try:
    s=os.fstat(f);raw=os.read(f,4097);end=os.fstat(f)
    key=lambda x:(x.st_dev,x.st_ino,x.st_uid,x.st_gid,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
    if (not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))!=(owner_uid,group,0o640)
        or s.st_size>4096 or len(raw)!=s.st_size or key(before)!=key(s) or key(s)!=key(end) or hashlib.sha256(raw).hexdigest()!=digest):raise RuntimeError('recovery evidence mismatch')
    values[name]=json.loads(raw)
   finally:os.close(f)
  old=values['receiver-result-'+RUN+'.json'];start=values['receiver-recovery-start-'+RUN+'.json'];end=values['receiver-recovery-result-'+RUN+'.json']
  if any(type(v) is not dict or v.get('run')!=RUN for v in values.values()):raise RuntimeError('recovery run mismatch')
  if old.get('status')!='attention' or old.get('sensorStopVerified') is not False or end.get('status')!='attention' or end.get('sensorStopVerified') is not False or start.get('stage')!='starting' or start.get('process')!=end.get('process'):raise RuntimeError('recovery outcome mismatch')
  if values['recovery-'+RUN+'-1.json'].get('stage')!='recovery-intent' or values['recovery-'+RUN+'-2.json'].get('stage')!='recovery-gatt-lookup-intent':raise RuntimeError('recovery stages mismatch')
  return True
 finally:os.close(d)
