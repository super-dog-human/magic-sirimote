"""Experimental receiver native entry; no automatic installation or boot setup.

Explicitly assumes only cooperating project code issues Feature commands. It
cannot exclude other TV software. Not ready for hardware use without recovery.
"""
import json,os,signal,stat,threading
from pathlib import Path
from postconnect_receiver_app import run_from_state
from receiver_result_receipt import APP
from receiver_request_auth import CONTROLLER

ROOT=Path('/media/developer/apps/usr/palm/applications')
PKG=Path('/media/developer/apps/usr/palm/packages')

def _read_controller_pin(p,*,owner_uid=5999,group_gid=5000):
 p=Path(p);before=p.lstat()
 # This LG's developer-app files are observed as 0775 after a cold start.
 # Accept that platform mode for this packaged data file only. Runtime locks
 # and authentication records retain their separate, stricter policies.
 if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_nlink!=1 or before.st_uid!=owner_uid or before.st_gid!=group_gid or stat.S_IMODE(before.st_mode) not in (0o644,0o775) or before.st_size>32768:raise RuntimeError('controller pin invalid')
 def identity(s):return (s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
 f=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  s=os.fstat(f);raw=os.read(f,32769)
  end=os.fstat(f);named=p.lstat()
  if identity(before)!=identity(s) or identity(s)!=identity(end) or identity(end)!=identity(named) or len(raw)!=s.st_size:raise RuntimeError('controller pin changed')
 finally:os.close(f)
 def unique(pairs):
  out={}
  for k,v in pairs:
   if k in out:raise ValueError('duplicate controller pin')
   out[k]=v
  return out
 pin=json.loads(raw,object_pairs_hook=unique)
 if type(pin) is not dict or set(pin)!={'appId','files','packageInfoSha256'} or pin['appId']!=CONTROLLER:raise RuntimeError('controller pin shape invalid')
 return pin

def controller_pin():
 return _read_controller_pin(Path(__file__).resolve().parent/'controller-pin.json')

def controller_stop_proof(record,*,controller_app,controller_package,pin,proc_path='/proc',python_path='/usr/bin/python3',allow_exe_permission_denied=False):
 """Repeat package and unique live process checks; disclose narrow exe fallback."""
 import local_attestation as att
 import receiver_package_attestation as package
 if type(record) is not dict or record.get('appId')!=CONTROLLER or type(record.get('process')) is not dict or type(pin) is not dict or pin.get('appId')!=CONTROLLER:raise RuntimeError('invalid stop controller identity')
 p=record['process']
 if type(p.get('pid')) is not int or p['pid']<=0 or type(p.get('startTicks')) is not int or p['startTicks']<=0 or type(p.get('status')) is not dict:raise RuntimeError('invalid stop controller process')
 if package.package_matches(controller_app,controller_package,pin) is not True:raise RuntimeError('stop controller package mismatch')
 matches=att.matching_processes(controller_app,p['status'],proc_path,python_path,allow_exe_permission_denied=allow_exe_permission_denied)
 if len(matches)!=1 or matches[0].get('pid')!=p['pid'] or matches[0].get('startTicks')!=p['startTicks']:raise RuntimeError('stop controller process unconfirmed')
 return {'process':p,'executableVerified':matches[0].get('exeVerified') is not False}

def main():
 from retired_requests import reject_retired_requests
 reject_retired_requests(ROOT/APP/'state')
 stop=threading.Event()
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda _s,_f:stop.set())
 from controller_start_record import read_record
 from receiver_stop_ipc import StopEvent,read_stop
 state=ROOT/APP/'state';pin=controller_pin()
 # Recovery authenticates its own live controller and request. Do not first
 # require the original, potentially dead controller to still be running.
 try:os.stat(state/'recovery-request.json',follow_symlinks=False)
 except FileNotFoundError:pass
 else:
  from receiver_recovery_entry import run_recovery
  result=run_recovery(state=state,controller_app=str(ROOT/CONTROLLER),controller_package=str(PKG/CONTROLLER),pin=pin,stop=stop)
  return 0 if result.get('status')=='recovered' else 2
 record=read_record(state);run=record['run']
 accepted=controller_stop_proof(record,controller_app=str(ROOT/CONTROLLER),controller_package=str(PKG/CONTROLLER),pin=pin,allow_exe_permission_denied=True)
 def verify(rec):
  if rec!=record:return False
  current=controller_stop_proof(rec,controller_app=str(ROOT/CONTROLLER),controller_package=str(PKG/CONTROLLER),pin=pin,allow_exe_permission_denied=True)
  if current!=accepted:return False
  print(json.dumps({'stage':'controller-stop-attestation','executableVerified':current['executableVerified']},separators=(',',':')),flush=True)
  return True
 ipc=StopEvent(stop,lambda:read_stop(state,run,record,verify))
 # Explicitly experimental; never deploy until button semantics and duplicate
 # IR behavior have been checked on the target.
 result=run_from_state(state_path=ROOT/APP/'state',controller_app=str(ROOT/CONTROLLER),controller_package=str(PKG/CONTROLLER),controller_pin=controller_pin(),cooperative_only=True,allow_exe_permission_denied=True,duration=None,stop_event=ipc,system_buttons=True)
 return 0 if result.get('status')=='complete' and ipc.ipc_error is None else 2

if __name__=='__main__':raise SystemExit(main())
