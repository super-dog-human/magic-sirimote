"""Read only an exact receiver receipt; output remains a self-report.

Independent app-package/process and lifecycle verification is still required
before treating a receipt as proof or permitting another launch.
"""
import json,os,re,stat
from pathlib import Path
from receiver_result_receipt import APP
from receive_diagnostics import valid as valid_receive_diagnostics, valid_cleanup

def read_receipt(directory,run,*,state_uid=5999,group=5000,historical=False):
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('invalid run')
 d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or ds.st_uid!=state_uid or ds.st_gid!=group or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe receipt directory')
  name='receiver-result-'+run+'.json';before=os.stat(name,dir_fd=d,follow_symlinks=False)
  if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_gid!=group or stat.S_IMODE(before.st_mode) not in ((0o640,0o775) if historical is True else (0o640,)) or before.st_size>4096:raise RuntimeError('unsafe receipt')
  f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
  try:
   s=os.fstat(f);raw=os.read(f,4097)
   if (before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_size)!=(s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_size) or len(raw)!=s.st_size:raise RuntimeError('receipt changed')
  finally:os.close(f)
  def unique(pairs):
   out={}
   for k,v in pairs:
    if k in out:raise ValueError('duplicate key')
    out[k]=v
   return out
  obj=json.loads(raw,object_pairs_hook=unique)
  base={'schema','appId','run','status','diagnostic','frameCounts','readStats','phase','previousPhase','failureType','sensorStopVerified','journalArchived','featureExclusivity','counts','process','rawReportsPersisted'}
  if type(obj) is not dict or not base<=set(obj)<=base|{'receiveDiagnostics','cleanupDiagnostics'} or obj['schema']!=1 or type(obj['schema']) is not int or obj['appId']!=APP or obj['run']!=run or obj['status'] not in ('complete','attention','not-ready','stopped-before-receiver') or obj['featureExclusivity'] not in ('cooperative-only-unproven','external-guard-supplied-unverified') or any(type(obj[k]) is not bool for k in ('sensorStopVerified','journalArchived','rawReportsPersisted')) or obj['rawReportsPersisted'] is not False:raise RuntimeError('receipt invalid')
  if 'cleanupDiagnostics' in obj and not valid_cleanup(obj['cleanupDiagnostics']):raise RuntimeError('cleanup diagnostics invalid')
  if 'receiveDiagnostics' in obj and not valid_receive_diagnostics(obj['receiveDiagnostics']):raise RuntimeError('receive diagnostics invalid')
  if obj['diagnostic'] not in (None,'guard-rejected','native-identity-rejected','luna-timeout','luna-nonzero','luna-invalid-json','borrowed-view-invalid','control-changed','receive-unconfirmed','output-release-unverified','receive-control-not-ready','other-ValueError','other-RuntimeError','other-LunaCallError','other-TimeoutError','other-OSError','other-error') and not (type(obj['diagnostic']) is str and re.fullmatch(r'(?:output-open-(?:close|timeout|permission|unavailable|io|inventory|changed|key-held|mouse-held|guard|other)|target-(?:inventory-incomplete|inventory-invalid|not-unique|not-present|ambiguous|node-invalid|node-changed|identity-mismatch)|setup-(?:input-start|after-input-start|open-target|open-outputs|open-system-keys|connection-recheck|receiver-setup|session)|gatt-rejected-(?:[0-9]{1,4}|unknown)|notification-(?:control-unavailable|intent-unrecorded|enable-unconfirmed|setting-unsupported|proof-unrecorded)|preborrow-(?:lease|feature|snapshot|age|hid|gatt|exception))',obj['diagnostic'])):raise RuntimeError('diagnostic invalid')
  if obj['phase'] not in (None,'prepare','start','receive','stop') or obj['previousPhase'] not in (None,'start','receive') or obj['failureType'] not in (None,'RuntimeError','ValueError','TimeoutError','OSError','LunaCallError'):raise RuntimeError('phase diagnostic invalid')
  frames=obj['frameCounts'];framekeys={'keyFrameWrites','clickFrameWrites','motionFrameWrites'}
  if frames is not None and (type(frames) is not dict or set(frames)!=framekeys or any(type(frames[k]) is not int or not 0<=frames[k]<=100000 for k in framekeys)):raise RuntimeError('frame counters invalid')
  reads=obj['readStats'];readkeys={'readCalls','bytesReceived','nonemptyReads','emptyReads','wouldBlockReads','interruptedReads','elapsedMs'}
  if reads is not None and (type(reads) is not dict or set(reads)!=readkeys|{'aborted'} or type(reads['aborted']) is not bool or any(type(reads[k]) is not int or not 0<=reads[k]<=100000000 for k in readkeys)):raise RuntimeError('read counters invalid')
  counts=obj['counts'];keys={'bytesReceived','keyFrameWrites','clickFrameWrites','motionFrameWrites'}
  if obj['status']=='complete':
   if type(counts) is not dict or set(counts)!=keys or any(type(counts[k]) is not int or counts[k]<0 for k in keys):raise RuntimeError('input counters invalid')
   if counts['bytesReceived']==0 and (type(reads) is not dict or reads['aborted'] is not True or reads['bytesReceived']!=0 or reads['nonemptyReads']!=0 or type(frames) is not dict or any(counts[k]!=0 or frames[k]!=0 for k in framekeys)):raise RuntimeError('empty input counters inconsistent')
  elif counts is not None:raise RuntimeError('unexpected input counters')
  p=obj['process']
  if type(p) is not dict or set(p)!={'pid','startTicks','status'} or type(p['pid']) is not int or p['pid']<=0 or type(p['startTicks']) is not int or p['startTicks']<=0 or type(p['status']) is not dict or set(p['status'])!={'Uid','Gid','Groups','CapEff'} or any(type(v) is not str for v in p['status'].values()):raise RuntimeError('process record invalid')
  u=p['status']['Uid'].split();g=p['status']['Gid'].split()
  if len(u)!=4 or u!=[str(s.st_uid)]*4 or s.st_uid==0 or len(g)!=4 or g!=['5000']*4 or p['status']['CapEff']!='0000000000000000':raise RuntimeError('process privilege mismatch')
  if obj['status']=='complete' and (obj['sensorStopVerified'] is not True or obj['journalArchived'] is not True):raise RuntimeError('incomplete receipt')
  after=os.stat(name,dir_fd=d,follow_symlinks=False)
  if (after.st_dev,after.st_ino,after.st_uid,after.st_gid,after.st_size,after.st_mtime_ns,after.st_ctime_ns)!=(before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_size,before.st_mtime_ns,before.st_ctime_ns):raise RuntimeError('receipt changed after read')
  return obj
 finally:os.close(d)

