"""Resident TV controller: connect, supervise, stop, and recover verified sessions."""
import runtime_bundle as bundle
import json,os,signal,stat,threading,time
from pathlib import Path
from hid_input import ordinary
from persistent_status_pump import PersistentConnectedStatusPump
from supervisor_lease import SupervisorLease
from stop_request import StopMonitor, publish_instance
from boot_diagnostics import BootTrace
from postconnect_supervisor_cycle import SupervisorCycle
from resident_supervisor_loop import run_loop
from resident_autoconnect import AutoConnect
from bootstrap_connect import bootstrap,BootstrapClient,confirm_and_retire
from passive_connection_wait import wait_connected
from receiver_result_receipt import _process_identity

APP=bundle.app_id('org.codex.siriremote.autocoord20261029v')
B=bundle.app_id('org.codex.siriremote.hidgattrouterb20261029u')
ROOT=Path('/media/developer/apps/usr/palm/applications')
PKG=Path('/media/developer/apps/usr/palm/packages')
STATE=bundle.role_path('controller',ROOT/APP)/'state'

def load_config():
 from controller_pin_client import read_pin
 from pin_transport import call
 return read_pin(lambda uri,payload: call(uri,payload,timeout=8))

def recover_retained_if_connected(*,lease,pin,stop,timeout=90,clock=time.monotonic,trace=lambda _:None):
 """Prove the old processes ended, reconnect once, then recover once."""
 from orphan_reconcile import _read
 from takeover_prepare import inspect
 from takeover_recovery import execute
 trace('bootstrap-takeover-start')
 intent,_=_read(lease.dirfd,'receiver-launch-intent.json',os.getuid(),5000,0o640,historical=True)
 run=intent.get('run') if type(intent) is dict else None
 import re
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run):raise RuntimeError('prior intent invalid')
 context={'run':run,'controller_state':STATE,'receiver_state':bundle.role_path('receiver',ROOT/B)/'state','controller_app':str(bundle.role_path('controller',ROOT/APP)),'receiver_app':str(bundle.role_path('receiver',ROOT/B)),'receiver_package':str(bundle.package_path(PKG/B)),'pin':pin,'lease':lease}
 # A receiver may be finishing after its controller died. Only re-read this
 # specific uncertain process state; do not reconnect or issue a command
 # until the process-exit and journal checks succeed.
 exit_deadline=clock()+90
 while not stop.is_set() and lease.held() is True and clock()<exit_deadline:
  try:
   if inspect(**context).get('status')!='eligible':raise RuntimeError('prior state not eligible')
   trace('bootstrap-takeover-eligible')
   break
  except RuntimeError as exc:
   if str(exc)!='prior receiver still present or unverified':raise
   stop.wait(1)
 else:raise RuntimeError('prior receiver exit unavailable')
 # Existing bootstrap reserves a durable one-shot HID connect intent and
 # independently checks the bonded target. A failure is not retried here.
 connected=bootstrap(lease=lease,stop=stop,deadline=clock()+45,trace=trace)
 trace('bootstrap-takeover-connected' if connected else 'bootstrap-takeover-not-connected')
 pump=PersistentConnectedStatusPump();pump.start()
 try:
  deadline=clock()+timeout
  while not stop.is_set() and lease.held() is True and clock()<deadline:
   if pump.tracker.is_open() is not True:raise RuntimeError('recovery watch unavailable')
   if pump.tracker.snapshot() is not None:
    trace('bootstrap-takeover-watch-ready')
    return execute(run=run,watch=pump.tracker,stop=stop,**{k:v for k,v in context.items() if k!='run'})
   stop.wait(.25)
  raise RuntimeError('connected target unavailable')
 finally:
  if pump.stop() is not True:raise RuntimeError('recovery watch termination unconfirmed')

