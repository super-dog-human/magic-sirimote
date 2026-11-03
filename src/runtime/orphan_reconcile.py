"""Reconcile completed sessions and pre-boot launches that never started.

No launch, sensor write, or successful input result is invented here. An active
uncertain sensor journal still requires B's existing real recovery path.
Call only while holding the exclusive supervisor lease.
"""
import runtime_bundle as bundle
import json, os, re, stat
from pathlib import Path
import local_attestation as att
import receiver_package_attestation as package
from recovery_reader import read_recovery_receipt, read_recovery_start
from receiver_result_reader import read_receipt, read_start
from borrowed_runtime_journal import inspect_journal

def _unique(pairs):
 out={}
 for key,value in pairs:
  if key in out:raise ValueError('duplicate state key')
  out[key]=value
 return out

def _identity(s):
 return (s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)

def _read(d,name,owner,group,mode,*,historical=False):
 f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
 try:
  before=os.fstat(f)
  if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=owner or before.st_gid!=group or stat.S_IMODE(before.st_mode) not in ((mode,0o775) if historical is True else (mode,)) or before.st_size>4096:raise RuntimeError('unsafe recovery evidence')
  raw=os.read(f,4097)
  if len(raw)!=before.st_size or _identity(before)!=_identity(os.fstat(f)):raise RuntimeError('recovery evidence changed')
  obj=json.loads(raw,object_pairs_hook=_unique)
  if type(obj) is not dict:raise RuntimeError('invalid recovery evidence')
  return obj,before
 finally:os.close(f)

def _ended(process,app,proc='/proc',ignore_current=False):
 # Empty app process census prevents a different live instance being ignored.
 if any(pid!=os.getpid() or not ignore_current for pid in att.candidate_pids(app,proc)):return False
 if type(process) is not dict or type(process.get('pid')) is not int or process['pid']<=0 or type(process.get('startTicks')) is not int or process['startTicks']<=0:raise RuntimeError('invalid old process')
 try:return att._start_ticks(Path(proc)/str(process['pid'])/'stat')!=process['startTicks']
 except FileNotFoundError:return True

def archive_before_input(*,c,b,intent,intent_stat,controller_app,receiver_app,receiver_package,pin,lease,owner,group):
 """Archive a constructor failure before the durable input-start intent.

 An empty journal plus absent handoff metadata proves begin() was not reached.
 The original controller and every receiver must have ended, and the caller
 holds the supervisor lease. Preserve every record; never invent sensor stop.
 """
 run=intent['run']
 if not re.fullmatch('[a-f0-9]{32}',run):raise RuntimeError('invalid prior run')
 journal='input-'+run+'.jsonl'
 forbidden={'borrowed-active','recovery-request.json','recovery-controller-start.json'}
 def absent():
  return (not any(n in forbidden or n.startswith(('receiver-start-','receiver-result-','receiver-ready-','receiver-progress-','receiver-recovery-','borrowed-','recovery-')) for n in os.listdir(b))
   and 'input-'+run+'.json' not in os.listdir(c))
 if not absent():return None
 try:j=os.stat(journal,dir_fd=c,follow_symlinks=False)
 except FileNotFoundError:return None
 if not stat.S_ISREG(j.st_mode) or j.st_nlink!=1 or (j.st_uid,j.st_gid,j.st_size,stat.S_IMODE(j.st_mode))!=(owner,group,0,0o640):return None
 rows=[];values={}
 for name in ('request.json','controller-start.json'):
  dest=name[:-5]+'-before-input-'+run+'.json'
  try:value,info=_read(b,name,owner,group,0o660);source=name
  except FileNotFoundError:value,info=_read(b,dest,owner,group,0o660);source=dest
  if value.get('run')!=run or source==name and dest in os.listdir(b):raise RuntimeError('unstarted handoff differs')
  rows.append((source,dest,info));values[name]=value
 q=values['request.json'];record=values['controller-start.json'];process=record.get('process')
 if q.get('schema')!=1 or q.get('appId')!=bundle.app_id(Path(receiver_app).name) or record.get('schema')!=1 or record.get('appId')!=bundle.app_id(Path(controller_app).name):raise RuntimeError('unstarted app identity differs')
 if type(process) is not dict or process.get('status',{}).get('Uid','').split()!=[str(owner)]*4:raise RuntimeError('unstarted process identity differs')
 def proof():
  return (lease.held() is True and (os.fstat(lease.dirfd).st_dev,os.fstat(lease.dirfd).st_ino)==(os.fstat(c).st_dev,os.fstat(c).st_ino)
   and absent() and _ended(process,controller_app,ignore_current=True) and att.candidate_pids(receiver_app)==[]
   and package.package_matches(receiver_app,receiver_package,pin) is True
   and _identity(os.stat(journal,dir_fd=c,follow_symlinks=False))==_identity(j)
   and _identity(os.stat('receiver-launch-intent.json',dir_fd=c,follow_symlinks=False))==_identity(intent_stat))
 if not proof():raise RuntimeError('unstarted proof unavailable')
 dest='receiver-launch-before-input-'+run+'.json'
 if dest in os.listdir(c):raise RuntimeError('unstarted archive already exists')
 for source,target,info in rows:
  if not proof() or _identity(os.stat(source,dir_fd=b,follow_symlinks=False))!=_identity(info):raise RuntimeError('unstarted evidence changed')
  if source!=target:os.rename(source,target,src_dir_fd=b,dst_dir_fd=b);os.fsync(b)
 if not proof():raise RuntimeError('unstarted proof changed')
 os.rename('receiver-launch-intent.json',dest,src_dir_fd=c,dst_dir_fd=c);os.fsync(c)
 return {'status':'reconciled','run':run,'priorOutcome':'input-never-started','launchIntentArchived':True}

