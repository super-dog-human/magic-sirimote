"""Resident supervisor with graceful draining around real one-cycle
implementations.

No status pump, app package, autostart registration or device I/O is created
here. A stop request drains an admitted receiver; uncertain outcomes retain
ownership evidence.
"""
import time,threading
from post_connect_rearm import PostConnectRearm

def run_loop(*,watch,lease,cycle_factory,stop,clock=time.monotonic,observe_timeout=30,finish_timeout=7320,emit=lambda _:None,drain_wait=None,connect_tick=lambda:None,connection_admitted=lambda result:None,reopen_recovery=None):
 if not callable(getattr(watch,'snapshot',None)) or not callable(getattr(watch,'disconnected_snapshot',None)) or not callable(getattr(lease,'held',None)) or not callable(cycle_factory) or not callable(getattr(stop,'wait',None)) or not callable(getattr(stop,'is_set',None)) or not callable(clock) or not callable(emit) or type(observe_timeout) not in (int,float) or not 0<observe_timeout<=60 or type(finish_timeout) not in (int,float) or not 0<finish_timeout<=7500:raise ValueError('invalid loop dependencies')
 # A stop request prevents new sessions; an admitted receiver drains under the lease.
 # Use an independent wait: stop.wait would spin once SIGTERM sets stop.
 if drain_wait is None:drain_wait=threading.Event().wait
 if not callable(drain_wait):raise ValueError('invalid drain wait')
 rearm=None;last_completion=None;waiting_emitted=False
 while not stop.is_set():
  if lease.held() is not True:return {'status':'attention','reason':'supervisor-lease-lost'}
  if callable(getattr(watch,'is_open',None)) and watch.is_open() is not True:return {'status':'attention','reason':'status-watch-closed','requireDisconnect':last_completion is not None}
  connect_tick()
  if rearm is None:
   ready=watch.snapshot()
   if ready is None:
    if not waiting_emitted and watch.disconnected_snapshot() is not None:emit('waiting-for-connection');waiting_emitted=True
    connect_tick()
    wait_connected=getattr(watch,'wait_for_connection',None)
    if callable(wait_connected):wait_connected(.5,stop)
    else:stop.wait(.5)
    continue
  else:
   try:ready=rearm.observe()
   except Exception:return {'status':'attention','reason':'rearm-observation-error'}
   if ready is None:connect_tick();stop.wait(.5);continue
  try:cycle=cycle_factory()
  except Exception:return {'status':'attention','reason':'cycle-creation-error'}
  try:
   if stop.is_set():return {'status':'stopped'}
   result=cycle.begin()
   if type(result) is not dict:return {'status':'attention','reason':'launch-result-invalid'}
   if result.get('status')=='attention' and result.get('reason')=='receiver-package-mismatch':return {'status':'attention','reason':'receiver-package-mismatch'}
   if result.get('status')=='not-ready':
    if last_completion is not None:rearm=PostConnectRearm(watch,generation=last_completion['generation'],result=last_completion)
    connect_tick();stop.wait(.5);continue
   if result.get('status')!='accepted':return {'status':'attention','reason':'launch-unconfirmed'}
   connection_admitted(result)
   emit('receiver-launch-accepted');deadline=clock()+observe_timeout;observed=False
   while clock()<deadline:
    if lease.held() is not True:return {'status':'attention','reason':'lease-lost-during-receiver'}
    try:
     cycle.observe_receiver();observed=True;break
    except (FileNotFoundError,RuntimeError):drain_wait(.25)
   if not observed:return {'status':'attention','reason':'receiver-start-unobserved'}
   emit('receiver-start-observed');deadline=clock()+finish_timeout;ready_to_finish=False;stop_sent=False;next_health_check=clock()
   while clock()<deadline:
    if lease.held() is not True:return {'status':'attention','reason':'lease-lost-during-receiver'}
    if stop.is_set() and not stop_sent:
     if cycle.request_stop() is not True:return {'status':'attention','reason':'receiver-stop-request-unconfirmed'}
     stop_sent=True;deadline=clock()+min(finish_timeout,60)
    if not stop_sent and clock()>=next_health_check:
     healthy=cycle.receiver_healthy() is True
     checked_at=clock();next_health_check=checked_at+5
     if healthy:deadline=checked_at+finish_timeout
    if not stop_sent and callable(getattr(cycle,'receiver_idle',None)) and cycle.receiver_idle() is True:connect_tick()
    if callable(getattr(cycle,'note_disconnect',None)):cycle.note_disconnect()
    if cycle.ready_to_finish() is True:ready_to_finish=True;break
    if callable(getattr(cycle,'receiver_failed',None)) and cycle.receiver_failed() is True:
     if not callable(getattr(cycle,'recover_after_disconnect',None)):return {'status':'attention','reason':'receiver-ended-without-clean-result'}
     # Keep supervising the uncertain prior run while awaiting a fresh link.
     recovered=None
     while not stop.is_set():
      if lease.held() is not True:return {'status':'attention','reason':'lease-lost-during-recovery'}
      # A closed watcher cannot prove a disconnect or a fresh connection.
      # Preserve the unfinished run for independent recovery instead of
      # spinning indefinitely or launching with invented connection proof.
      if callable(getattr(watch,'is_open',None)) and watch.is_open() is not True:
       if not callable(reopen_recovery) or not callable(getattr(cycle,'rebind_recovery_watch',None)):return {'status':'attention','reason':'status-watch-closed-during-recovery'}
       replacement,proof=reopen_recovery()
       if cycle.rebind_recovery_watch(replacement,proof) is not True:return {'status':'attention','reason':'recovery-rebind-unconfirmed'}
       watch=replacement
      recovered=cycle.recover_after_disconnect()
      if recovered is not None:break
      connect_tick();drain_wait(.5)
     if recovered is None:return {'status':'attention','reason':'recovery-interrupted-prior-state-unknown'}
     if recovered.get('status')!='recovered' or recovered.get('modeZeroVerified') is not True or recovered.get('oldReceiverExitVerified') is not True or recovered.get('journalArchived') is not True or recovered.get('launchIntentArchived') is not True:return {'status':'attention','reason':'recovery-unconfirmed'}
     emit('session-recovered');ready_to_finish='recovered';break
    drain_wait(.5)
   if not ready_to_finish:return {'status':'attention','reason':'receiver-stop-unobserved'}
   if ready_to_finish=='recovered':
    # Recovery proved zero on this current connection. No clean-complete
    # receipt is fabricated and another disconnect is unnecessary.
    rearm=None;last_completion=None;continue
   result=cycle.finish()
   if type(result) is not dict or result.get('status')!='complete' or result.get('sensorStopVerified') is not True or result.get('journalArchived') is not True or result.get('launchIntentArchived') is not True:return {'status':'attention','reason':'completion-unconfirmed'}
   last_completion=result;rearm=PostConnectRearm(watch,generation=result['generation'],result=result);emit('session-complete')
  except Exception:
   return {'status':'attention','reason':'cycle-error'}
  finally:
   try:cycle.close()
   except Exception:
    # The caller must not assume clean supervision if local close failed.
    return {'status':'attention','reason':'cycle-close-error'}
 return {'status':'stopped'}