def main():
 from retired_requests import reject_retired_requests
 reject_retired_requests(STATE)
 ordinary();pin=load_config();stop=threading.Event()
 for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda _s,_f:stop.set())
 lease=SupervisorLease(STATE);pump=None;stop_monitor=None
 try:
  process=_process_identity()
  import secrets
  instance=secrets.token_hex(16)
  publish_instance(lease.dirfd,pid=process['pid'],start_ticks=process['startTicks'],instance=instance)
  stop_monitor=StopMonitor(lease.dirfd,stop,pid=process['pid'],start_ticks=process['startTicks'],instance=instance,**({'owner_uid':os.getuid()} if bundle.active() else {}))
  stop_monitor.start()
  trace=BootTrace()
  from orphan_reconcile import reconcile
  try:
   reconcile(controller_state=STATE,receiver_state=bundle.role_path('receiver',ROOT/B)/'state',controller_app=str(bundle.role_path('controller',ROOT/APP)),receiver_app=str(bundle.role_path('receiver',ROOT/B)),receiver_package=str(bundle.package_path(PKG/B)),pin=pin,lease=lease)
  except (OSError,RuntimeError,ValueError):
   try:
    result=recover_retained_if_connected(lease=lease,pin=pin,stop=stop,trace=trace.add)
    if type(result) is not dict or result.get('status')!='recovered':
     trace.add('bootstrap-takeover-result-unconfirmed');trace.publish(lease.dirfd,instance);return 2
   except (OSError,RuntimeError,ValueError) as exc:
    fixed={'prior receiver still present or unverified':'bootstrap-takeover-receiver-live','prior uncertain sensor journal unavailable':'bootstrap-takeover-journal-ineligible','takeover proof unavailable':'bootstrap-takeover-proof-unavailable','recovery watch unavailable':'bootstrap-takeover-watch-unavailable','connected target unavailable':'bootstrap-takeover-connection-unavailable'}
    trace.add(fixed.get(str(exc),'bootstrap-takeover-error-'+type(exc).__name__))
    try:trace.publish(lease.dirfd,instance)
    except (OSError,RuntimeError,ValueError):pass
    return 2
  connected=bootstrap(lease=lease,stop=stop,deadline=time.monotonic()+120,trace=trace.add)
  try:trace.publish(lease.dirfd,instance)
  except (OSError,RuntimeError,ValueError):pass
  if not connected:
   # Do not resend a potentially dispatched connect: passively wait for an
   # independently observed bonded target and two fresh connected profiles.
   client=BootstrapClient(pump=lambda:None,guard=lambda:not stop.is_set() and lease.held() is True,clock=time.monotonic,native_app=True)
   if wait_connected(client=client,lease=lease,stop=stop).get('status')!='connected':return 2
   confirm_and_retire(client=client,lease=lease,stop=stop)
  assist=None;ready_announced=False;reopen_attempts=0
  def cycle():
   import secrets
   return SupervisorCycle(watch=pump.tracker,lease=lease,controller_state=STATE,receiver_state=bundle.role_path('receiver',ROOT/B)/'state',run=secrets.token_hex(16),controller_process=process,receiver_app=str(bundle.role_path('receiver',ROOT/B)),receiver_package=str(bundle.package_path(PKG/B)),receiver_pin=pin,allow_exe_permission_denied=True)
  def emit(event):
   nonlocal ready_announced
   if event=='waiting-for-connection' and not ready_announced:
    name='controller-ready-'+str(os.getpid())+'-'+str(process['startTicks'])+'.json'
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=lease.dirfd)
    try:
     os.fchmod(fd,0o640)
     with os.fdopen(fd,'wb') as stream:
      fd=None;stream.write((json.dumps({'schema':1,'appId':APP,'stage':'waiting-for-connection','pid':os.getpid(),'startTicks':process['startTicks'],'epochMs':int(time.time()*1000)},separators=(',',':'))+'\n').encode());stream.flush();os.fsync(stream.fileno())
     os.fsync(lease.dirfd)
     ready_announced=True
    finally:
     if fd is not None:os.close(fd)
  def reopen_recovery():
   nonlocal pump
   # Keep the same uncertain receiver cycle and lease. Replacing a failed
   # watcher is not itself proof of a disconnect.
   old,pump=pump,None
   if old is None or old.stop() is not True or lease.held() is not True:raise RuntimeError('old watch exit unconfirmed')
   client=BootstrapClient(pump=lambda:None,guard=lambda:not stop.is_set() and lease.held() is True,clock=time.monotonic,native_app=True)
   proof=wait_connected(client=client,lease=lease,stop=stop,require_disconnect=True)
   if proof!={'status':'connected','disconnectObserved':True} or lease.held() is not True:raise RuntimeError('fresh reconnect unconfirmed')
   pump=PersistentConnectedStatusPump();pump.start();assist.watch=pump.tracker
   deadline=time.monotonic()+15
   while not stop.is_set() and lease.held() is True and time.monotonic()<deadline:
    if pump.tracker.is_open() is not True:break
    if pump.tracker.snapshot() is not None:return pump.tracker,proof
    stop.wait(.25)
   raise RuntimeError('replacement watch unavailable')
  while not stop.is_set():
   pump=PersistentConnectedStatusPump();pump.start()
   if assist is None:assist=AutoConnect(watch=pump.tracker,lease=lease,stop=stop)
   else:assist.watch=pump.tracker  # preserve uncertain connect latch and backoff
   result=run_loop(watch=pump.tracker,lease=lease,cycle_factory=cycle,stop=stop,emit=emit,connect_tick=assist.tick,connection_admitted=assist.admission_observed,reopen_recovery=reopen_recovery)
   if result.get('status')=='stopped':return 0
   if result.get('reason')!='status-watch-closed' or type(result.get('requireDisconnect')) is not bool:return 2
   closed,pump=pump,None
   if closed.stop() is not True:return 2
   if lease.held() is not True:return 2
   delay=min(300,5*(2**min(reopen_attempts,6)));reopen_attempts+=1
   if stop.wait(delay):return 0
   client=BootstrapClient(pump=lambda:None,guard=lambda:not stop.is_set() and lease.held() is True,clock=time.monotonic,native_app=True)
   if wait_connected(client=client,lease=lease,stop=stop,require_disconnect=result['requireDisconnect']).get('status')!='connected':return 2
   if result['requireDisconnect']:reopen_attempts=0
  return 0
 finally:
  try:
   if pump is not None and pump.stop() is not True:raise RuntimeError('status pump stop unverified')
  finally:
   try:
    if stop_monitor is not None:stop_monitor.close()
   finally:lease.close()

if __name__=='__main__':raise SystemExit(main())
