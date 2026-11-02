"""Run-specific bounded read-only verification for the recorded recovery."""
import hashlib,json,os,stat
from maintenance_guard import RUN

DIGESTS={
 'receiver-result-'+RUN+'.json':'a4ce64d43f28de5c0019076557e39870cd976a5fd38f59d700ca98838f16411b',
 'receiver-recovery-start-'+RUN+'.json':'8a7c0462e81e3581a44246148fc23e373772ab5910695ef2136c49f56fe1d506',
 'receiver-recovery-result-'+RUN+'.json':'9be269a76a8829313c89b69046131ce3fdfd66d5b98cc038cacec2a939afa6c3',
 'recovery-'+RUN+'-1.json':'e3fc42cf8a32b8dff3c1e57f3e0625971747c9e1b3177755275e41ae87a9d6e2',
 'recovery-'+RUN+'-2.json':'09a5f0a0f70ca9b46e57db47a02286cef19569643b48e9c5053a4065e8187860',
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
