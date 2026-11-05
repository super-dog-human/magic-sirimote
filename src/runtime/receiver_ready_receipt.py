"""Run-bound ready marker after mode-1 readback; no raw inputs persisted.

The marker is a self-report and must be paired with independent process and
live status checks. It does not prove subsequent user input or cursor motion.
"""
import json,os,re,stat,time
from pathlib import Path
from borrowed_mode_session import BorrowedModeSession
from receiver_result_receipt import APP
from local_attestation import _start_ticks

def write_ready(directory,run,session,*,state_uid=5999,group=5000,clock=time.time,start_ticks=None,resume_sequence=None,pointer_ready=True):
 if type(pointer_ready) is not bool:raise ValueError('invalid pointer readiness')
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run) or type(session) is not BorrowedModeSession or session.state!='active' or session.control_valid() is not True or type(getattr(session.view,'generation',None)) is not int or session.view.generation<=0:raise RuntimeError('receiver not ready')
 if resume_sequence is not None and (type(resume_sequence) is not int or not 1<=resume_sequence<=4096):raise ValueError('invalid resume sequence')
 now=clock()
 if type(now) not in (int,float) or now<=0:raise RuntimeError('invalid clock')
 ticks=_start_ticks(Path('/proc/self/stat')) if start_ticks is None else start_ticks()
 if type(ticks) is not int or ticks<=0:raise RuntimeError('process start time unavailable')
 data={'schema':1,'appId':APP,'run':run,'stage':'receiver-ready','pid':os.getpid(),'startTicks':ticks,'generation':session.view.generation,'sensorModeVerified':1,'epochMs':int(now*1000),'rawReportsPersisted':False}
 data.update(navigationReady=True,pointerReady=pointer_ready)
 d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or ds.st_uid!=state_uid or ds.st_gid!=group or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe ready directory')
  name='receiver-ready-'+run+'.json' if resume_sequence is None else 'receiver-resume-ready-'+run+'-'+str(resume_sequence)+'.json'
  f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=d)
  try:
   os.fchmod(f,0o640);x=os.fstat(f)
   if not stat.S_ISREG(x.st_mode) or x.st_nlink!=1 or x.st_uid!=os.getuid() or x.st_gid!=group:raise RuntimeError('unsafe ready file')
   with os.fdopen(f,'wb') as stream:
    f=None;stream.write((json.dumps(data,sort_keys=True,separators=(',',':'))+'\n').encode());stream.flush();os.fsync(stream.fileno())
   os.fsync(d)
  finally:
   if f is not None:os.close(f)
 finally:os.close(d)
 return True
