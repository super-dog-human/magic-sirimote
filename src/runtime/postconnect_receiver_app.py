"""Post-connect receiver orchestration.

The caller must provide a truthful feature guard and a valid application
state folder. A project-local lock alone does not establish system-wide
exclusivity. The native entry point owns launch and recovery.
"""
import os,threading,time
from hid_input import ordinary
from persistent_status_pump import PersistentConnectedStatusPump
from local_feature_lease import LocalFeatureLease
from atomic_session_directory import AtomicSessionDirectory
from postconnect_receiver_device import paired_target,open_target
from postconnect_receiver_entry import run_connected_once
from output_devices import open_verified_outputs
from receiver_result_receipt import write_receipt,write_start
from receiver_request_auth import authenticate
from controller_start_record import read_record
from cooperative_feature_assumption import CooperativeFeatureAssumption
from receiver_ready_receipt import write_ready
from receiver_progress import write_progress

def run_once(*,state_path,run,external_feature_guard=None,cooperative_only=False,duration=60,stop_event=None,system_buttons=False,
             startup_timeout=12,clock=time.monotonic,pump_factory=None,
             lease_factory=LocalFeatureLease,journal_factory=AtomicSessionDirectory,
             session_runner=run_connected_once,identity_check=ordinary,input_handoff_check=None,gatt_lookup_reply=None):
 if type(system_buttons) is not bool or type(cooperative_only) is not bool or (cooperative_only and external_feature_guard is not None) or (not cooperative_only and not callable(external_feature_guard)) or not callable(clock) or (duration is not None and (type(duration) not in (int,float) or not 0<duration<=7200)) or type(startup_timeout) not in (int,float) or not 0<startup_timeout<=30:raise ValueError('invalid app configuration')
 stop=stop_event or threading.Event()
 if not callable(getattr(stop,'is_set',None)) or not callable(getattr(stop,'wait',None)):raise ValueError('invalid stop event')
 identity_check();lease=None;journal=None;pump=None;result={'status':'attention','reason':'startup-unconfirmed'};cleanup=[];pump_stopped=False
 try:
  lease=lease_factory(state_path);journal=journal_factory(state_path,run)
  if cooperative_only:external_feature_guard=CooperativeFeatureAssumption(lease,explicit_cooperative_only=True)
  factory=pump_factory or (lambda:PersistentConnectedStatusPump())
  pump=factory();pump.start();deadline=clock()+startup_timeout
  while not stop.is_set() and clock()<deadline:
   if pump.snapshot() is not None:break
   if pump.stop_event.is_set():break
   stop.wait(.1)
  if stop.is_set():result={'status':'stopped-before-receiver'}
  elif pump.snapshot() is None:result={'status':'not-ready','reason':'connected-profile-not-observed'}
  else:
   from hid_retry_guard import make_guard
   initial=pump.tracker.snapshot()
   if type(initial) is not dict or type(initial.get('generation')) is not int:raise RuntimeError('retry generation unavailable')
   retry_guard=make_guard(watch=pump.tracker,lease=lease,stop=stop,feature=external_feature_guard,generation=initial['generation'])
   def open_with_retry():return open_target(allow_retry=retry_guard,wait=stop.wait)
   def outputs():return open_verified_outputs(allow_retry=retry_guard,wait=stop.wait)[0]
   extra={}
   if input_handoff_check is not None:extra.update(input_handoff_check=input_handoff_check,gatt_lookup_reply=gatt_lookup_reply)
   if system_buttons:
    from system_key_device import open_verified_system_key
    extra.update({'open_system_keys':open_verified_system_key,'close_system_keys':os.close})
   result=session_runner(watch=pump.tracker,lease=lease,paired_check=paired_target,external_feature_guard=external_feature_guard,record=journal,open_target=open_with_retry,open_outputs=outputs,close_target=os.close,duration=duration,abort=stop.is_set,clock=clock,on_ready=lambda session:write_ready(state_path,run,session),on_progress=lambda session,value:write_progress(state_path,run,session,value),**extra)
 except Exception as exc:result={'status':'attention','reason':'startup-'+type(exc).__name__}
 finally:
  if pump is not None:
   try:
    pump_stopped=pump.stop() is True
    if not pump_stopped:cleanup.append('status-pump-stop-unverified')
   except Exception:cleanup.append('status-pump-stop-error')
  if journal is not None:
   if not cleanup and type(result) is dict and result.get('status')=='complete':
    try:
     if journal.archive_completed(result=result,pump_stopped=pump_stopped) is not True:cleanup.append('session-archive-unverified')
     else:result={**result,'journalArchived':True}
    except Exception:cleanup.append('session-archive-error')
   elif not cleanup and type(result) is dict and result.get('status') in ('not-ready','stopped-before-receiver'):
    try:
     if journal.discard_empty(pump_stopped=pump_stopped) is not True:cleanup.append('empty-session-discard-unverified')
    except Exception:cleanup.append('empty-session-discard-error')
   try:journal.close()
   except Exception:cleanup.append('journal-close-error')
  if lease is not None:
   try:lease.close()
   except Exception:cleanup.append('lease-close-error')
 feature='cooperative-only-unproven' if cooperative_only else 'external-guard-supplied-unverified'
 if cleanup:return {'run':run,'status':'attention','reason':'app-cleanup-unverified','errors':cleanup,'sessionResult':result,'featureExclusivity':feature}
 return {**result,'run':run,'featureExclusivity':feature}

