"""Prepare a separate authenticated recovery-controller record.

Offline candidate. No Bluetooth, input, receiver launch or cleanup is done
here. The original controller record is preserved for orphan reconciliation.
"""
import os,re
from pathlib import Path
from controller_start_record import read_record,write_record
from prior_recovery import prior_run
from orphan_reconcile import _ended,_read,_identity
import receiver_package_attestation as package
from receiver_result_receipt import _process_identity

def _lease_for(lease,controller_state):
 if lease.held() is not True or type(getattr(lease,'dirfd',None)) is not int:return False
 fd=os.open(Path(controller_state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  a=os.fstat(fd);b=os.fstat(lease.dirfd)
  return (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino) and lease.held() is True
 finally:os.close(fd)

def _context(*,run,controller_state,receiver_state,controller_app,receiver_app,receiver_package,pin,lease,state_uid=5999,group=5000):
 if type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('invalid run')
 if not _lease_for(lease,controller_state):raise RuntimeError('supervisor lease required')
 intent,intent_stat=_read(lease.dirfd,'receiver-launch-intent.json',os.getuid(),group,0o640,historical=True)
 if (set(intent)!={'run','stage','generation'} or intent.get('run')!=run or
     intent.get('stage')!='receiver-launch-intent' or type(intent.get('generation')) is not int or intent['generation']<1):
  raise RuntimeError('prior launch intent invalid')
 old=read_record(receiver_state,run,state_uid=state_uid,group=group,historical=True)
 if old['process']['status'].get('Uid','').split()!=[str(os.getuid())]*4:raise RuntimeError('prior controller owner changed')
 current=_process_identity()
 if current['pid']!=os.getpid() or current==old['process']:raise RuntimeError('new controller identity invalid')
 prior=prior_run(receiver_state,run,state_uid=state_uid,group=group)
 if not _ended(prior['process'],receiver_app):raise RuntimeError('prior receiver still present or unverified')
 def same_intent():
  value,info=_read(lease.dirfd,'receiver-launch-intent.json',os.getuid(),group,0o640,historical=True)
  return value==intent and _identity(info)==_identity(intent_stat)
 def proof():
  return (_lease_for(lease,controller_state) and
   package.package_matches(receiver_app,receiver_package,pin) is True and
   _ended(old['process'],controller_app,ignore_current=True) and
   _ended(prior['process'],receiver_app) and
   same_intent() and
   read_record(receiver_state,run,state_uid=state_uid,group=group,historical=True)==old and
   _process_identity()==current)
 if not proof():raise RuntimeError('takeover proof unavailable')
 for name in ('recovery-controller-start.json','recovery-request.json',
              'receiver-recovery-start-'+run+'.json','receiver-recovery-result-'+run+'.json',
              'recovery-'+run+'-1.json'):
  try:os.lstat(Path(receiver_state)/name)
  except FileNotFoundError:pass
  else:raise RuntimeError('previous recovery attempt retained')
 if not proof():raise RuntimeError('takeover proof changed')
 return proof,prior,current

def inspect(**context):
 """Check eligibility without changing files or connecting to the target."""
 proof,prior,_=_context(**context)
 if not proof():raise RuntimeError('takeover proof changed')
 return {'status':'eligible','run':context['run'],'priorOutcome':prior['priorOutcome']}

def prepare(**context):
 proof,prior,current=_context(**context)
 run=context['run'];receiver_state=context['receiver_state']
 ownership={k:context[k] for k in ('state_uid','group') if k in context}
 write_record(receiver_state,run,current,name='recovery-controller-start.json',**ownership)
 # An uncertainty after publication is retained; never remove or overwrite it.
 if not proof() or read_record(receiver_state,run,name='recovery-controller-start.json',**ownership)['process']!=current:
  raise RuntimeError('published takeover unconfirmed')
 return {'status':'prepared','run':run,'priorOutcome':prior['priorOutcome'],'priorProcess':prior['process'],'requestCreated':False,'receiverLaunched':False}
