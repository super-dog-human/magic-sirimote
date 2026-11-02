"""Explicit, finite native-to-native socket diagnostic. No Bluetooth or input calls."""
import json,os,re,stat,time,threading
from pathlib import Path
from input_start_handoff import InputStartHandoff,HandoffServer,HandoffClient
from prelaunch_handoff_runtime import write_json_once
from receiver_result_receipt import _process_identity
import native_app_identity
A='org.codex.siriremote.autocoord20261029v';B='org.codex.siriremote.hidgattrouterb20261029u'
ROOT=Path('/media/developer/apps/usr/palm/applications')

def read(path,uid):
 f=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  s=os.fstat(f)
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=uid or s.st_gid!=5000 or s.st_nlink!=1 or stat.S_IMODE(s.st_mode)!=0o640 or s.st_size>2048:raise RuntimeError('diagnostic metadata invalid')
  raw=os.read(f,2049)
  if len(raw)!=s.st_size:raise RuntimeError('diagnostic read incomplete')
  return json.loads(raw)
 finally:os.close(f)

def maybe_diagnose(role):
 if role not in ('controller','receiver'):raise ValueError('invalid role')
 state=ROOT/(A if role=='controller' else B)/'state';request=state/'handoff-diagnostic-request.json'
 if not request.exists():return False
 q=read(request,5415)
 if set(q)!={'schema','run','role','expiresEpochMs'} or q['schema']!=1 or q['role']!=role or not re.fullmatch('[a-f0-9]{32}',q['run']) or type(q['expiresEpochMs']) is not int or not 0<q['expiresEpochMs']-int(time.time()*1000)<=180000:raise RuntimeError('diagnostic request invalid')
 if native_app_identity.verify_self() is not True:raise RuntimeError('diagnostic native identity invalid')
 run=q['run'];write_json_once(state/('handoff-diagnostic-claim-'+run+'.json'),{'run':run,'role':role})
 cstate=ROOT/A/'state';sock=cstate/('d'+run[:16]);meta=cstate/('handoff-diagnostic-meta-'+run+'.json');server=None
 result={'run':run,'role':role,'pid':os.getpid(),'uid':os.getuid(),'bluetoothOperations':0,'inputOperations':0}
 try:
  if role=='controller':
   identity={k:_process_identity()[k] for k in ('pid','startTicks')};done=threading.Event();peers=[]
   def authorized(pid,uid,gid):
    if uid!=5636 or gid!=5000 or pid==os.getpid():return False
    peers.append({'pid':pid,'uid':uid,'gid':gid});return True
   h=InputStartHandoff(run=run,controller=identity,generation=1,connection_valid=lambda _:True,journal=lambda _:True,send_input_start=lambda:True,launch_receiver=lambda _:True)
   # Synthetic proof is diagnostic only; no device initialization is attempted.
   h.begin();validate=h.validate
   def checked(request,pid):
    value=validate(request,pid);done.set();return value
   h.validate=checked;server=HandoffServer(sock,h,authorized)
   write_json_once(meta,{'run':run,'token':h.token,'controller':identity,'controllerUid':os.getuid()})
   result['received']=done.wait(40);result['peers']=peers
   if result['received']:time.sleep(.2)
   result['status']='connected' if result['received'] else 'timeout'
  else:
   m=read(meta,6959)
   if m.get('run')!=run:raise RuntimeError('diagnostic session mismatch')
   client=HandoffClient(path=str(sock),run=run,token=m['token'],controller=m['controller'],controller_uid=m['controllerUid'])
   result['status']='connected' if client.check() else 'failed';result['controller']=m['controller']
 except Exception as e:result.update(status='error',errorType=type(e).__name__,error=str(e))
 finally:
  if server is not None:server.close()
  write_json_once(state/('handoff-diagnostic-result-'+run+'.json'),result)
 return True