def _archive_unstarted_after_boot(*,c,b,intent,intent_stat,controller_app,receiver_app,receiver_package,pin,lease,owner,group,boot_time=None):
 """Retire an expired pre-boot launch that never reached B's durable start.

 B fsyncs its start receipt before creating the sensor journal or issuing any
 sensor command. Absence of both is usable only with the pinned B package,
 no live B process, and a request that expired before this boot. This is an
 abandoned handoff, never a successful session or a sensor-stop receipt.
 """
 run=intent['run']
 def boot():
  return int(next(x.split()[1] for x in Path('/proc/stat').read_text().splitlines() if x.startswith('btime ')))
 started=boot() if boot_time is None else boot_time
 if type(started) is not int or started<=0:raise RuntimeError('boot time unavailable')
 def absent():
  names=os.listdir(b)
  forbidden={'borrowed-active','recovery-request.json','recovery-controller-start.json',
   'receiver-start-'+run+'.json','receiver-result-'+run+'.json',
   'receiver-ready-'+run+'.json','receiver-progress-'+run+'.json'}
  return not any(n in forbidden or n.startswith(('receiver-recovery-start-'+run,'receiver-recovery-result-'+run,'recovery-'+run+'-','borrowed-complete-'+run,'borrowed-recovered-'+run)) for n in names)
 if not absent():return None
 rows=[];values={}
 for name in ('request.json','controller-start.json'):
  dest=name[:-5]+'-unstarted-'+run+'.json'
  try:value,info=_read(b,name,owner,group,0o660,historical=True);source=name
  except FileNotFoundError:value,info=_read(b,dest,owner,group,0o660,historical=True);source=dest
  if source==name and dest in os.listdir(b):raise RuntimeError('duplicate unstarted handoff')
  if info.st_mtime>=started or value.get('run')!=run:raise RuntimeError('handoff not from prior boot')
  values[name]=value;rows.append((source,dest,info))
 q=values['request.json'];record=values['controller-start.json'];process=record.get('process')
 if (set(q)!={'schema','appId','run','expiresEpochMs'} or type(q['schema']) is not int or q['schema']!=1 or q['appId']!=bundle.app_id(Path(receiver_app).name) or
     type(q['expiresEpochMs']) is not int or not 0<q['expiresEpochMs']<started*1000 or intent_stat.st_mtime>=started):
  raise RuntimeError('unstarted request not expired before boot')
 if (set(record)!={'schema','appId','run','process'} or type(record['schema']) is not int or record['schema']!=1 or record['appId']!=bundle.app_id(Path(controller_app).name) or
     type(process) is not dict or set(process)!={'pid','startTicks','status'} or type(process.get('status')) is not dict or
     process['status'].get('Uid','').split()!=[str(owner)]*4 or process['status'].get('CapEff')!='0000000000000000'):
  raise RuntimeError('unstarted controller identity invalid')
 def proof():
  if lease.held() is not True or not absent():return False
  ls=os.fstat(lease.dirfd);cs=os.fstat(c)
  return ((ls.st_dev,ls.st_ino)==(cs.st_dev,cs.st_ino) and
   (boot_time is not None or boot()==started) and
   _ended(process,controller_app,ignore_current=True) and att.candidate_pids(receiver_app)==[] and
   package.package_matches(receiver_app,receiver_package,pin) is True and
   _identity(os.stat('receiver-launch-intent.json',dir_fd=c,follow_symlinks=False))==_identity(intent_stat))
 if not proof():raise RuntimeError('unstarted handoff proof unavailable')
 dest='receiver-launch-unstarted-'+run+'.json'
 if dest in os.listdir(c):raise RuntimeError('duplicate unstarted intent')
 for source,target,info in rows:
  if not proof() or _identity(os.stat(source,dir_fd=b,follow_symlinks=False))!=_identity(info):raise RuntimeError('unstarted handoff changed')
  if source!=target:os.rename(source,target,src_dir_fd=b,dst_dir_fd=b);os.fsync(b)
 if not proof():raise RuntimeError('unstarted handoff proof changed')
 os.rename('receiver-launch-intent.json',dest,src_dir_fd=c,dst_dir_fd=c);os.fsync(c)
 return {'status':'reconciled','run':run,'priorOutcome':'not-started-before-reboot','launchIntentArchived':True}

