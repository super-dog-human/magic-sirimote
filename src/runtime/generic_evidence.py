"""Verify fixed-shape pre-sensor records for a run without changing files."""
import hashlib,json,os,re,stat
from pathlib import Path
HEX=re.compile(r'^[0-9a-f]{64}$')
RUN=re.compile(r'^[0-9a-f]{32}$')

def verify(controller_state,receiver_state,*,run,expected,state_uid=5999,controller_uid=6959,receiver_uid=5636,group=5000):
 if type(run) is not str or not RUN.fullmatch(run) or type(expected) is not dict:raise ValueError('invalid run')
 count=len(expected.get('journal',{}))
 if count not in (0,2,4,5,6):raise ValueError('invalid journal count')
 journal_names=['borrowed-'+run+'-%02d.json'%i for i in range(1,count+1)]
 file_names=('receiver-launch-intent.json','controller-start.json','request.json','receiver-start-'+run+'.json','receiver-result-'+run+'.json')
 if set(expected)!=set(file_names)|{'journal'} or type(expected['journal']) is not dict or set(expected['journal'])!=set(journal_names) or any(type(x) is not str or not HEX.fullmatch(x) for x in [*(expected[n] for n in file_names),*expected['journal'].values()]):raise ValueError('invalid evidence plan')
 a=os.open(Path(controller_state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);b=os.open(Path(receiver_state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);j=None
 def directory(fd,uid):
  s=os.fstat(fd)
  if not stat.S_ISDIR(s.st_mode) or (s.st_uid,s.st_gid)!=(uid,group) or stat.S_IMODE(s.st_mode) not in (0o770,0o775):raise RuntimeError('directory mismatch')
 def read(fd,name,uid,mode,digest):
  before=os.stat(name,dir_fd=fd,follow_symlinks=False);f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
  try:
   s=os.fstat(f);raw=os.read(f,8193);end=os.fstat(f);named=os.stat(name,dir_fd=fd,follow_symlinks=False)
   key=lambda x:(x.st_dev,x.st_ino,x.st_uid,x.st_gid,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
   if not stat.S_ISREG(s.st_mode) or (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_nlink)!=(uid,group,mode,1) or s.st_size>8192 or len(raw)!=s.st_size or key(before)!=key(s) or key(s)!=key(end) or key(end)!=key(named) or hashlib.sha256(raw).hexdigest()!=digest:raise RuntimeError('evidence changed')
   def unique(pairs):
    out={}
    for k,v in pairs:
     if k in out:raise ValueError('duplicate key')
     out[k]=v
    return out
   return json.loads(raw,object_pairs_hook=unique)
  finally:os.close(f)
 try:
  directory(a,state_uid);directory(b,state_uid)
  intent=read(a,'receiver-launch-intent.json',controller_uid,0o640,expected['receiver-launch-intent.json'])
  start=read(b,'controller-start.json',controller_uid,0o660,expected['controller-start.json'])
  request=read(b,'request.json',controller_uid,0o660,expected['request.json'])
  receiver_start=read(b,'receiver-start-'+run+'.json',receiver_uid,0o640,expected['receiver-start-'+run+'.json'])
  result=read(b,'receiver-result-'+run+'.json',receiver_uid,0o640,expected['receiver-result-'+run+'.json'])
  if any(type(v) is not dict or v.get('run')!=run for v in (intent,start,request,receiver_start,result)):raise RuntimeError('run mismatch')
  if intent.get('stage')!='receiver-launch-intent' or receiver_start.get('stage')!='starting' or result.get('status')!='attention' or result.get('sensorStopVerified') is not False or result.get('journalArchived') is not False or receiver_start.get('process')!=result.get('process'):raise RuntimeError('receipt mismatch')
  names=os.listdir(b)
  if any(n in ('recovery-request.json','recovery-controller-start.json') or n.startswith('recovery-'+run+'-') or n.startswith('receiver-recovery-start-'+run) or n.startswith('receiver-recovery-result-'+run) for n in names):raise RuntimeError('recovery attempt exists')
  j=os.open('borrowed-active',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=b);directory(j,receiver_uid)
  if sorted(os.listdir(j))!=journal_names:raise RuntimeError('journal differs')
  records=[read(j,n,receiver_uid,0o640,expected['journal'][n]) for n in journal_names]
  if not records:
   # An empty, intact journal plus the setup-stage failure identifies the path
   # before any receiver-side mutation. The workflow still requires a fresh,
   # independent sensor-zero read and exclusive app/process checks.
   if result.get('diagnostic')!='setup-input-start' or any(result.get(k) is not None for k in ('counts','frameCounts','phase','previousPhase')):raise RuntimeError('empty journal without pre-input failure')
  elif count in (4,5,6):
   from borrowed_runtime_journal import inspect_journal
   evidence=inspect_journal(Path(receiver_state)/'borrowed-active',run,state_uid=receiver_uid,owner_uid=receiver_uid,group=group)
   allowed=[]
   for first in (['f0af-intent','f0af-ack'],['prelaunch-input-intent','prelaunch-input-ack']):
    allowed.append(first+['gatt-lookup-intent','gatt-lookup-unknown'])
    base=first+['gatt-lookup-intent','borrowed-view-obtained']
    allowed.extend([base,base+['notification-config-intent'],base+['notification-config-intent','notification-enabled']])
   # Notification enable is an intended operational setting and may have
   # occurred. This proves only that sensor enabling was never attempted.
   if evidence.get('status')!='no-sensor-enable-recorded' or evidence.get('stages') not in allowed:raise RuntimeError('not a pre-sensor preparation failure')
   if result.get('phase')!='prepare' or result.get('frameCounts')!={'keyFrameWrites':0,'clickFrameWrites':0,'motionFrameWrites':0}:raise RuntimeError('lookup failure output uncertain')
  elif any(type(x) is not dict or x.get('run')!=run for x in records) or [x.get('stage') for x in records] not in (['f0af-intent','f0af-ack'],['prelaunch-input-intent','prelaunch-input-ack']):raise RuntimeError('not a pre-sensor journal')
  return True
 finally:
  if j is not None:os.close(j)
  os.close(b);os.close(a)

def no_recovery(receiver_state,*,run,state_uid=5999,group=5000):
 if type(run) is not str or not RUN.fullmatch(run):raise ValueError('invalid run')
 d=os.open(Path(receiver_state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  s=os.fstat(d)
  if not stat.S_ISDIR(s.st_mode) or (s.st_uid,s.st_gid)!=(state_uid,group) or stat.S_IMODE(s.st_mode) not in (0o770,0o775):return False
  names=os.listdir(d)
  return not any(n in ('recovery-request.json','recovery-controller-start.json') or n.startswith('recovery-'+run+'-') or n.startswith('receiver-recovery-start-'+run) or n.startswith('receiver-recovery-result-'+run) for n in names)
 finally:os.close(d)
