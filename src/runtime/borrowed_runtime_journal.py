"""Durable, one-run mutation journal for the borrowed runtime.

Each record is created exclusively and synced before returning. Partial
files or a pre-existing run require recovery, never automatic reuse. This
journal does not itself recover a sensor, authenticate other processes, or
prove the target filesystem survives a power cycle.
"""
import state_permissions
import json,os,re,stat
from pathlib import Path

MAX_ENTRIES=4096

TRANSITIONS={None:{'f0af-intent','gatt-lookup-intent','prelaunch-input-intent'},'prelaunch-input-intent':{'prelaunch-input-ack'},'prelaunch-input-ack':{'gatt-lookup-intent'},'f0af-intent':{'f0af-ack','f0af-unknown'},'f0af-ack':{'gatt-lookup-intent'},'gatt-lookup-intent':{'gatt-lookup-unknown','borrowed-view-obtained'},'borrowed-view-obtained':{'sensor-enable-intent','notification-config-intent'},'notification-config-intent':{'notification-enabled'},'notification-enabled':{'sensor-enable-intent'},'sensor-enable-intent':{'sensor-enable-ack','sensor-stop-intent'},'sensor-enable-ack':{'sensor-stop-intent','session-recovered'},'sensor-stop-intent':{'sensor-zero-confirmed','session-recovered'},'session-recovered':{'f0af-intent'}}
TRANSITIONS['sensor-enable-ack'].add('sensor-resume-intent')
TRANSITIONS['sensor-resume-intent']={'sensor-resume-intent','sensor-resume-ack','sensor-stop-intent','session-recovered'}
TRANSITIONS['sensor-resume-ack']={'sensor-resume-intent','sensor-stop-intent','session-recovered'}

class BorrowedRuntimeJournal:
 def __init__(self,directory,run,*,state_uid=5999,group=5000):
  if type(run) is not str or not re.fullmatch('[0-9a-f]{32}',run):raise ValueError('invalid run')
  self.run=run;self.fd=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);self.sequence=0;self.stage=None;self.generation=None
  try:
   s=os.fstat(self.fd)
   if not stat.S_ISDIR(s.st_mode) or s.st_uid!=state_uid or s.st_gid!=group or stat.S_IMODE(s.st_mode) not in state_permissions.directory_modes():raise RuntimeError('unsafe journal directory')
   self.identity=(s.st_dev,s.st_ino,s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode));self.owner=os.getuid();self.group=group
   if any(n.startswith('borrowed-') for n in os.listdir(self.fd)):raise RuntimeError('journal already exists or prior run requires recovery')
  except BaseException:os.close(self.fd);self.fd=None;raise
 def _check(self):
  if self.fd is None:raise RuntimeError('journal closed')
  s=os.fstat(self.fd)
  if (s.st_dev,s.st_ino,s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))!=self.identity:raise RuntimeError('journal directory changed')
 def __call__(self,event):
  self._check()
  if type(event) is not dict or type(event.get('stage')) is not str or event['stage'] not in TRANSITIONS.get(self.stage,set()):raise RuntimeError('invalid journal transition')
  stage=event['stage'];expected={'stage'}
  if stage in ('f0af-intent','f0af-ack','f0af-unknown','gatt-lookup-intent','gatt-lookup-unknown','prelaunch-input-intent','prelaunch-input-ack','session-recovered'):expected|={'generation'}
  if stage=='borrowed-view-obtained':expected|={'generation','clientIdSha256','ownership'}
  if set(event)!=expected:raise ValueError('invalid journal event')
  if 'generation' in event and (type(event['generation']) is not int or event['generation']<=0):raise ValueError('invalid generation')
  if 'generation' in event and self.generation is not None:
   if (stage=='session-recovered' and event['generation']<=self.generation) or (stage!='session-recovered' and event['generation']!=self.generation):raise ValueError('generation changed')
  if stage=='borrowed-view-obtained' and (event['ownership']!='unproven' or type(event['clientIdSha256']) is not str or not re.fullmatch('[0-9a-f]{64}',event['clientIdSha256'])):raise ValueError('invalid borrowed identity')
  if self.sequence>=MAX_ENTRIES:raise RuntimeError('journal entry limit reached')
  seq=self.sequence+1;name='borrowed-'+self.run+'-'+str(seq).zfill(2)+'.json';data=(json.dumps({'run':self.run,'seq':seq,**event},sort_keys=True,separators=(',',':'))+'\n').encode()
  fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=self.fd)
  try:
   os.fchmod(fd,0o640);s=os.fstat(fd)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=self.owner or s.st_gid!=self.group:raise RuntimeError('unsafe journal file')
   with os.fdopen(fd,'wb') as f:fd=None;f.write(data);f.flush();os.fsync(f.fileno())
   os.fsync(self.fd);self._check();self.sequence=seq;self.stage=stage
   if 'generation' in event:self.generation=event['generation']
   return True
  finally:
   if fd is not None:os.close(fd)
 def close(self):
  if self.fd is not None:os.close(self.fd);self.fd=None