def archive_not_ready(*,c,b,intent,intent_stat,receipt,receiver_state,controller_app,receiver_app,receiver_package,pin,lease,owner,group,state_uid=5999):
 """Preserve a finished receiver that exited before any sensor preparation.

 This is not a successful input session or a sensor-stop proof. A pinned
 receiver writes not-ready only before entering sensor preparation and discards
 its empty journal. Any ready/progress/journal/recovery evidence excludes this.
 """
 run=intent['run']
 if receipt.get('status') not in ('not-ready','stopped-before-receiver'):return None
 if any(receipt.get(k) is not None for k in ('phase','previousPhase','counts','frameCounts','readStats')):return None
 start=read_start(receiver_state,run,state_uid=state_uid,group=group,historical=True)
 if start['process']!=receipt['process']:raise RuntimeError('unprepared receiver differs')
 forbidden={'borrowed-active','recovery-request.json','recovery-controller-start.json',
  'receiver-ready-'+run+'.json','receiver-progress-'+run+'.json'}
 def absent():
  return not any(n in forbidden or n.startswith(('borrowed-complete-'+run,'borrowed-recovered-'+run,'receiver-recovery-start-'+run,'receiver-recovery-result-'+run)) for n in os.listdir(b))
 if not absent():return None
 rows=[];values={}
 for name in ('request.json','controller-start.json'):
  dest=name[:-5]+'-not-ready-'+run+'.json'
  try:value,info=_read(b,name,owner,group,0o660,historical=True);source=name
  except FileNotFoundError:value,info=_read(b,dest,owner,group,0o660,historical=True);source=dest
  if value.get('run')!=run or source==name and dest in os.listdir(b):raise RuntimeError('unprepared handoff differs')
  values[name]=value;rows.append((source,dest,info))
 request,record=values['request.json'],values['controller-start.json'];process=record.get('process')
 if (request.get('schema')!=1 or request.get('appId')!=bundle.app_id(Path(receiver_app).name)
     or record.get('schema')!=1 or record.get('appId')!=bundle.app_id(Path(controller_app).name)
     or type(process) is not dict or process.get('status',{}).get('Uid','').split()!=[str(owner)]*4):raise RuntimeError('unprepared identities differ')
 def proof():
  return (lease.held() is True and absent()
   and (os.fstat(lease.dirfd).st_dev,os.fstat(lease.dirfd).st_ino)==(os.fstat(c).st_dev,os.fstat(c).st_ino)
   and _ended(process,controller_app,ignore_current=True) and _ended(receipt['process'],receiver_app)
   and package.package_matches(receiver_app,receiver_package,pin) is True
   and read_start(receiver_state,run,state_uid=state_uid,group=group,historical=True)==start
   and read_receipt(receiver_state,run,state_uid=state_uid,group=group,historical=True)==receipt
   and _identity(os.stat('receiver-launch-intent.json',dir_fd=c,follow_symlinks=False))==_identity(intent_stat))
 dest='receiver-launch-not-ready-'+run+'.json'
 if dest in os.listdir(c) or not proof():raise RuntimeError('unprepared exit proof unavailable')
 for source,target,info in rows:
  if not proof() or _identity(os.stat(source,dir_fd=b,follow_symlinks=False))!=_identity(info):raise RuntimeError('unprepared evidence changed')
  if source!=target:os.rename(source,target,src_dir_fd=b,dst_dir_fd=b);os.fsync(b)
 if not proof():raise RuntimeError('unprepared proof changed')
 os.rename('receiver-launch-intent.json',dest,src_dir_fd=c,dst_dir_fd=c);os.fsync(c)
 return {'status':'reconciled','run':run,'priorOutcome':'receiver-not-ready-before-sensors','launchIntentArchived':True}

