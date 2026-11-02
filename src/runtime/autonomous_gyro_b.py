#!/usr/bin/python3
"""B: exact read-only HID observation after host gate; never persists raw reports."""
import errno,fcntl,json,os,secrets,stat,struct,time,sys
import subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from combined_receiver import CombinedReceiver
from observed_motion_gate import ObservedMotionGate
from continuity_monitor import ContinuityMonitor
from input_session_policy import InputSessionPolicy
from output_devices import open_verified_outputs
from shared_protocol import open_from_request,publish
APP_A_ID='org.codex.siriremote.hidgattroutera20261029u'
APP_ID='org.codex.siriremote.hidgattrouterb20261029u';APP=Path('/media/developer/apps/usr/palm/applications/'+APP_ID);STATE=APP/'state'
TARGET='02:00:00:00:00:01';NAME='EXAMPLE_REMOTE_SERIAL';MAX=32
PROFILE_CALL_TIMEOUT_SECONDS=4
HOST_CUE_WAIT_SECONDS=90
READ_WINDOW_SECONDS=60
ACTION_WINDOW_SECONDS=READ_WINDOW_SECONDS
READ_BACKOFF_SECONDS=0.01
READ_SUCCESS_YIELD_SECONDS=0.001
INPUT_INVENTORY_TIMEOUT_SECONDS=10
OUTPUT_INVENTORY_TIMEOUT_SECONDS=20
def atomic_at(directory,name,obj):
 directory=Path(directory);p=directory/name;tmp=directory/('.'+name+'.'+secrets.token_hex(8));raw=(json.dumps(obj,sort_keys=True,separators=(',',':'))+'\n').encode()
 d=directory.lstat();assert stat.S_ISDIR(d.st_mode) and not stat.S_ISLNK(d.st_mode) and d.st_uid==5999 and d.st_gid==5000 and stat.S_IMODE(d.st_mode)==0o770
 fd=os.open(str(tmp),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o660)
 try:
  os.fchmod(fd,0o660)
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  os.link(str(tmp),str(p),follow_symlinks=False)
 finally:
  try:tmp.unlink()
  except OSError:pass
def atomic(name,obj):atomic_at(STATE,name,obj)
def ioctl(fd,request,b):fcntl.ioctl(fd,request,b,True);return b
def cstr(b):return bytes(b).split(b'\0',1)[0].decode('utf-8','replace')
def ordinary():
 p={}
 for l in open('/proc/self/status'):
  k,_,v=l.partition(':')
  if k in ('Uid','Gid','Groups','CapEff'):p[k]=v.strip()
 u=p.get('Uid','').split();g=p.get('Gid','').split()
 if len(u)!=4 or len(set(u))!=1 or u[0]=='0' or len(g)!=4 or len(set(g))!=1 or g[0]!='5000' or p.get('CapEff')!='0000000000000000':raise RuntimeError('ordinary-uid-gid-capability-gate-failed')
 return p
def identity(fd):
 info=ioctl(fd,(2<<30)|(8<<16)|(ord('H')<<8)|3,bytearray(8));bus,vid,pid=struct.unpack('=IHH',info)
 name=ioctl(fd,(2<<30)|(256<<16)|(ord('H')<<8)|4,bytearray(256));uniq=ioctl(fd,(2<<30)|(256<<16)|(ord('H')<<8)|8,bytearray(256))
 return {'matches':(bus,vid,pid)==(5,0x004c,0x0266) and cstr(name)==NAME and cstr(uniq).lower()==TARGET,'bus':bus,'vendor':vid,'product':pid,'name':cstr(name),'uniq':cstr(uniq).lower()}
