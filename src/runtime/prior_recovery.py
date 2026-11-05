"""Authenticate a prior run without inventing an outcome after a crash."""
from pathlib import Path
from receiver_result_reader import read_receipt,read_start
from borrowed_runtime_journal import inspect_journal
import os,re

def prior_run(directory,run,*,expected_process=None,state_uid=5999,group=5000):
 try:
  receipt=read_receipt(directory,run,state_uid=state_uid,group=group,historical=True)
 except FileNotFoundError:
  # Only genuine absence is recoverable; malformed/foreign receipts fail.
  start=read_start(directory,run,state_uid=state_uid,group=group,historical=True)
  process=start['process'];outcome='unknown'
 else:
  if receipt.get('status')!='attention':raise RuntimeError('prior outcome not recoverable')
  process=receipt['process'];outcome='attention'
 if expected_process is not None and process!=expected_process:raise RuntimeError('prior process identity differs')
 uids=process['status']['Uid'].split()
 if len(uids)!=4 or len(set(uids))!=1 or not uids[0].isdecimal() or int(uids[0])<=0:raise RuntimeError('prior UID invalid')
 owner=int(uids[0])
 d=os.open(Path(directory)/'borrowed-active',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  names=os.listdir(d)
  if not names or any(not re.fullmatch('borrowed-'+run+r'-[0-9]{2,4}\.json',name) for name in names):raise RuntimeError('foreign or empty prior journal')
 finally:os.close(d)
 # Journal reader independently enforces exact run, file owner/group/modes,
 # directory owner and ordered lifecycle records. No zero is inferred.
 evidence=inspect_journal(Path(directory)/'borrowed-active',run,owner_uid=owner,state_uid=owner,group=group,historical=True)
 if evidence.get('status') not in ('sensor-state-unknown','zero-recorded-live-recheck-required','no-sensor-enable-recorded','input-start-recorded-sensor-not-attempted'):raise RuntimeError('prior uncertain sensor journal unavailable')
 return {'process':process,'priorOutcome':outcome,'journalEvidence':evidence}