def run_and_record(*,state_path,run,**kwargs):
 try:write_start(state_path,run)
 except Exception:return {'run':run,'status':'attention','reason':'start-receipt-unverified'}
 result=run_once(state_path=state_path,run=run,**kwargs)
 if result.get('status')=='not-ready':
  import json
  reason=result.get('reason')
  print(json.dumps({'receiverStartup':reason if reason in ('connected-profile-not-observed','connection-or-feature-unavailable') else 'not-ready'}),flush=True)
 try:write_receipt(state_path,run,result)
 except Exception:return {'run':run,'status':'attention','reason':'receipt-unverified','sessionResult':result}
 return result

def run_authorized(*,state_path,run,controller_record,controller_app,controller_package,controller_pin,external_feature_guard=None,cooperative_only=False,allow_exe_permission_denied=False,duration=60,stop_event=None,system_buttons=False):
 """Use only after a trusted transport supplies the controller's live record."""
 try:
  authenticate(controller_record=controller_record,run=run,controller_app=controller_app,controller_package=controller_package,pin=controller_pin,receiver_state=state_path,allow_exe_permission_denied=allow_exe_permission_denied)
 except Exception:
  result={'run':run,'status':'attention','reason':'controller-or-request-unverified','featureExclusivity':'cooperative-only-unproven' if cooperative_only else 'external-guard-supplied-unverified'}
  try:write_start(state_path,run);write_receipt(state_path,run,result)
  except Exception:pass
  return result
 from prelaunch_handoff_runtime import receiver_client
 client=receiver_client(controller_app,controller_record)
 from controller_status_watch import ControllerStatusWatch
 return run_and_record(state_path=state_path,run=run,input_handoff_check=client.check,gatt_lookup_reply=client.gatt_lookup_reply,pump_factory=lambda:ControllerStatusWatch(client),external_feature_guard=external_feature_guard,cooperative_only=cooperative_only,duration=duration,stop_event=stop_event,system_buttons=system_buttons)

def run_from_state(*,state_path,controller_app,controller_package,controller_pin,external_feature_guard=None,cooperative_only=False,allow_exe_permission_denied=False,duration=60,stop_event=None,system_buttons=False):
 try:record=read_record(state_path);run=record['run']
 except Exception:return {'status':'attention','reason':'controller-record-unverified'}
 return run_authorized(state_path=state_path,run=run,controller_record=record,controller_app=controller_app,controller_package=controller_package,controller_pin=controller_pin,external_feature_guard=external_feature_guard,cooperative_only=cooperative_only,allow_exe_permission_denied=allow_exe_permission_denied,duration=duration,stop_event=stop_event,system_buttons=system_buttons)