def scan_devices(root='/dev',lstat_fn=None,open_fn=None,fstat_fn=None,identity_fn=None,close_fn=None,clock=time.monotonic,timeout=10):
 lstat_fn=os.lstat if lstat_fn is None else lstat_fn;open_fn=os.open if open_fn is None else open_fn;fstat_fn=os.fstat if fstat_fn is None else fstat_fn;identity_fn=identity if identity_fn is None else identity_fn;close_fn=os.close if close_fn is None else close_fn
 nodes=[];errors={};matches=[];complete=True;deadline=clock()+timeout
 for i in range(MAX):
  if clock()>deadline:complete=False;break
  p=os.path.join(root,'hidraw'+str(i))
  try:st=lstat_fn(p)
  except OSError as e:
   k=errno.errorcode.get(e.errno,'OTHER');errors[k]=errors.get(k,0)+1
   if e.errno!=errno.ENOENT:complete=False
   continue
  if stat.S_ISLNK(st.st_mode) or not stat.S_ISCHR(st.st_mode):
   nodes.append({'index':i,'fileType':'other','mode':oct(stat.S_IMODE(st.st_mode))});complete=False;continue
  entry={'index':i,'mode':oct(stat.S_IMODE(st.st_mode)),'uid':st.st_uid,'gid':st.st_gid,'rdevMajor':os.major(st.st_rdev),'rdevMinor':os.minor(st.st_rdev),'identityChecked':False,'openedReadOnly':False,'fdClosed':False};fd=None
  try:
   fd=open_fn(p,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC);entry['openedReadOnly']=True;opened=fstat_fn(fd);after=lstat_fn(p)
   if (st.st_ino,st.st_dev,st.st_rdev)!=(opened.st_ino,opened.st_dev,opened.st_rdev) or (opened.st_ino,opened.st_dev,opened.st_rdev)!=(after.st_ino,after.st_dev,after.st_rdev):entry['inspectionError']='node-identity-raced';complete=False
   else:
    x=identity_fn(fd);entry['identityChecked']=True;entry['targetIdentity']=x
    if x.get('matches') is True:matches.append(i)
    if clock()>deadline:entry['inspectionError']='inventory-deadline';complete=False
  except OSError as e:
   k=errno.errorcode.get(e.errno,'OTHER');entry['inspectionErrno']=k;complete=False
  except Exception as e:
   entry['inspectionError']=type(e).__name__;complete=False
  finally:
   if fd is not None:
    try:close_fn(fd);entry['fdClosed']=True
    except OSError as e:entry['closeErrno']=errno.errorcode.get(e.errno,'OTHER');complete=False
  if entry['openedReadOnly'] and (not entry['identityChecked'] or not entry['fdClosed']):complete=False
  nodes.append(entry)
 return {'nodes':nodes,'errnoBuckets':errors,'targetCandidateIndexes':matches,'inventoryComplete':complete,'range':[0,MAX-1],'allOpenedFdsClosed':all(not n.get('openedReadOnly') or n.get('fdClosed') for n in nodes)}
def profile_snapshot():
 out={};bus='luna://com.webos.service.bluetooth2/'
 for name in ('hid','gatt'):
  try:
   p=subprocess.run(['/usr/bin/luna-send-pub','-n','1','-f',bus+name+'/getStatus',json.dumps({'address':TARGET},separators=(',',':'))],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=PROFILE_CALL_TIMEOUT_SECONDS,check=False)
   out[name]={'returncode':p.returncode,'reply':json.loads(p.stdout) if p.returncode==0 and p.stdout else None}
  except BaseException as e:out[name]={'returncode':None,'reply':None,'error':type(e).__name__+':'+str(e)[:100]}
 return out
def profile_comparison_valid(before,after):
 def normalized(snapshot):
  if not isinstance(snapshot,dict):return None
  out={}
  for name in ('hid','gatt'):
   item=snapshot.get(name);r=item.get('reply') if isinstance(item,dict) and item.get('returncode')==0 else None
   if not isinstance(r,dict) or r.get('returnValue') is not True or str(r.get('address','')).lower()!=TARGET or str(r.get('adapterAddress','')).lower()!='02:00:00:00:00:02' or any(type(r.get(k)) is not bool for k in ('connected','connecting','connectRequest')):return None
   if r['connected'] is not True or r['connecting'] is not False or r['connectRequest'] is not False:return None
   out[name]={k:r[k] for k in ('returnValue','address','adapterAddress','connected','connecting','connectRequest')}
  return out
 b=normalized(before);a=normalized(after);return b is not None and a is not None and b==a
