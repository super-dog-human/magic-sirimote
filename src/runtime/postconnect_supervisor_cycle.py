"""Composition for one TV-local watcher/receiver cycle.

Starts no process on import. Caller owns the status pump and supervisor
lease; the receiver package and live process are checked separately.
Uncertain outcomes retain the launch and handoff evidence.
"""
import os,time
import runtime_bundle as bundle
from post_connect_receiver_launch import PostConnectReceiverLaunch
from receiver_launch_intent import ReceiverLaunchIntent
from receiver_request import write_request
from controller_start_record import write_record
from receiver_result_reader import read_receipt
from receiver_process_observer import observe_live,verify_exit,observed_process_ended
from receiver_handoff_archive import archive as archive_handoff
from tv_launch import Launcher

class SupervisorCycle:
 def __init__(self,*,watch,lease,controller_state,receiver_state,run,controller_process,receiver_app,receiver_package,receiver_pin,allow_exe_permission_denied=False,intent_factory=ReceiverLaunchIntent,launcher_factory=Launcher,write_start=write_record,write_receiver_request=write_request,clock=time.time,lookup_cache=None):
  if not callable(getattr(watch,'snapshot',None)) or not callable(getattr(lease,'held',None)) or lease.held() is not True or type(controller_process) is not dict or controller_process.get('pid')!=os.getpid() or not callable(clock):raise ValueError('invalid supervisor context')
  self.lookup_cache=lookup_cache;self.recovery_lookup_reply=None
  self.controller_state=controller_state;self.prelaunch=None;self.watch=watch;self.lease=lease;self.receiver_state=receiver_state;self.run=run;self.controller_process=controller_process;self.receiver_app=receiver_app;self.receiver_package=receiver_package;self.pin=receiver_pin;self.allow_fallback=allow_exe_permission_denied;self.write_start=write_start;self.write_request=write_receiver_request;self.clock=clock;self.intent=intent_factory(controller_state,run);self.launcher=launcher_factory(run);self.live=None;self.generation=None;self.finished=False;self.finish_attempted=False;self.recovery_disconnect=None;self.recovery_attempted=False
 def begin(self):
  if self.lease.held() is not True:raise RuntimeError('supervisor lease lost')
  if bundle.active():
   from control_processes import processes
   # A relaunch reuses the existing app's device namespace. Wait until the
   # prior window exits before starting input for a fresh native launch.
   if processes()['ui']:return {'status':'not-ready'}
  import receiver_package_attestation as package
  # Check before writing a launch request or creating a launch intent. This
  # does not eliminate a later file-replacement race; the observer also checks.
  if package.package_matches(self.receiver_app,self.receiver_package,self.pin) is not True:
   return {'status':'attention','reason':'receiver-package-mismatch'}
  current=self.watch.snapshot()
  if type(current) is not dict or type(current.get('generation')) is not int or current['generation']<1:return {'status':'not-ready'}
  generation=current['generation']
  # The existing durable intent blocks a second start after uncertain outcome.
  if self.intent({'stage':'receiver-launch-intent','run':self.run,'generation':generation}) is not True:return {'status':'attention','reason':'intent-unconfirmed'}
  try:
   if self.write_start(self.receiver_state,self.run,self.controller_process) is not True:raise RuntimeError('controller record unavailable')
   if self.write_request(self.receiver_state,self.run,int(self.clock()*1000)+120000) is not True:raise RuntimeError('receiver request unavailable')
   from pathlib import Path
   from borrowed_gatt_requester import revalidate_client
   from prelaunch_handoff_runtime import PrelaunchOwner,lookup_before_input,write_json_once
   def lookup_record(stage,value):
    write_json_once(Path(self.controller_state)/('gatt-'+self.run+'-'+stage+'.json'),{'run':self.run,**value})
   reused=self.lookup_cache.take(watch=self.watch,lease=self.lease) if self.lookup_cache is not None else None
   if reused is None:
    reply,generation=lookup_before_input(watch=self.watch,lease=self.lease,record=lookup_record,verify_ready=revalidate_client if bundle.active() else None)
   else:
    reply,generation=reused
    lookup_record('reused',{'generation':generation,'reply':reply,'ownership':'unproven'})
   self.prelaunch=PrelaunchOwner(self,self.controller_state,generation,lookup_reply=reply)
   self.prelaunch.begin()
  except Exception:return {'status':'attention','reason':'input-start-or-launch-unconfirmed'}
  self.generation=generation
  return {'status':'accepted','generation':generation,'receiverReady':False}
 def observe_receiver(self):
  if self.generation is None or self.finished or self.lease.held() is not True:raise RuntimeError('receiver observation unavailable')
  try:
   self.live=observe_live(receiver_state=self.receiver_state,run=self.run,app_path=self.receiver_app,pkg_path=self.receiver_package,pin=self.pin,allow_exe_permission_denied=self.allow_fallback)
  except FileNotFoundError:
   if bundle.active():self.launcher.retry_unentered(receiver_state=self.receiver_state,lease=self.lease)
   raise
  return {'run':self.run,'processObserved':True,'executableVerified':self.live['executableVerified']}
 def ready_to_finish(self):
  if self.live is None or self.finished or self.finish_attempted or self.lease.held() is not True:return False
  try:result=read_receipt(self.receiver_state,self.run)
  except FileNotFoundError:return False
  return verify_exit(live=self.live,result=result,app_path=self.receiver_app,pkg_path=self.receiver_package,pin=self.pin) is True
 def receiver_failed(self):
  if self.live is None or self.finished or self.lease.held() is not True:return False
  if observed_process_ended(self.live,app_path=self.receiver_app) is not True:return False
  try:result=read_receipt(self.receiver_state,self.run)
  except FileNotFoundError:return True
  return type(result) is not dict or result.get('status')!='complete'
 def finish(self):
  if self.live is None or self.finished or self.finish_attempted or self.lease.held() is not True:raise RuntimeError('receiver completion unavailable')
  result=read_receipt(self.receiver_state,self.run)
  def proof():return self.lease.held() is True and verify_exit(live=self.live,result=result,app_path=self.receiver_app,pkg_path=self.receiver_package,pin=self.pin) is True
  if proof() is not True:raise RuntimeError('receiver exit or cleanup unconfirmed')
  self.finish_attempted=True
  if archive_handoff(self.receiver_state,self.run,owner_uid=os.getuid()) is not True:raise RuntimeError('handoff archive unconfirmed')
  if self.intent.archive_completed(result,independent_proof=proof) is not True:raise RuntimeError('launch archive unconfirmed')
  self.finished=True
  return {'run':self.run,'generation':self.generation,'status':'complete','sensorStopVerified':True,'journalArchived':True,'launchIntentArchived':True,'executableVerified':self.live['executableVerified']}
 def request_stop(self):
  from receiver_stop_ipc import write_stop
  if self.live is None or self.finished or self.lease.held() is not True:raise RuntimeError('stop unavailable')
  return write_stop(self.receiver_state,self.run,self.controller_process)
 def receiver_healthy(self):
  if self.live is None or self.lease.held() is not True:return False
  try:
   current=observe_live(receiver_state=self.receiver_state,run=self.run,app_path=self.receiver_app,pkg_path=self.receiver_package,pin=self.pin,allow_exe_permission_denied=self.allow_fallback)
   # Preserve the admitted proof, including an explicitly unverified executable.
   # matching_processes permits fallback only for exe PermissionError.
   return current==self.live
  except (OSError,RuntimeError,ValueError):return False
 def receiver_idle(self):
  return self.prelaunch is not None and self.prelaunch.handoff.receiver_idle is True
 def note_disconnect(self):
  value=self.watch.disconnected_snapshot()
  if type(value) is dict and value.get('generation',0)>self.generation:self.recovery_disconnect=value['generation']
 def rebind_recovery_watch(self,new_watch,proof):
  # Generations are local to each watcher. Only an explicit, fresh
  # disconnected-then-connected observation permits crossing this boundary.
  if self.live is None or self.finished or self.recovery_attempted or self.lease.held() is not True:raise RuntimeError('recovery rebind unavailable')
  if not callable(getattr(self.watch,'is_open',None)) or self.watch.is_open() is not False:raise RuntimeError('old watcher is not closed')
  if proof!={'status':'connected','disconnectObserved':True}:raise RuntimeError('fresh disconnect proof missing')
  if not callable(getattr(new_watch,'is_open',None)) or new_watch.is_open() is not True:raise RuntimeError('new watcher unavailable')
  current=new_watch.snapshot()
  if type(current) is not dict or type(current.get('generation')) is not int or current['generation']<1:raise RuntimeError('new connection unverified')
  self.watch=new_watch;self.recovery_disconnect=current['generation']
  return True
 def recover_after_disconnect(self):
  from recovery_request import write_recovery_request
  from prior_recovery import prior_run
  from recovery_reader import read_recovery_start,read_recovery_receipt
  from recovery_handoff_archive import archive_recovered
  import receiver_package_attestation as package
  if self.live is None or self.finished or self.lease.held() is not True:raise RuntimeError('recovery supervision unavailable')
  self.note_disconnect()
  if self.recovery_disconnect is None:return None
  current=self.watch.snapshot()
  if self.recovery_attempted and (time.monotonic()>self.recovery_deadline or current is None):raise RuntimeError('recovery connection or deadline lost')
  if type(current) is not dict or current.get('generation',0)<self.recovery_disconnect:return None
  if not self.recovery_attempted:
   if bundle.active():
    from control_processes import processes
    if processes()['ui']:return None
   if package.package_matches(self.receiver_app,self.receiver_package,self.pin) is not True or observed_process_ended(self.live,app_path=self.receiver_app) is not True:return None
   from owned_idle_recovery import accept_recovery
   local=accept_recovery(self)
   if local is not None:return local
   prior=prior_run(self.receiver_state,self.run,expected_process=self.live['process'])
   self.recovery_prior_outcome=prior['priorOutcome']
   self.recovery_attempted=True
   from recovery_lookup_handoff import obtain
   reply,generation=obtain(watch=self.watch,lease=self.lease,directory=self.controller_state,run=self.run,
    eligible=lambda:self.lease.held() is True and observed_process_ended(self.live,app_path=self.receiver_app) is True)
   self.recovery_lookup_reply=reply
   self.recovery_generation=generation;self.recovery_deadline=time.monotonic()+120;self.recovery_live=None
   # Durable O_EXCL request blocks another recovery launch after uncertainty.
   write_recovery_request(self.receiver_state,self.run,int(self.clock()*1000)+120000,prior_process=self.live['process'],gatt_lookup_reply=reply)
   if Launcher(self.run).launch('B',self.run)!='accepted':raise RuntimeError('recovery launch unconfirmed')
   return None
  if current['generation']!=self.recovery_generation:raise RuntimeError('connection changed during recovery')
  if time.monotonic()>self.recovery_deadline:raise RuntimeError('recovery deadline expired')
  if self.recovery_live is None:
   try:self.recovery_live=observe_live(receiver_state=self.receiver_state,run=self.run,app_path=self.receiver_app,pkg_path=self.receiver_package,pin=self.pin,read=read_recovery_start,allow_exe_permission_denied=self.allow_fallback)
   except (FileNotFoundError,RuntimeError):return None
  try:receipt=read_recovery_receipt(self.receiver_state,self.run)
  except FileNotFoundError:return None
  if receipt.get('status')!='recovered' or receipt.get('sensorStopVerified') is not True or receipt.get('journalArchived') is not True or receipt.get('process')!=self.recovery_live['process']:raise RuntimeError('recovery proof unconfirmed')
  def proof():
   now=self.watch.snapshot()
   return self.lease.held() is True and package.package_matches(self.receiver_app,self.receiver_package,self.pin) is True and observed_process_ended(self.recovery_live,app_path=self.receiver_app) is True and type(now) is dict and now.get('generation')==self.recovery_generation
  if proof() is not True:return None
  result={'run':self.run,'status':'recovered','modeZeroVerified':True,'oldReceiverExitVerified':True,'journalArchived':True,'generation':self.recovery_generation,'priorReceiptStatus':self.recovery_prior_outcome}
  if archive_recovered(self.receiver_state,self.run,owner_uid=os.getuid()) is not True:raise RuntimeError('recovery handoff archive failed')
  if self.intent.archive_recovered(result,independent_proof=proof) is not True:raise RuntimeError('recovery launch archive failed')
  if self.lookup_cache is not None:
   self.lookup_cache.remember(self.recovery_lookup_reply,watch=self.watch,lease=self.lease,generation=self.recovery_generation)
  self.finished=True;return {**result,'launchIntentArchived':True}
 def close(self):
  try:
   if self.prelaunch is not None:self.prelaunch.close()
  finally:self.intent.close()