def reconcile(*,controller_state,receiver_state,controller_app,receiver_app,receiver_package,pin,lease,state_uid=5999,group=5000):
 if lease.held() is not True:raise RuntimeError('supervisor lease required')
 owner=os.getuid();fds=[]
 try:
  for path in (controller_state,receiver_state):
   d=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);fds.append(d)
   s=os.fstat(d)
   if s.st_uid!=state_uid or s.st_gid!=group or stat.S_IMODE(s.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe reconciliation directory')
  c,b=fds
  try:intent,intent_stat=_read(c,'receiver-launch-intent.json',owner,group,0o640,historical=True)
  except FileNotFoundError:return {'status':'clear'}
  if set(intent)!={'run','stage','generation'} or intent['stage']!='receiver-launch-intent' or type(intent['run']) is not str or not re.fullmatch('[a-f0-9]{32}',intent['run']) or type(intent['generation']) is not int or intent['generation']<1:raise RuntimeError('invalid prior intent')
  run=intent['run']
  # The authenticated receiver reader enforces receiver UID/privilege/file ACLs.
  try:completed=read_receipt(receiver_state,run,state_uid=state_uid,group=group,historical=True)
  except FileNotFoundError:completed=None
  if completed is not None and bundle.active():
   unprepared=archive_not_ready(c=c,b=b,intent=intent,intent_stat=intent_stat,receipt=completed,receiver_state=receiver_state,controller_app=controller_app,receiver_app=receiver_app,receiver_package=receiver_package,pin=pin,lease=lease,owner=owner,group=group,state_uid=state_uid)
   if unprepared is not None:return unprepared
  if completed is None:
   if bundle.active():
    unstarted=archive_before_input(c=c,b=b,intent=intent,intent_stat=intent_stat,controller_app=controller_app,receiver_app=receiver_app,receiver_package=receiver_package,pin=pin,lease=lease,owner=owner,group=group)
    if unstarted is not None:return unstarted
   unstarted=_archive_unstarted_after_boot(c=c,b=b,intent=intent,intent_stat=intent_stat,controller_app=controller_app,receiver_app=receiver_app,receiver_package=receiver_package,pin=pin,lease=lease,owner=owner,group=group)
   if unstarted is not None:return unstarted
  if completed is not None and completed['status']=='complete':
   outcome='complete';receipt=completed
   start=read_start(receiver_state,run,state_uid=state_uid,group=group,historical=True)
  else:
   outcome='recovered'
   receipt=read_recovery_receipt(receiver_state,run,state_uid=state_uid,group=group,historical=True)
   start=read_recovery_start(receiver_state,run,state_uid=state_uid,group=group,historical=True)
  if receipt['status']!=outcome or receipt['sensorStopVerified'] is not True or receipt['journalArchived'] is not True or receipt['process']!=start['process']:raise RuntimeError('real receiver completion unconfirmed')
  try:os.stat('borrowed-active',dir_fd=b,follow_symlinks=False)
  except FileNotFoundError:pass
  else:raise RuntimeError('active sensor journal needs real recovery')
  receiver_uid=int(receipt['process']['status']['Uid'].split()[0])
  j=os.open('borrowed-'+outcome+'-'+run,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=b)
  try:
   names=os.listdir(j)
   if not names or any(not re.fullmatch('borrowed-'+run+r'-[0-9]{2}\.json',name) for name in names):raise RuntimeError('foreign recovered journal evidence')
  finally:os.close(j)
  evidence=inspect_journal(Path(receiver_state)/('borrowed-'+outcome+'-'+run),run,owner_uid=receiver_uid,state_uid=receiver_uid,group=group,historical=True)
  if evidence.get('status') not in ('sensor-state-unknown','zero-recorded-live-recheck-required','no-sensor-enable-recorded','input-start-recorded-sensor-not-attempted'):raise RuntimeError('invalid recovered journal')
  if outcome=='complete' and evidence.get('status')!='zero-recorded-live-recheck-required':raise RuntimeError('completed journal lacks final sensor stop')
  # Resume partial handoff archives idempotently; never overwrite evidence.
  handoffs=[]
  for name in (('request.json','controller-start.json') if outcome=='complete' else ('request.json','controller-start.json','recovery-request.json')):
   dest=name[:-5]+'-'+outcome+'-'+run+'.json'
   try:obj,s=_read(b,name,owner,group,0o660,historical=True);source=name
   except FileNotFoundError:obj,s=_read(b,dest,owner,group,0o660,historical=True);source=dest
   if obj.get('run')!=run:raise RuntimeError('handoff run differs')
   if name=='request.json' and obj.get('appId')!=bundle.app_id(Path(receiver_app).name):raise RuntimeError('request app differs')
   if name=='controller-start.json':
    controller_process=obj.get('process')
    if (set(obj)!={'schema','appId','run','process'} or type(obj['schema']) is not int or obj['schema']!=1 or obj['appId']!=bundle.app_id(Path(controller_app).name) or
        type(controller_process) is not dict or set(controller_process)!={'pid','startTicks','status'} or type(controller_process.get('status')) is not dict or
        controller_process['status'].get('Uid','').split()!=[str(owner)]*4 or controller_process['status'].get('CapEff')!='0000000000000000'):
     raise RuntimeError('invalid prior controller identity')
   if source==name:
    try:os.stat(dest,dir_fd=b,follow_symlinks=False)
    except FileNotFoundError:pass
    else:raise RuntimeError('duplicate handoff archive')
   handoffs.append((source,dest,s))
  if outcome=='complete':
   for name in ('recovery-request.json','recovery-controller-start.json'):
    try:os.stat(name,dir_fd=b,follow_symlinks=False)
    except FileNotFoundError:pass
    else:raise RuntimeError('unfinished recovery conflicts with completion')
  recovery_controller=None
  name='recovery-controller-start.json';dest='recovery-controller-start-recovered-'+run+'.json'
  try:obj,s=_read(b,name,owner,group,0o660,historical=True);source=name
  except FileNotFoundError:
   try:obj,s=_read(b,dest,owner,group,0o660,historical=True);source=dest
   except FileNotFoundError:obj=None
  if obj is not None:
   p=obj.get('process')
   if (set(obj)!={'schema','appId','run','process'} or obj.get('schema')!=1 or
       obj.get('appId')!=bundle.app_id('org.codex.siriremote.autocoord20261029v') or obj.get('run')!=run or
       type(p) is not dict or set(p)!={'pid','startTicks','status'} or type(p.get('pid')) is not int or p['pid']<=0 or
       type(p.get('startTicks')) is not int or p['startTicks']<=0 or type(p.get('status')) is not dict or
       p['status'].get('Uid','').split()!=[str(owner)]*4 or p['status'].get('CapEff')!='0000000000000000'):
    raise RuntimeError('invalid recovery controller record')
   if source==name:
    try:os.stat(dest,dir_fd=b,follow_symlinks=False)
    except FileNotFoundError:pass
    else:raise RuntimeError('duplicate recovery controller archive')
   recovery_controller=p;handoffs.append((source,dest,s))
  def recovery_controller_safe():
   if recovery_controller is None:return True
   if recovery_controller['pid']==os.getpid():
    return (att._start_ticks(Path('/proc/self/stat'))==recovery_controller['startTicks'] and
            att.candidate_pids(controller_app)==[os.getpid()])
   return _ended(recovery_controller,controller_app,ignore_current=True)
  def proof():
   return lease.held() is True and package.package_matches(receiver_app,receiver_package,pin) is True and _ended(controller_process,controller_app,ignore_current=True) and _ended(receipt['process'],receiver_app) and recovery_controller_safe()
  if not proof():raise RuntimeError('prior processes or package unverified')
  for source,dest,s in handoffs:
   if _identity(os.stat(source,dir_fd=b,follow_symlinks=False))!=_identity(s) or not proof():raise RuntimeError('handoff changed')
   if source!=dest:os.rename(source,dest,src_dir_fd=b,dst_dir_fd=b);os.fsync(b)
  dest='receiver-launch-'+outcome+'-'+run+'.json'
  try:os.stat(dest,dir_fd=c,follow_symlinks=False)
  except FileNotFoundError:pass
  else:raise RuntimeError('prior intent archive exists')
  if not proof() or _identity(os.stat('receiver-launch-intent.json',dir_fd=c,follow_symlinks=False))!=_identity(intent_stat):raise RuntimeError('intent changed')
  os.rename('receiver-launch-intent.json',dest,src_dir_fd=c,dst_dir_fd=c);os.fsync(c)
  return {'status':'reconciled','run':run,'priorOutcome':outcome,'launchIntentArchived':True}
 finally:
  for d in fds:os.close(d)
