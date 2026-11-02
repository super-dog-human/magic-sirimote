"""Independent package/live-process and process-exit checks for a receiver.

This is a local reference; actual permissions and receipts on the TV are not
verified. Permission-limited executable fallback is explicitly reported.
"""
from pathlib import Path
import local_attestation as att
import receiver_package_attestation as package
from receiver_result_reader import read_start

def observed_process_ended(live,*,app_path,proc_path='/proc'):
 try:
  p=live['process']
  if type(p['pid']) is not int or p['pid']<=0 or type(p['startTicks']) is not int or p['startTicks']<=0 or att.candidate_pids(app_path,proc_path):return False
  try:current=att._start_ticks(Path(proc_path)/str(p['pid'])/'stat')
  except FileNotFoundError:return True
  return current!=p['startTicks']
 except (OSError,RuntimeError,ValueError,TypeError,KeyError):return False

def observe_live(*,receiver_state,run,app_path,pkg_path,pin,proc_path='/proc',python_path='/usr/bin/python3',read=read_start,allow_exe_permission_denied=False):
 receipt=read(receiver_state,run)
 if not package.package_matches(app_path,pkg_path,pin):raise RuntimeError('receiver package mismatch')
 proc=receipt['process'];matches=att.matching_processes(app_path,proc['status'],proc_path,python_path,allow_exe_permission_denied=allow_exe_permission_denied)
 if len(matches)!=1 or matches[0].get('pid')!=proc['pid'] or matches[0].get('startTicks')!=proc['startTicks']:raise RuntimeError('live receiver identity unconfirmed')
 return {'run':run,'process':proc,'executableVerified':matches[0].get('exeVerified') is not False}

def verify_exit(*,live,result,app_path,pkg_path,pin,proc_path='/proc'):
 try:
  if type(live) is not dict or type(result) is not dict or result.get('run')!=live.get('run') or result.get('process')!=live.get('process') or result.get('status')!='complete' or result.get('sensorStopVerified') is not True or result.get('journalArchived') is not True:return False
  if not package.package_matches(app_path,pkg_path,pin) or att.candidate_pids(app_path,proc_path):return False
  proc=live['process'];p=Path(proc_path)/str(proc['pid'])/'stat'
  try:current=att._start_ticks(p)
  except FileNotFoundError:return True
  # PID reuse proves the recorded process no longer has the same start time.
  return current!=proc['startTicks']
 except (OSError,RuntimeError,ValueError,TypeError,KeyError):return False
