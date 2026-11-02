"""Offline continuously rearming supervisor around one-cycle implementations.

No status pump, app package, autostart registration or device I/O is created
here. A stopped supervisor during a live receiver leaves ownership evidence.
"""
import time
from post_connect_rearm import PostConnectRearm

def run_loop(*,watch,lease,cycle_factory,stop,clock=time.monotonic,observe_timeout=30,finish_timeout=7320,emit=lambda _:None):
 if not callable(getattr(watch,'snapshot',None)) or not callable(getattr(watch,'disconnected_snapshot',None)) or not callable(getattr(lease,'held',None)) or not callable(cycle_factory) or not callable(getattr(stop,'wait',None)) or not callable(getattr(stop,'is_set',None)) or not callable(clock) or not callable(emit) or type(observe_timeout) not in (int,float) or not 0<observe_timeout<=60 or type(finish_timeout) not in (int,float) or not 0<finish_timeout<=7500:raise ValueError('invalid loop dependencies')
 rearm=None;last_completion=None;waiting_emitted=False
 while not stop.is_set():
  if lease.held() is not True:return {'status':'attention','reason':'supervisor-lease-lost'}
  if callable(getattr(watch,'is_open',None)) and watch.is_open() is not True:return {'status':'attention','reason':'status-watch-closed'}
  if rearm is None:
   ready=watch.snapshot()
   if ready is None:
    if not waiting_emitted and watch.disconnected_snapshot() is not None:emit('waiting-for-connection');waiting_emitted=True
    stop.wait(.5);continue
  else:
   try:ready=rearm.observe()
   except Exception:return {'status':'attention','reason':'rearm-observation-error'}
   if ready is None:stop.wait(.5);continue
  try:cycle=cycle_factory()
  except Exception:return {'status':'attention','reason':'cycle-creation-error'}
  try:
   result=cycle.begin()
   if type(result) is not dict:return {'status':'attention','reason':'launch-result-invalid'}
   if result.get('status')=='not-ready':
    if last_completion is not None:rearm=PostConnectRearm(watch,generation=last_completion['generation'],result=last_completion)
    stop.wait(.5);continue
   if result.get('status')!='accepted':return {'status':'attention','reason':'launch-unconfirmed'}
   emit('receiver-launch-accepted');deadline=clock()+observe_timeout;observed=False
   while not stop.is_set() and clock()<deadline:
    if lease.held() is not True:return {'status':'attention','reason':'lease-lost-during-receiver'}
    try:
     cycle.observe_receiver();observed=True;break
    except (FileNotFoundError,RuntimeError):stop.wait(.25)
   if not observed:return {'status':'attention','reason':'receiver-start-unobserved' if not stop.is_set() else 'stop-during-receiver'}
   emit('receiver-start-observed');deadline=clock()+finish_timeout;ready_to_finish=False
   while not stop.is_set() and clock()<deadline:
    if lease.held() is not True:return {'status':'attention','reason':'lease-lost-during-receiver'}
    if cycle.ready_to_finish() is True:ready_to_finish=True;break
    if callable(getattr(cycle,'receiver_failed',None)) and cycle.receiver_failed() is True:return {'status':'attention','reason':'receiver-ended-without-clean-result'}
    stop.wait(.5)
   if not ready_to_finish:return {'status':'attention','reason':'receiver-stop-unobserved' if not stop.is_set() else 'stop-during-receiver'}
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
