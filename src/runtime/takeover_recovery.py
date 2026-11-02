"""One-shot controller takeover and receiver recovery; not wired to live startup.

The caller supplies a fresh, connected target watcher and an exclusive
supervisor lease. Any ambiguous launch or recovery outcome is retained.
"""
import math,re,time
from takeover_prepare import prepare
from recovery_request import write_recovery_request
from recovery_reader import read_recovery_start,read_recovery_receipt
from receiver_process_observer import observe_live,observed_process_ended
from orphan_reconcile import reconcile
from tv_launch import Launcher
import receiver_package_attestation as package

def execute(*,run,watch,lease,stop,controller_state,receiver_state,controller_app,receiver_app,receiver_package,pin,
            prepare_fn=prepare,write_request=write_recovery_request,launcher_factory=Launcher,observe=observe_live,
            read_receipt=read_recovery_receipt,process_ended=observed_process_ended,reconcile_fn=reconcile,
            wall=time.time,clock=time.monotonic,timeout=120):
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run) or type(timeout) not in (int,float) or not 0<timeout<=120:raise ValueError('invalid recovery context')
 if not all(callable(x) for x in (prepare_fn,write_request,launcher_factory,observe,read_receipt,process_ended,reconcile_fn,wall,clock)):raise ValueError('invalid recovery adapter')
 current=watch.snapshot()
 if type(current) is not dict or type(current.get('generation')) is not int or current['generation']<1:raise RuntimeError('target connection unavailable')
 generation=current['generation'];start=clock();last=start;deadline=start+timeout
 def guard():
  nonlocal last
  now=clock()
  if type(now) not in (int,float) or not math.isfinite(now) or now<last:raise RuntimeError('clock invalid')
  last=now;sample=watch.snapshot()
  return (now<deadline and not stop.is_set() and lease.held() is True and type(sample) is dict and type(sample.get('generation')) is int and sample['generation']==generation and package.package_matches(receiver_app,receiver_package,pin) is True)
 if not guard():raise RuntimeError('recovery preflight unavailable')
 proof=prepare_fn(run=run,controller_state=controller_state,receiver_state=receiver_state,controller_app=controller_app,receiver_app=receiver_app,receiver_package=receiver_package,pin=pin,lease=lease)
 if type(proof) is not dict or proof.get('status')!='prepared' or proof.get('run')!=run or type(proof.get('priorProcess')) is not dict or not guard():raise RuntimeError('takeover preparation unconfirmed')
 # Lookup itself has a durable O_EXCL intent. Bind the recovery guard only
 # after its expected GATT transition has settled; the child adopts the reply.
 from recovery_lookup_handoff import obtain
 reply,generation=obtain(watch=watch,lease=lease,directory=controller_state,run=run,
  eligible=lambda:not stop.is_set() and lease.held() is True and clock()<deadline)
 if not guard():raise RuntimeError('recovery lookup connection unavailable')
 # O_EXCL is the one-attempt marker. An uncertain dispatch is never replayed.
 if write_request(receiver_state,run,int(wall()*1000)+120000,prior_process=proof['priorProcess'],gatt_lookup_reply=reply) is not True:raise RuntimeError('recovery request unconfirmed')
 if not guard():raise RuntimeError('connection changed before recovery dispatch')
 if launcher_factory(run).launch('B',run)!='accepted':raise RuntimeError('recovery dispatch unconfirmed')
 live=None
 while guard():
  if live is None:
   try:live=observe(receiver_state=receiver_state,run=run,app_path=receiver_app,pkg_path=receiver_package,pin=pin,read=read_recovery_start,allow_exe_permission_denied=True)
   except (FileNotFoundError,RuntimeError):stop.wait(.25);continue
  try:receipt=read_receipt(receiver_state,run)
  except FileNotFoundError:stop.wait(.25);continue
  if (type(receipt) is not dict or receipt.get('status')!='recovered' or receipt.get('sensorStopVerified') is not True or receipt.get('journalArchived') is not True or receipt.get('process')!=live.get('process')):raise RuntimeError('recovery receipt unconfirmed')
  if process_ended(live,app_path=receiver_app) is not True:stop.wait(.25);continue
  if not guard():raise RuntimeError('recovery proof changed')
  result=reconcile_fn(controller_state=controller_state,receiver_state=receiver_state,controller_app=controller_app,receiver_app=receiver_app,receiver_package=receiver_package,pin=pin,lease=lease)
  if type(result) is not dict or result.get('status')!='reconciled' or result.get('run')!=run:raise RuntimeError('reconciliation unconfirmed')
  return {'status':'recovered','run':run,'priorOutcome':proof['priorOutcome'],'sensorStopVerified':True,'journalArchived':True,'launchIntentArchived':True}
 raise RuntimeError('recovery deadline or connection lost')