def profile_connected(snapshot):
 if not isinstance(snapshot,dict):return False
 for name in ('hid','gatt'):
  item=snapshot.get(name);r=item.get('reply') if isinstance(item,dict) and item.get('returncode')==0 else None
  if not isinstance(r,dict) or r.get('returnValue') is not True or str(r.get('address','')).lower()!=TARGET or str(r.get('adapterAddress','')).lower()!='02:00:00:00:00:02' or r.get('connected') is not True or r.get('connecting') is not False or r.get('connectRequest') is not False:return False
 return True
def live_a(app_path):
 found=[]
 for p in Path('/proc').iterdir():
  if p.name.isdecimal():
   try:args=(p/'cmdline').read_bytes().split(b'\0')
   except OSError:continue
   if str(Path(app_path)/'native_probe.py').encode() in args:found.append(p.name)
 return found
def read_json_owned(path):
 p=Path(path);s=p.lstat();assert stat.S_ISREG(s.st_mode) and not stat.S_ISLNK(s.st_mode) and s.st_gid==5000 and stat.S_IMODE(s.st_mode)==0o660
 return json.loads(p.read_text())
def receive_window(fd,duration=60,read_fn=None,clock=None,sleep_fn=None,abort_fn=None):
 read_fn=os.read if read_fn is None else read_fn;clock=time.monotonic if clock is None else clock;sleep_fn=time.sleep if sleep_fn is None else sleep_fn
 started=clock();deadline=started+duration;stats={'readCalls':0,'bytesReceived':0,'nonemptyReads':0,'emptyReads':0,'wouldBlockReads':0,'interruptedReads':0,'rawReportsPersisted':False,'aborted':False}
 while clock()<deadline:
  if abort_fn is not None and abort_fn():stats['aborted']=True;break
  stats['readCalls']+=1
  try:
   data=read_fn(fd,4096)
   if data:stats['nonemptyReads']+=1;stats['bytesReceived']+=len(data);del data;sleep_fn(.001)
   else:stats['emptyReads']+=1;sleep_fn(.01)
  except BlockingIOError:stats['wouldBlockReads']+=1;sleep_fn(.01)
  except InterruptedError:stats['interruptedReads']+=1
  except OSError as e:
   if e.errno==errno.EAGAIN:stats['wouldBlockReads']+=1;sleep_fn(.01)
   elif e.errno==errno.EINTR:stats['interruptedReads']+=1
   else:raise
 stats['elapsedMs']=int((clock()-started)*1000)
 return stats
def receive_actions(fd,pipeline,generation=1,duration=60,read_fn=None,clock=None,sleep_fn=None,abort_fn=None,stats=None):
 from receive_diagnostics import record_shape,record_failure
 read_fn=os.read if read_fn is None else read_fn;clock=time.monotonic if clock is None else clock;sleep_fn=time.sleep if sleep_fn is None else sleep_fn
 started=clock();deadline=None if duration is None else started+duration
 def remaining(limit):return limit if deadline is None else min(limit,max(0,deadline-clock()))
 if stats is None:stats={}
 stats.update({'readCalls':0,'bytesReceived':0,'nonemptyReads':0,'emptyReads':0,'wouldBlockReads':0,'interruptedReads':0,'rawReportsPersisted':False,'aborted':False,'elapsedMs':0})
 stats['reportShapes']=[];stats['shapeOverflow']=0
 stats.pop('receiveFailure',None)
 stage='clock'
 def wait(limit):
  nonlocal stage
  stage='wait';sleep_fn(remaining(limit))
 try:
  while deadline is None or clock()<deadline:
   stage='tick'
   pipeline.tick()
   stage='abort'
   if abort_fn is not None and abort_fn():stats['aborted']=True;break
   stats['readCalls']+=1
   stage='read'
   try:data=read_fn(fd,4096)
   except BlockingIOError:
    stats['wouldBlockReads']+=1;wait(READ_BACKOFF_SECONDS);stage='clock';continue
   except InterruptedError:
    stats['interruptedReads']+=1;wait(READ_BACKOFF_SECONDS);stage='clock';continue
   except OSError as e:
    if e.errno==errno.EAGAIN:stats['wouldBlockReads']+=1;wait(READ_BACKOFF_SECONDS);stage='clock';continue
    if e.errno==errno.EINTR:stats['interruptedReads']+=1;wait(READ_BACKOFF_SECONDS);stage='clock';continue
    raise
   if not data:
    stats['emptyReads']+=1;wait(READ_BACKOFF_SECONDS);stage='clock';continue
   stats['nonemptyReads']+=1;stats['bytesReceived']+=len(data)
   record_shape(stats,data)
   stage='feed'
   try:pipeline.feed_raw(generation,data)
   finally:del data
   wait(READ_SUCCESS_YIELD_SECONDS);stage='clock'
 except BaseException as exc:
  record_failure(stats,stage,exc)
  raise
 finally:
  stats['elapsedMs']=int((clock()-started)*1000)
 return stats
