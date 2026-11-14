"""Short, bounded startup diagnostics; no payloads, coordinates or credentials.

This self-report does not authorize input or prove visible cursor movement.
At most 25 snapshots, five seconds apart; no periodic writes after two minutes.
Diagnostic failures disable further snapshots without interrupting input.
"""
import state_permissions
import json,math,os,re,stat,time
from pathlib import Path
from borrowed_mode_session import BorrowedModeSession
from local_attestation import _start_ticks
from receiver_result_receipt import APP
from receive_diagnostics import POINTER,LIMIT,count

def snapshot(summary):
 current=summary.get('current') or {};router=current.get('router') or {}
 pointer=router.get('pointer') or {};transport=current.get('transport') or {}
 return {'navigation':router.get('navigation',{'mode':'pointer','directionSwitches':0,'pointerSwitches':0}),'pointerCalibrated':pointer.get('calibrated') is True,
         'pointer':{k:min(LIMIT,pointer.get(k,0)) for k in POINTER},
         'motionBodyWrites':min(LIMIT,transport.get('bodyWrites',0)),
         'motionNeutralWrites':min(LIMIT,transport.get('neutralWrites',0))}

def valid(value):
 return (type(value) is dict and set(value)=={'navigation','pointerCalibrated','pointer','motionBodyWrites','motionNeutralWrites'}
         and type(value['navigation']) is dict and set(value['navigation'])=={'mode','directionSwitches','pointerSwitches'}
         and value['navigation']['mode'] in ('pointer','navigation') and count(value['navigation']['directionSwitches']) and count(value['navigation']['pointerSwitches'])
         and type(value['pointerCalibrated']) is bool and type(value['pointer']) is dict
         and set(value['pointer'])==set(POINTER) and all(count(x) for x in value['pointer'].values())
         and count(value['motionBodyWrites']) and count(value['motionNeutralWrites']))

class BoundedProgress:
 def __init__(self,emit,*,clock):
  self.emit=emit;self.clock=clock;self.next_at=None;self.last_at=None;self.writes=0;self.disabled=emit is None
 def maybe(self,summary):
  if self.disabled or self.writes>=25:return
  try:
   now=self.clock()
   if type(now) not in (int,float) or not math.isfinite(now) or now<0 or (self.last_at is not None and now<self.last_at):raise ValueError('invalid progress clock')
   self.last_at=now
   if self.next_at is not None and now<self.next_at:return
   self.next_at=now+5;self.writes+=1
   value=snapshot(summary())
   if not valid(value) or self.emit(value) is not True:raise RuntimeError('progress unconfirmed')
  except Exception:self.disabled=True

def write_progress(directory,run,session,value,*,state_uid=5999,group=5000,clock=time.time,start_ticks=None):
 if (type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run)
     or type(session) is not BorrowedModeSession or session.state!='active'
     or session.control_valid() is not True or type(session.view.generation) is not int
     or session.view.generation<=0 or not valid(value)):raise RuntimeError('invalid progress')
 now=clock();ticks=_start_ticks(Path('/proc/self/stat')) if start_ticks is None else start_ticks()
 if type(now) not in (int,float) or not math.isfinite(now) or now<=0 or type(ticks) is not int or ticks<=0:raise RuntimeError('invalid progress identity')
 data={'schema':1,'appId':APP,'run':run,'pid':os.getpid(),'startTicks':ticks,
       'generation':session.view.generation,'epochMs':int(now*1000),'rawReportsPersisted':False,**value}
 raw=(json.dumps(data,sort_keys=True,separators=(',',':'))+'\n').encode()
 if len(raw)>2048:raise RuntimeError('progress bound exceeded')
 d=os.open(Path(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 name='receiver-progress-'+run+'.json';temp=name+'.tmp';created=False
 try:
  ds=os.fstat(d)
  if ds.st_uid!=state_uid or ds.st_gid!=group or stat.S_IMODE(ds.st_mode) not in state_permissions.directory_modes():raise RuntimeError('unsafe progress directory')
  try:
   st=os.stat(name,dir_fd=d,follow_symlinks=False)
   if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_uid!=os.getuid() or st.st_gid!=group or stat.S_IMODE(st.st_mode)!=0o640:raise RuntimeError('unsafe progress destination')
  except FileNotFoundError:pass
  fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=d);created=True
  with os.fdopen(fd,'wb') as stream:
   os.fchmod(stream.fileno(),0o640);st=os.fstat(stream.fileno())
   if st.st_uid!=os.getuid() or st.st_gid!=group or st.st_nlink!=1:raise RuntimeError('unsafe progress file')
   stream.write(raw);stream.flush();os.fsync(stream.fileno())
  os.replace(temp,name,src_dir_fd=d,dst_dir_fd=d);created=False;os.fsync(d)
 finally:
  if created:os.unlink(temp,dir_fd=d)
  os.close(d)
 return True
