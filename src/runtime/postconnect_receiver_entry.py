"""Receiver setup after a verified connection.

Caller must start its own fresh status watcher after app launch and supply
verified paired-target and external feature-exclusivity checks. The native
entry point invokes this module. The caller remains responsible for watcher
and lease lifetime and for recovery from a killed process or ambiguous
lookup.
"""
import json,math,re,threading
from combined_receiver import CombinedReceiver
from borrowed_receive_bridge import receive_once
from borrowed_sustained_receive import receive_sustained
from media_receive_session import receive_with_media
from borrowed_session_runner import run_once
from input_session_policy import InputSessionPolicy
import borrowed_runtime

class _OutputPreparation:
 """Prepare independent local sinks without writing events or remote commands."""
 def __init__(self,open_outputs,open_system_keys,clock):
  self.outputs=None;self.system_sink=None;self.system_fd=None;self.error=None
  self.stage='open-outputs';self.timings={};self.lock=threading.Lock();self.started=[]
  def outputs():self.outputs=open_outputs()
  def system_keys():
   self.system_sink,self.system_fd=open_system_keys()
   if type(self.system_fd) is not int or self.system_fd<0 or not callable(getattr(self.system_sink,'pulse',None)) or not callable(getattr(self.system_sink,'verify_released',None)):raise RuntimeError('system key open unconfirmed')
  def task(stage,label,action):
   def prepare():
    try:
     started=clock();action()
     with self.lock:self.timings[label]=round((clock()-started)*1000)
    except BaseException as exc:self.fail(stage,exc)
   return threading.Thread(target=prepare,name='receiver-'+stage)
  self.threads=[('open-outputs',task('open-outputs','outputOpenMs',outputs))]
  if open_system_keys is not None:self.threads.append(('open-system-keys',task('open-system-keys','systemKeyOpenMs',system_keys)))
 def fail(self,stage,error):
  with self.lock:
   if self.error is None:self.stage=stage;self.error=error
 def start(self):
  for stage,thread in self.threads:
   try:thread.start()
   except BaseException as exc:self.fail(stage,exc);break
   self.started.append(thread)
 def join(self):
  # Never release the lease or begin recovery while a preparation thread
  # might still acquire a descriptor. Both open routines have bounded limits.
  for thread in self.started:thread.join()
  return self.outputs,self.system_sink,self.system_fd

def diagnostic_code(exc):
 # Persist only fixed, non-sensitive categories, not arbitrary exception text.
 text=str(exc)
 if re.fullmatch(r'gatt-rejected-(?:[0-9]{1,4}|unknown)',text):return text
 if text in ('notification-control-unavailable','notification-intent-unrecorded','notification-enable-unconfirmed','notification-setting-unsupported','notification-proof-unrecorded'):return text
 if re.fullmatch(r'preborrow-(?:lease|feature|snapshot|age|hid|gatt|exception)',text):return text
 fixed={'input handoff unconfirmed':'input-handoff-unconfirmed','receiver connection unavailable':'input-handoff-no-connection','input handoff intent not recorded':'input-handoff-journal-failed','input handoff not recorded':'input-handoff-ack-journal-failed','target inventory incomplete':'target-inventory-incomplete','target not unique':'target-not-unique','target not present':'target-not-present','target ambiguous':'target-ambiguous','target inventory invalid':'target-inventory-invalid','target node invalid':'target-node-invalid','target node changed':'target-node-changed','target identity mismatch':'target-identity-mismatch','Call guard rejected dispatch':'guard-rejected','Native application identity unverified':'native-identity-rejected','Luna call timed out':'luna-timeout','Luna call timed out during monitor pump':'luna-timeout','Luna command returned nonzero':'luna-nonzero','Luna response was not valid JSON':'luna-invalid-json','invalid borrowed view':'borrowed-view-invalid','control changed after lookup':'control-changed','receive-unconfirmed':'receive-unconfirmed','output-release-unverified':'output-release-unverified','control-not-ready':'receive-control-not-ready'}
 return fixed.get(text,'other-'+type(exc).__name__ if type(exc).__name__ in ('ValueError','RuntimeError','LunaCallError','TimeoutError','OSError') else 'other-error')