def valid_a_ready(ready,run):
 if not isinstance(ready,dict) or ready.get('appId')!=APP_A_ID or ready.get('run')!=run or ready.get('stage')!='A_CONNECTED_F0_ACKED':return False
 reply=ready.get('f0afReply')
 if ready.get('f0afCalls')!=1 or not isinstance(reply,dict) or reply.get('returnValue') is not True or str(reply.get('address','')).lower()!=TARGET or str(reply.get('adapterAddress','')).lower()!='02:00:00:00:00:02':return False
 profiles=ready.get('profiles')
 if not isinstance(profiles,dict):return False
 for name in ('hid','gatt'):
  p=profiles.get(name)
  if not isinstance(p,dict) or p.get('returnValue') is not True or str(p.get('address','')).lower()!=TARGET or str(p.get('adapterAddress','')).lower()!='02:00:00:00:00:02' or p.get('connected') is not True or p.get('connecting') is not False or p.get('connectRequest') is not False:return False
 return True
def main():
 process=ordinary();run=None;shared=None;monitor=None;fd=None;report=None;outputs=None;pipeline=None;output_records=[];output_inventory=None;cleanup={'hidrawFdClosed':False,'outputFdsClosed':False,'outputsReleased':False,'emergencyReleaseAttempted':False,'emergencyReleaseVerified':False};app_a='/media/developer/apps/usr/palm/applications/'+APP_A_ID
 ownstate=STATE
 scope={'readCalls':0,'bytesReceived':0,'nonemptyReads':0,'emptyReads':0,'wouldBlockReads':0,'interruptedReads':0,'hidrawOpenCalls':0,'hidrawIdentityCalls':0,'keyOutputOpenCalls':0,'clickOutputOpenCalls':0,'bluetoothGetStatusCalls':6,'bluetoothWrites':0,'connectCalls':0,'disconnectCalls':0,'cccdWrites':0,'sensorWrites':0,'selectorWrites':0,'inputWrites':0,'grabCalls':0,'rawReportsPersisted':False,'fdClosed':False,'outputFdsClosed':False,'outputStateReleased':False}
 try:
  q=read_json_owned(ownstate/'request.json');run=q.get('run');assert q.get('appId')==APP_ID and isinstance(run,str) and len(run)==32
  shared=open_from_request(ownstate,APP_ID,run);ready=shared.read('a-ready')
  if not valid_a_ready(ready,run):raise RuntimeError('A-ready-identity-or-state-invalid')
  if len(live_a(app_a))!=1 or shared.read('a-result') is not None:raise RuntimeError('A-not-live-or-result-already-present')
  before_profiles=profile_snapshot()
  if not profile_connected(before_profiles):raise RuntimeError('profiles-not-connected-before-B')
  inv=scan_devices(timeout=INPUT_INVENTORY_TIMEOUT_SECONDS)
  if not inv['inventoryComplete'] or len(inv['targetCandidateIndexes'])!=1:raise RuntimeError('hidraw-target-not-uniquely-inspectable')
  idx=inv['targetCandidateIndexes'][0];path='/dev/hidraw'+str(idx);scope['hidrawOpenCalls']=1
  st=os.lstat(path)
  if stat.S_ISLNK(st.st_mode) or not stat.S_ISCHR(st.st_mode):raise RuntimeError('target-node-not-character-device')
  fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC);opened=os.fstat(fd);after=os.lstat(path)
  if (st.st_ino,st.st_dev,st.st_rdev)!=(opened.st_ino,opened.st_dev,opened.st_rdev) or (opened.st_ino,opened.st_dev,opened.st_rdev)!=(after.st_ino,after.st_dev,after.st_rdev):raise RuntimeError('target-node-changed-during-open')
  ident=identity(fd);scope['hidrawIdentityCalls']=1
  if ident.get('matches') is not True:raise RuntimeError('target-identity-changed-during-open')
  final_profiles=profile_snapshot()
  if not profile_comparison_valid(before_profiles,final_profiles):raise RuntimeError('profile-drift-during-target-open')
  outputs,output_records,output_inventory=open_verified_outputs(timeout=OUTPUT_INVENTORY_TIMEOUT_SECONDS)
  scope['keyOutputOpenCalls']=1;scope['clickOutputOpenCalls']=1
  output_profiles=profile_snapshot()
  if not profile_comparison_valid(final_profiles,output_profiles):raise RuntimeError('profile-drift-during-output-open')
  final_profiles=output_profiles
  if len(live_a(app_a))!=1 or shared.read('a-result') is not None:raise RuntimeError('A-not-live-or-result-after-output-open')
  report={'appId':APP_ID,'run':run,'status':'waiting-for-host-cue','process':process,'targetIndex':idx,'targetIdentity':ident,'inventoryComplete':inv['inventoryComplete'],'targetCandidateIndexes':inv['targetCandidateIndexes'],'profilesAtOpen':final_profiles,'outputDevices':output_records,'outputInventory':output_inventory,'scope':scope}
  bready={'appId':APP_ID,'run':run,'stage':'NONBLOCK_ACTIONS_READY','epochMs':int(time.time()*1000),'targetIndex':idx,'targetIdentity':ident,'targetFdOpen':True,'profileConnected':True,'process':process,'outputDevices':output_records,'outputInventory':output_inventory,'outputStateClear':True,'scope':{'hidrawOpenCalls':1,'hidrawIdentityCalls':1,'keyOutputOpenCalls':1,'clickOutputOpenCalls':1,'readCalls':0,'rawReportsPersisted':False,'sensorEnableAttempted':False}}
  atomic('b-ready-'+run+'.json',bready);publish(shared,'b-ready',bready)
  deadline=time.monotonic()+HOST_CUE_WAIT_SECONDS;cue=None
  while time.monotonic()<deadline:
   abort=shared.read('abort')
   if abort is not None:
    if abort.get('appId')==APP_A_ID and abort.get('run')==run and abort.get('stage')=='HOST_ABORT':raise RuntimeError('host-aborted-before-read')
   cue=shared.read('cue')
   if cue is not None:break
   time.sleep(.05)
  if not isinstance(cue,dict) or cue.get('appId')!='org.codex.siriremote.hidgattroutera20261029u' or cue.get('run')!=run or cue.get('stage')!='VERIFIED_RECEIVE_GATE' or type(cue.get('epochNs')) is not int:raise RuntimeError('host-cue-missing-or-invalid')
  base=CombinedReceiver(outputs,clock=time.monotonic,session_policy=InputSessionPolicy.sustained(READ_WINDOW_SECONDS),sensor_input_verified=False,max_actions=12)
  if not base.bind(1):raise RuntimeError('action-pipeline-bind-failed')
  # Slow Bluetooth status queries never block the input-processing thread.
  def sample_control():
   return len(live_a(app_a))==1 and shared.read('a-result') is None and profile_connected(profile_snapshot())
  monitor=ContinuityMonitor(sample_control,interval=1,max_age=5);monitor.start()
  if not monitor.wait_first(12):raise RuntimeError('continuity-first-sample-unavailable')
  pipeline=ObservedMotionGate(base,run=run,ready=ready,cue=cue,profiles=final_profiles,now_ms=int(time.time()*1000),continuity=monitor.current)
  start_ns=time.time_ns();report.update(status='receiving',cueEpochNs=cue['epochNs'],receiveStartEpochNs=start_ns)
  def aborted():
   if pipeline.closed:return True
   x=shared.read('abort')
   if x is None:return False
   return x.get('appId')==APP_A_ID and x.get('run')==run and x.get('stage')=='HOST_ABORT'
  stats=receive_actions(fd,pipeline,1,READ_WINDOW_SECONDS,abort_fn=aborted,stats=scope)
  pipeline.stop('receive-window-ended');report['actions']=pipeline.summary()
  if outputs is not None:cleanup['outputsReleased']=outputs.verify_released()
  report['receiveEndEpochNs']=time.time_ns();report['elapsedMs']=stats['elapsedMs']
  after_profiles=profile_snapshot();report['profilesAfterReceive']=after_profiles;report['profileStable']=profile_comparison_valid(before_profiles,after_profiles)
  report['status']='aborted' if scope.get('aborted') else 'complete' if report['profileStable'] and scope['rawReportsPersisted'] is False and scope['bytesReceived']>0 else 'no-input-observed' if report['profileStable'] else 'profile-state-uncertain'
 except BaseException as e:
  if report is None:report={'appId':APP_ID if run else None,'run':run,'status':'failed','scope':scope}
  else:report['status']='failed';report['error']=type(e).__name__+':'+str(e)[:160]
  report['error']=report.get('error',type(e).__name__+':'+str(e)[:160])
 finally:
  if pipeline is not None:
   try:pipeline.stop('native-finally');report['actions']=pipeline.summary()
   except BaseException as e:cleanup['pipelineStopError']=type(e).__name__
  if fd is not None:
   try:os.close(fd);scope['fdClosed']=True;cleanup['hidrawFdClosed']=True
   except OSError as e:scope['closeErrno']=errno.errorcode.get(e.errno,'OTHER')
  if outputs is not None:
   try:
    cleanup['emergencyReleaseAttempted']=True
    cleanup['emergencyReleaseVerified']=outputs.best_effort_release(max_attempts=2)
    if not cleanup['emergencyReleaseVerified']:cleanup['outputReleaseError']='EmergencyReleaseUnverified'
   except BaseException as e:cleanup['outputReleaseError']='EmergencyRelease'+type(e).__name__
   try:cleanup['outputsReleased']=outputs.verify_released();scope['outputStateReleased']=True
   except BaseException as e:cleanup['outputReleaseError']=type(e).__name__
   try:
    osummary=outputs.summary();scope['keyFrameWrites']=osummary['keyFrameWrites'];scope['clickFrameWrites']=osummary['clickFrameWrites'];scope['motionFrameWrites']=osummary['motionFrameWrites'];scope['inputWrites']=scope['keyFrameWrites']+scope['clickFrameWrites']+scope['motionFrameWrites'];cleanup['emergencyReleaseAttempts']=osummary['emergencyReleaseAttempts'];cleanup['emergencyReleaseErrors']=osummary['emergencyReleaseErrors']
   except BaseException as e:scope['outputSummaryError']=type(e).__name__
   try:outputs.close();cleanup['outputFdsClosed']=True;scope['outputFdsClosed']=True
   except BaseException as e:cleanup['outputCloseError']=type(e).__name__
  if monitor is not None:
   cleanup['continuityMonitorStopped']=monitor.stop(10)
   if not cleanup['continuityMonitorStopped'] and report is not None:report['status']='cleanup-unverified'
  if report is not None:
   report['cleanup']=cleanup
   if report.get('status')=='complete' and (not cleanup.get('hidrawFdClosed') or not cleanup.get('outputsReleased') or not cleanup.get('outputFdsClosed') or any(k in cleanup for k in ('pipelineStopError','outputReleaseError','outputCloseError'))):report['status']='cleanup-unverified'
  if run:
   report['scope']=scope
   report['readStarted']=bool(report.get('receiveStartEpochNs'))
   try:
    atomic('b-result-'+run+'.json',report)
    if shared is not None:publish(shared,'b-result',report)
   except BaseException:pass
  if shared is not None:
   try:shared.close()
   except OSError:pass
 if report.get('status')!='complete':raise RuntimeError('B-observation-not-complete:'+str(report.get('error','unknown')))
 print(json.dumps(report,separators=(',',':')),flush=True)
if __name__=='__main__':
 if '--import-check' in sys.argv:
  import action_pipeline,output_devices
  print(json.dumps({'imports':{'action_pipeline':str(Path(action_pipeline.__file__).resolve()),'output_devices':str(Path(output_devices.__file__).resolve())},'hardwareCalls':0},separators=(',',':')))
 else:main()
