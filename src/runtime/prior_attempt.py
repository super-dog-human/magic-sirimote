"""Read-only verification of one confirmed, non-archiving prior attempt."""
import hashlib,json,os,stat
from maintenance_guard import RUN
OP='4240935f00fd4a84966335c6af675ace'
INSPECTION='d7999b9a121a416789259a0a9860c798'
DIGESTS={
 'serial-zero-archive-request.json':(5415,'40b4dfdc3c7e990bac2544b672c77877c2f37aa888dedfa9f24dfd07d8115e84'),
 'serial-zero-archive-intent-'+RUN+'.json':(6959,'09a4f12f9e50dfc947a0655c8d2eaa2adf926ea5a2715209fbcfd94aeca229a0'),
 'serial-zero-archive-result-'+RUN+'.json':(6959,'bc81952df72696dd693cfcac38723ce032784852c06ec017efa85d542e0a7cfe'),
 'maintenance-inspection-result-'+INSPECTION+'.json':(6959,'c73927979a5b29aaf266e4ce630d73e6e728c68b74ff1ba8a340639bd96d7209')}

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
  q=values['serial-zero-archive-request.json'];i=values['serial-zero-archive-intent-'+RUN+'.json'];r=values['serial-zero-archive-result-'+RUN+'.json'];inspection=values['maintenance-inspection-result-'+INSPECTION+'.json']
  if any(type(x) is not dict or x.get('run')!=RUN or x.get('operation')!=OP for x in (q,i,r)) or r.get('status')!='attention' or r.get('errorType')!='RuntimeError':raise RuntimeError('prior outcome mismatch')
  checks=inspection.get('checks');required=('boot','controllerOnly','leaseBinding','nativeIdentity','profilesIdle','receiverAbsent','receiverPackage','recoveryEvidence')
  if inspection.get('operation')!=INSPECTION or inspection.get('noDeviceWrites') is not True or type(checks) is not dict or any(type(checks.get(k)) is not dict or checks[k].get('result') is not True for k in required):raise RuntimeError('inspection outcome mismatch')
  return True
 finally:os.close(d)