def run_connected_once(*,watch,lease,paired_check,external_feature_guard,record,
                       open_target,open_outputs,close_target,duration,abort,
                       clock,receive_clock=None,read_fn=None,sleep_fn=None,on_ready=None,on_progress=None,open_system_keys=None,close_system_keys=None,input_handoff_check=None,gatt_lookup_reply=None):
 if not all(callable(x) for x in (paired_check,external_feature_guard,record,open_target,open_outputs,close_target,abort,clock)) or not callable(getattr(watch,'snapshot',None)) or (on_ready is not None and not callable(on_ready)) or (on_progress is not None and not callable(on_progress)) or (duration is not None and (type(duration) not in (int,float) or not math.isfinite(duration) or not 0<duration<=7200)):
  raise ValueError('missing receiver dependency')
 setup_started=clock();timings={}
 initial=watch.snapshot()
 if (type(initial) is not dict or type(initial.get('generation')) is not int or initial['generation']<=0
     or paired_check() is not True or external_feature_guard() is not True):
  return {'status':'not-ready','reason':'connection-or-feature-unavailable'}
 timings['admissionMs']=round((clock()-setup_started)*1000)
 if (open_system_keys is None)!=(close_system_keys is None) or (open_system_keys is not None and not all(callable(x) for x in (open_system_keys,close_system_keys))):raise ValueError('invalid system key dependencies')
 stage='input-start';generation=initial['generation'];fd=None;outputs=None;system_sink=None;system_fd=None;receive_stats={};out={'status':'attention','reason':'setup-unconfirmed'};close_errors=[];receive_started=False;preparation=None;early=None;media=None
 try:
  prepared=_OutputPreparation(open_outputs,open_system_keys,clock)
  prepared.start();preparation=prepared
  started=clock()
  if input_handoff_check is None:
   input_start=borrowed_runtime.initialize_input(watch=watch,lease=lease,paired=True,external_feature_guard=external_feature_guard,record=record,clock=clock,gatt_lookup_reply=gatt_lookup_reply)
  else:
   input_start=borrowed_runtime.accept_prelaunch_input(watch=watch,lease=lease,paired=True,external_feature_guard=external_feature_guard,record=record,handoff_check=input_handoff_check,clock=clock,gatt_lookup_reply=gatt_lookup_reply)
  timings['inputStartMs']=round((clock()-started)*1000)
  stage='after-input-start'
  if abort() is not False:raise RuntimeError('stopped after input start')
  stage='open-target'
  started=clock()
  fd=open_target()
  timings['targetOpenMs']=round((clock()-started)*1000)
  if type(fd) is not int or fd<0:raise RuntimeError('target open unconfirmed')
  started=clock();outputs,system_sink,system_fd=preparation.join()
  timings.update(preparation.timings);timings['outputJoinMs']=round((clock()-started)*1000)
  stage=preparation.stage
  if preparation.error is not None:raise preparation.error
  stage='connection-recheck'
  started=clock()
  current=watch.snapshot()
  if type(current) is not dict or type(current.get('generation')) is not int or current['generation']!=generation or paired_check() is not True or external_feature_guard() is not True:raise RuntimeError('connection changed during open')
  timings['connectionRecheckMs']=round((clock()-started)*1000)
  if abort() is not False:raise RuntimeError('stopped before sensor preparation')
  stage='receiver-setup'
  receiver=None
  if duration is not None and duration<=60 and system_sink is None:
   policy=InputSessionPolicy.sustained(duration) if duration>30 else None
   receiver=CombinedReceiver(outputs,clock=clock,session_policy=policy,max_actions=12 if policy is None else policy.max_actions,action_history_limit=None if policy is None else 32)
   if receiver.bind(generation) is not True:raise RuntimeError('receiver bind failed')
  import runtime_bundle as bundle
  if bundle.active() and duration is None:
   from preborrow_guard import PreBorrowGuard
   from early_navigation import EarlyNavigation
   admission=PreBorrowGuard(watch,lease,generation=generation,external_feature_guard=external_feature_guard,clock=clock)
   emitter=None;screen=None
   if system_sink is not None:
    from media_receive_session import MediaResources
    media=MediaResources(system_sink);media.start();emitter=media.sink.pulse;screen=media.screen
   early=EarlyNavigation(outputs,fd,generation=generation,guard=admission,abort=abort,
                         clock=receive_clock or clock,read_fn=read_fn,system_key_emit=emitter,screen_control=screen)
   early.start();receive_started=True
   print(json.dumps({'stage':'navigation-input-ready','epochMs':int(__import__('time').time()*1000),'elapsedMs':round((clock()-setup_started)*1000)}),flush=True)
  def prepare():
   started=clock()
   session=borrowed_runtime.prepare(watch=watch,lease=lease,paired=True,external_feature_guard=external_feature_guard,record=record,clock=clock,input_start=input_start,**({'pump':early} if early is not None else {}))
   timings['gattPrepareMs']=round((clock()-started)*1000)
   return session
  def receive(session):
   nonlocal receive_started
   if abort() is not False:raise RuntimeError('stopped before receiving')
   def publish_ready():
    nonlocal receive_started
    if abort() is not False or session.control_valid() is not True:return False
    if on_ready is not None and on_ready(session) is not True:return False
    import runtime_bundle as bundle
    if bundle.active():
     try:print(json.dumps({'stage':'receiver-setup-timing','elapsedMs':round((clock()-setup_started)*1000),'steps':timings}),flush=True)
     except Exception:pass
    receive_started=True;return True
   publish_progress=None if on_progress is None else lambda value:on_progress(session,value)
   if early is not None:
    return receive_sustained(session,outputs,fd,duration=duration,abort=abort,clock=receive_clock or clock,read_fn=read_fn,sleep_fn=sleep_fn,stats=receive_stats,on_ready=publish_ready,on_progress=publish_progress,prepared_receiver=early)
   if receiver is None:
    if system_sink is not None:
     return receive_with_media(session,outputs,fd,system_key_sink=system_sink,duration=duration,abort=abort,clock=receive_clock or clock,read_fn=read_fn,sleep_fn=sleep_fn,stats=receive_stats,on_ready=publish_ready,on_progress=publish_progress)
    return receive_sustained(session,outputs,fd,duration=duration,abort=abort,clock=receive_clock or clock,read_fn=read_fn,sleep_fn=sleep_fn,stats=receive_stats,on_ready=publish_ready,on_progress=publish_progress)
   return receive_once(session,receiver,fd,duration=duration,abort=abort,clock=receive_clock or clock,read_fn=read_fn,sleep_fn=sleep_fn,stats=receive_stats,on_ready=publish_ready)
  stage='session'
  def stop_early():
   try:early.stop()
   finally:
    if media is not None:media.close()
  out=run_once(prepare,receive,classify=diagnostic_code,**({'before_stop':stop_early} if early is not None else {}))
  if type(out) is dict:
   summary=outputs.summary()
   out={**out,'outputCounts':{k:summary[k] for k in ('keyFrameWrites','clickFrameWrites','motionFrameWrites')},'readStats':receive_stats}
 except Exception as exc:
  code=diagnostic_code(exc)
  if stage=='open-outputs':
   from output_devices import failure_code
   code=failure_code(exc)
  elif code.startswith('other-'):code='setup-'+stage
  out={'status':'attention','reason':'setup-'+type(exc).__name__,'diagnostic':code,'errorType':type(exc).__name__,'setupStage':stage}
 finally:
  if early is not None:
   try:early.stop()
   except Exception:close_errors.append('early-input-stop-error')
  if media is not None:
   try:media.close()
   except Exception:close_errors.append('media-worker-stop-unverified')
  if preparation is not None:
   outputs,system_sink,system_fd=preparation.join()
   if preparation.error is not None:close_errors.append('output-preparation-failed')
  if system_fd is not None:
   try:
    if system_sink is None or system_sink.verify_released() is not True:close_errors.append('system-key-release-unverified')
   except Exception:close_errors.append('system-key-release-error')
   try:close_system_keys(system_fd)
   except Exception:close_errors.append('system-key-close-error')
  if outputs is not None:
   try:
    # Do not send release events for a setup that never processed input.
    if outputs.verify_released() is not True:raise RuntimeError('release unverified')
   except Exception:
    if not receive_started:close_errors.append('output-release-unverified')
    else:
     try:
      if outputs.best_effort_release() is not True or outputs.verify_released() is not True:close_errors.append('output-release-unverified')
     except Exception:close_errors.append('output-release-error')
   try:outputs.close()
   except Exception:close_errors.append('output-close-error')
  if fd is not None:
   try:close_target(fd)
   except Exception:close_errors.append('target-close-error')
 if close_errors:return {'status':'attention','reason':'resource-close-unverified','errors':close_errors,'sessionResult':out}
 if out.get('setupStage')=='open-target':out={**out,'resourcesClosed':True}
 return out
