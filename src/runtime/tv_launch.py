"""TV-local launch with one bounded retry of an unentered bundled handoff.

Caller must durably record launch intent before calling. This file performs no
operation on import and does not by itself establish a TV service grant.
"""
import runtime_bundle as bundle
import json,re,subprocess,time
APPS={'A':bundle.app_id('org.codex.siriremote.hidgattroutera20261029u'),'B':bundle.app_id('org.codex.siriremote.hidgattrouterb20261029u')}
URI='luna://com.webos.applicationManager/launch'
def _strict(raw):
 if not isinstance(raw,str) or len(raw.encode('utf8'))>8192:raise ValueError('invalid reply')
 def unique(pairs):
  out={}
  for k,v in pairs:
   if k in out:raise ValueError('duplicate key')
   out[k]=v
  return out
 obj=json.loads(raw,object_pairs_hook=unique)
 if not isinstance(obj,dict) or type(obj.get('returnValue')) is not bool:raise ValueError('invalid reply')
 return obj
class Launcher:
 def __init__(self,run,invoke=subprocess.run):
  if not isinstance(run,str) or not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('invalid run')
  self.run=run;self.invoke=invoke;self.attempted=set();self.accepted_at=None;self.retried=False
 def launch(self,role,run):
  if run!=self.run or role not in APPS:raise ValueError('invalid target')
  if role in self.attempted:raise RuntimeError('launch already attempted')
  self.attempted.add(role)
  return self._dispatch(role)
 def _dispatch(self,role,*,retry=False):
  integrated=bundle.active()
  if integrated:
   from control_processes import processes
   # Do not treat reopening an old window as a fresh input worker launch.
   if processes()['ui']:return 'rejected'
  payload={'id':APPS[role],'params':{}}
  if integrated:
   payload['launchHidden']=True
   payload['params']={'inputHandoff':self.run}
  args=['/usr/bin/luna-send-pub','-n','1','-f',URI,json.dumps(payload,separators=(',',':'))]
  try:
   result=self.invoke(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=15,check=False)
   if result.returncode!=0 or not result.stdout:return 'unknown'
   reply=_strict(result.stdout)
   if integrated:
    from prelaunch_handoff_runtime import write_json_once
    info={'run':self.run,'epochMs':int(time.time()*1000),'accepted':reply['returnValue']}
    pid=reply.get('processId')
    if type(pid) is str and pid.isdecimal():pid=int(pid)
    if type(pid) is int and pid>0:info['processId']=pid
    try:write_json_once(bundle.ROOT/'roles/controller/state'/(('native-launch-retry-' if retry else 'native-launch-')+self.run+'.json'),info)
    except (OSError,RuntimeError,ValueError):pass
   if reply['returnValue'] is True:self.accepted_at=time.monotonic()
   return 'accepted' if reply['returnValue'] is True else 'rejected'
  except (OSError,subprocess.TimeoutExpired,ValueError,TypeError):return 'unknown'

 def retry_unentered(self,*,receiver_state,lease,clock=time.monotonic):
  """Retry the same app request, never Bluetooth/input start or a new run.

  SAM can acknowledge a launch without starting a new native process during
  a close/relaunch overlap. Only a still-valid, unentered request is eligible.
  Existing/starting wrappers and any receiver evidence suppress this retry.
  """
  if (not bundle.active() or self.retried or 'B' not in self.attempted
      or self.accepted_at is None or clock()-self.accepted_at<3):return False
  from pathlib import Path
  from control_processes import processes
  from receiver_request import read_request
  import os
  state=Path(receiver_state)
  def idle():
   found=processes()
   return not found['ui'] and not found['receiver'] and not found['legacy']
  if lease.held() is not True or not idle():return False
  names=set(os.listdir(state))
  forbidden={'receiver-'+kind+'-'+self.run+'.json' for kind in ('start','ready','progress','result')}
  forbidden.update(('borrowed-active','recovery-request.json','recovery-controller-start.json'))
  if names & forbidden:return False
  request=read_request(state,owner_uid=os.getuid())
  if request['run']!=self.run or lease.held() is not True or not idle():return False
  self.retried=True
  return self._dispatch('B',retry=True)=='accepted'