def inspect_journal(directory,run,*,owner_uid,state_uid=5999,group=5000,historical=False):
 """Read evidence only. A recorded zero is historical, not live proof."""
 if type(run) is not str or not re.fullmatch('[0-9a-f]{32}',run) or type(owner_uid) is not int or owner_uid<0:raise ValueError('invalid identity')
 d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if ds.st_uid!=state_uid or ds.st_gid!=group or stat.S_IMODE(ds.st_mode) not in state_permissions.directory_modes():raise RuntimeError('unsafe journal directory')
  prefix='borrowed-'+run+'-';names=[n for n in os.listdir(d) if n.startswith(prefix)];stages=[];generation=None
  if any(not re.fullmatch(re.escape(prefix)+r'[0-9]{2,4}\.json',n) for n in names):raise RuntimeError('journal filename invalid')
  names.sort(key=lambda n:int(n[len(prefix):-5]))
  if len(names)>MAX_ENTRIES:raise RuntimeError('too many journal entries')
  for seq,name in enumerate(names,1):
   if name!=prefix+str(seq).zfill(2)+'.json':raise RuntimeError('journal sequence invalid')
   fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
   try:
    s=os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=owner_uid or s.st_gid!=group or stat.S_IMODE(s.st_mode) not in (state_permissions.retained_modes(0o640) if historical is True else (0o640,)) or s.st_size>4096:raise RuntimeError('journal file invalid')
    raw=os.read(fd,4097)
    if len(raw)!=s.st_size:raise RuntimeError('incomplete journal read')
   finally:os.close(fd)
   def unique(pairs):
    out={}
    for k,v in pairs:
     if k in out:raise ValueError('duplicate journal key')
     out[k]=v
    return out
   record=json.loads(raw,object_pairs_hook=unique)
   if type(record) is not dict or record.get('run')!=run or type(record.get('seq')) is not int or record['seq']!=seq:raise RuntimeError('journal identity invalid')
   stage=record.get('stage');previous=stages[-1] if stages else None
   if stage not in TRANSITIONS.get(previous,set()):raise RuntimeError('journal transition invalid')
   expected={'run','seq','stage'}
   if stage in ('f0af-intent','f0af-ack','f0af-unknown','gatt-lookup-intent','gatt-lookup-unknown','prelaunch-input-intent','prelaunch-input-ack','session-recovered'):expected|={'generation'}
   if stage=='borrowed-view-obtained':expected|={'generation','clientIdSha256','ownership'}
   if set(record)!=expected:raise RuntimeError('journal shape invalid')
   if 'generation' in record:
    g=record['generation']
    if type(g) is not int or g<=0 or (generation is not None and (g<=generation if stage=='session-recovered' else g!=generation)):raise RuntimeError('journal generation invalid')
    generation=g
   if stage=='borrowed-view-obtained' and (record.get('ownership')!='unproven' or type(record.get('clientIdSha256')) is not str or not re.fullmatch('[0-9a-f]{64}',record['clientIdSha256'])):raise RuntimeError('journal client invalid')
   stages.append(stage)
  if not stages:return {'status':'empty','stages':[]}
  if stages[-1] in ('f0af-intent','f0af-unknown'):status='input-start-unknown'
  elif stages[-1] in ('f0af-ack','prelaunch-input-ack'):status='input-start-recorded-sensor-not-attempted'
  elif stages[-1]=='session-recovered':status='zero-recorded-live-recheck-required'
  elif 'sensor-enable-intent' not in stages[(len(stages)-1-stages[::-1].index('session-recovered') if 'session-recovered' in stages else 0):]:status='no-sensor-enable-recorded'
  elif stages[-1]=='sensor-zero-confirmed':status='zero-recorded-live-recheck-required'
  else:status='sensor-state-unknown'
  return {'status':status,'stages':stages,'generation':generation}
 finally:os.close(d)
