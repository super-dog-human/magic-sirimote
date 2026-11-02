"""Write a bounded result for later independent receiver inspection.

No raw HID reports are written. A receipt is a self-report, not proof of
process identity, process exit, storage persistence, or sensor state today.
"""
import json,os,re,stat
from pathlib import Path
from receive_diagnostics import valid as valid_receive_diagnostics
APP='org.codex.siriremote.hidgattrouterb20261029u'

def _process_identity():
 from hid_input import ordinary
 from local_attestation import _start_ticks
 return {'pid':os.getpid(),'startTicks':_start_ticks(Path('/proc/self/stat')),'status':ordinary()}

def write_receipt(directory,run,result,*,state_uid=5999,group=5000,process_info=None):
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run) or type(result) is not dict or result.get('run')!=run or result.get('status') not in ('complete','attention','not-ready','stopped-before-receiver'):
  raise ValueError('invalid result')
 status=result['status'];sensor=result.get('sensorStopVerified') is True;archived=result.get('journalArchived') is True
 if status=='complete' and (not sensor or not archived):raise ValueError('completed result lacks stop evidence')
 process=(process_info or _process_identity)()
 if type(process) is not dict or set(process)!={'pid','startTicks','status'} or type(process['pid']) is not int or process['pid']!=os.getpid() or type(process['startTicks']) is not int or process['startTicks']<=0 or type(process['status']) is not dict or set(process['status'])!={'Uid','Gid','Groups','CapEff'} or any(type(v) is not str for v in process['status'].values()):raise RuntimeError('process identity invalid')
 feature=result.get('featureExclusivity')
 if feature not in ('cooperative-only-unproven','external-guard-supplied-unverified'):raise ValueError('feature assumption missing')
 counts=None
 if status=='complete':
  o=result.get('outputCounts');r=result.get('receiveSummary')
  if type(o) is not dict or type(r) is not dict or any(type(o.get(k)) is not int or o[k]<0 for k in ('keyFrameWrites','clickFrameWrites','motionFrameWrites')) or type(r.get('bytesReceived')) is not int or r['bytesReceived']<0:raise ValueError('input counters missing')
  if r['bytesReceived']==0:
   # A requested, clean shutdown may precede the first HID frame. Persist
   # that zero count; completing shutdown is not successful input acceptance.
   reads=result.get('readStats')
   if r.get('endReason')!='stop-requested' or type(reads) is not dict or reads.get('aborted') is not True or reads.get('bytesReceived')!=0 or reads.get('nonemptyReads')!=0 or any(o[k]!=0 for k in ('keyFrameWrites','clickFrameWrites','motionFrameWrites')):raise ValueError('empty result lacks clean stop')
  counts={'bytesReceived':r['bytesReceived'],**{k:o[k] for k in ('keyFrameWrites','clickFrameWrites','motionFrameWrites')}}
 allowed={'guard-rejected','native-identity-rejected','luna-timeout','luna-nonzero','luna-invalid-json','borrowed-view-invalid','control-changed','receive-unconfirmed','output-release-unverified','receive-control-not-ready','other-ValueError','other-RuntimeError','other-LunaCallError','other-TimeoutError','other-OSError','other-error'}
 diagnostic=result.get('diagnostic')
 if diagnostic not in allowed and not (type(diagnostic) is str and re.fullmatch(r'(?:output-open-(?:close|timeout|permission|unavailable|io|inventory|changed|key-held|mouse-held|guard|other)|target-(?:inventory-incomplete|inventory-invalid|not-unique|not-present|ambiguous|node-invalid|node-changed|identity-mismatch)|setup-(?:input-start|after-input-start|open-target|open-outputs|open-system-keys|connection-recheck|receiver-setup|session)|gatt-rejected-(?:[0-9]{1,4}|unknown)|notification-(?:control-unavailable|intent-unrecorded|enable-unconfirmed|setting-unsupported|proof-unrecorded)|preborrow-(?:lease|feature|snapshot|age|hid|gatt|exception))',diagnostic)):diagnostic=None
 frames=result.get('outputCounts')
 frame_keys=('keyFrameWrites','clickFrameWrites','motionFrameWrites')
 if type(frames) is dict and all(type(frames.get(k)) is int and 0<=frames[k]<=100000 for k in frame_keys):frames={k:frames[k] for k in frame_keys}
 else:frames=None
 read=result.get('readStats');readkeys=('readCalls','bytesReceived','nonemptyReads','emptyReads','wouldBlockReads','interruptedReads','elapsedMs')
 if type(read) is dict and all(type(read.get(k)) is int and 0<=read[k]<=100000000 for k in readkeys) and type(read.get('aborted')) is bool:read={**{k:read[k] for k in readkeys},'aborted':read['aborted']}
 else:read=None
 if counts is not None and counts['bytesReceived']==0 and read is None:raise ValueError('empty result lacks read counters')
 phase=result.get('phase') if result.get('phase') in ('prepare','start','receive','stop') else None
 previous=result.get('previousPhase') if result.get('previousPhase') in ('start','receive') else None
 failure=result.get('errorType') if result.get('errorType') in ('RuntimeError','ValueError','TimeoutError','OSError','LunaCallError') else None
 data={'schema':1,'appId':APP,'run':run,'status':status,'diagnostic':diagnostic,'frameCounts':frames,'readStats':read,'phase':phase,'previousPhase':previous,'failureType':failure,'sensorStopVerified':sensor,'journalArchived':archived,'featureExclusivity':feature,'counts':counts,'process':process,'rawReportsPersisted':False}
 details=(result.get('readStats') or {}).get('receiveDiagnostics')
 if valid_receive_diagnostics(details):data['receiveDiagnostics']=details
 fd=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  d=os.fstat(fd)
  if not stat.S_ISDIR(d.st_mode) or d.st_uid!=state_uid or d.st_gid!=group or stat.S_IMODE(d.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe receipt directory')
  name='receiver-result-'+run+'.json';f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=fd)
  try:
   os.fchmod(f,0o640);s=os.fstat(f)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid() or s.st_gid!=group:raise RuntimeError('unsafe receipt file')
   with os.fdopen(f,'wb') as stream:
    f=None;stream.write((json.dumps(data,sort_keys=True,separators=(',',':'))+'\n').encode());stream.flush();os.fsync(stream.fileno())
   os.fsync(fd)
  finally:
   if f is not None:os.close(f)
 finally:os.close(fd)
 return data