def read_start(directory,run,*,state_uid=5999,group=5000,historical=False):
 """Read a startup self-report; an independent live process check is needed."""
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('invalid run')
 d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or ds.st_uid!=state_uid or ds.st_gid!=group or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe receipt directory')
  name='receiver-start-'+run+'.json';before=os.stat(name,dir_fd=d,follow_symlinks=False)
  if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_gid!=group or stat.S_IMODE(before.st_mode) not in ((0o640,0o775) if historical is True else (0o640,)) or before.st_size>4096:raise RuntimeError('unsafe receipt')
  f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
  try:
   s=os.fstat(f);raw=os.read(f,4097)
   if (before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_size)!=(s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_size) or len(raw)!=s.st_size:raise RuntimeError('receipt changed')
  finally:os.close(f)
  def unique(pairs):
   out={}
   for k,v in pairs:
    if k in out:raise ValueError('duplicate key')
    out[k]=v
   return out
  obj=json.loads(raw,object_pairs_hook=unique)
  if type(obj) is not dict or set(obj)!={'schema','appId','run','stage','process','rawReportsPersisted'} or type(obj['schema']) is not int or obj['schema']!=1 or obj['appId']!=APP or obj['run']!=run or obj['stage']!='starting' or obj['rawReportsPersisted'] is not False:raise RuntimeError('start receipt invalid')
  p=obj['process']
  if type(p) is not dict or set(p)!={'pid','startTicks','status'} or type(p['pid']) is not int or p['pid']<=0 or type(p['startTicks']) is not int or p['startTicks']<=0 or type(p['status']) is not dict or set(p['status'])!={'Uid','Gid','Groups','CapEff'} or any(type(v) is not str for v in p['status'].values()):raise RuntimeError('process record invalid')
  u=p['status']['Uid'].split();g=p['status']['Gid'].split()
  if len(u)!=4 or u!=[str(s.st_uid)]*4 or s.st_uid==0 or len(g)!=4 or g!=['5000']*4 or p['status']['CapEff']!='0000000000000000':raise RuntimeError('process privilege mismatch')
  after=os.stat(name,dir_fd=d,follow_symlinks=False)
  if (after.st_dev,after.st_ino,after.st_uid,after.st_gid,after.st_size,after.st_mtime_ns,after.st_ctime_ns)!=(before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_size,before.st_mtime_ns,before.st_ctime_ns):raise RuntimeError('receipt changed after read')
  return obj
 finally:os.close(d)
