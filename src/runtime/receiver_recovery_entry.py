"""Recovery runs inside B's UID, taking its existing private Feature lock."""
import os,time
from pathlib import Path
from receiver_request_auth import authenticate
from controller_start_record import read_record
from recovery_request import read_recovery_request
from receiver_result_reader import read_receipt
from prior_recovery import prior_run
from recovery_receipt import write_recovery_start,write_recovery_receipt
from local_feature_lease import LocalFeatureLease
from persistent_status_pump import PersistentConnectedStatusPump
from postconnect_receiver_device import paired_target
from borrowed_recovery_runtime import recover_zero
from recovery_records import RecoveryRecords,archive_uncertain
from local_attestation import _start_ticks

def recovery_controller_record(state):
 # A malformed takeover record is not equivalent to an absent one.
 try:record=read_record(state,name='recovery-controller-start.json')
 except FileNotFoundError:record=read_record(state)
 return record

def run_recovery(*,state,controller_app,controller_package,pin,stop):
 # A restarted controller has a distinct run-bound attestation record. The
 # original controller record stays intact for independent reconciliation.
 record=recovery_controller_record(state)
 run=record['run']
 accepted=authenticate(controller_record=record,run=run,controller_app=controller_app,controller_package=controller_package,pin=pin,receiver_state=state,read=read_recovery_request,allow_exe_permission_denied=True)
 old=prior_run(state,run,expected_process=accepted['request']['priorProcess'])
 if old['process']['status']['Uid'].split()!=[str(os.getuid())]*4:raise RuntimeError('prior receiver identity differs')
 def old_exit():
  try:return _start_ticks(Path('/proc')/str(old['process']['pid'])/'stat')!=old['process']['startTicks']
  except FileNotFoundError:return True
 if not old_exit():raise RuntimeError('old receiver still live')
 write_recovery_start(state,run)
 feature=None;pump=None;records=None;result={'run':run,'status':'attention','sensorStopVerified':False,'journalArchived':False,'featureExclusivity':'cooperative-only-unproven'}
 try:
  feature=LocalFeatureLease(state)
  records=RecoveryRecords(state,run)
  records({'stage':'recovery-intent','priorSensorState':'uncertain','priorOutcome':old['priorOutcome']})
  pump=PersistentConnectedStatusPump();pump.start();deadline=time.monotonic()+12
  while pump.snapshot() is None and not stop.is_set() and time.monotonic()<deadline:stop.wait(.1)
  current=pump.snapshot()
  if stop.is_set() or current is None:raise RuntimeError('recovery reconnect unavailable')
  proof=recover_zero(watch=pump.tracker,lease=feature,generation=current['generation'],paired_check=paired_target,external_feature_guard=lambda:not stop.is_set() and feature.held() is True,record=records,old_receiver_exited=old_exit,gatt_lookup_reply=accepted['request']['gattLookupReply'])
  def valid():
   now=pump.snapshot()
   return not stop.is_set() and old_exit() and feature.held() is True and type(now) is dict and now.get('generation')==current['generation']
  if not valid():raise RuntimeError('recovery proof changed')
  records({**proof,'stage':'recovery-zero-confirmed'})
  if archive_uncertain(state,run,owner_uid=os.getuid(),proof=valid) is not True:raise RuntimeError('uncertain archive failed')
  result={**result,'status':'recovered','sensorStopVerified':True,'journalArchived':True}
 except Exception as exc:
  from postconnect_receiver_entry import diagnostic_code
  result.update(diagnostic=diagnostic_code(exc),errorType=type(exc).__name__)
 finally:
  if pump is not None and pump.stop() is not True:result={**result,'status':'attention'}
  if records is not None:records.close()
  if feature is not None:feature.close()
 write_recovery_receipt(state,run,result)
 return result