def write_start(directory,run,*,state_uid=5999,group=5000,process_info=None):
 """Record receiver startup for a separate observer to inspect while live."""
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('invalid run')
 process=(process_info or _process_identity)()
 if type(process) is not dict or set(process)!={'pid','startTicks','status'} or type(process['pid']) is not int or process['pid']!=os.getpid() or type(process['startTicks']) is not int or process['startTicks']<=0 or type(process['status']) is not dict or set(process['status'])!={'Uid','Gid','Groups','CapEff'} or any(type(v) is not str for v in process['status'].values()):raise RuntimeError('process identity invalid')
 data={'schema':1,'appId':APP,'run':run,'stage':'starting','process':process,'rawReportsPersisted':False}
 d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or ds.st_uid!=state_uid or ds.st_gid!=group or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe receipt directory')
  f=os.open('receiver-start-'+run+'.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=d)
  try:
   os.fchmod(f,0o640);s=os.fstat(f)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid() or s.st_gid!=group:raise RuntimeError('unsafe receipt file')
   with os.fdopen(f,'wb') as stream:
    f=None;stream.write((json.dumps(data,sort_keys=True,separators=(',',':'))+'\n').encode());stream.flush();os.fsync(stream.fileno())
   os.fsync(d)
  finally:
   if f is not None:os.close(f)
 finally:os.close(d)
 return data
