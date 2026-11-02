"""Offline composition of a saved receiver result and launch completion.

The caller supplies an independent verifier for exact app/package/process exit.
A receipt alone is self-reported and never establishes that verifier.
"""
from receiver_result_reader import read_receipt

def complete(intent,*,receiver_state,run,independent_verifier,read=read_receipt):
 if not callable(independent_verifier) or not callable(read) or not callable(getattr(intent,'archive_completed',None)):raise ValueError('invalid completion dependencies')
 receipt=read(receiver_state,run)
 if type(receipt) is not dict or receipt.get('run')!=run or receipt.get('status')!='complete' or receipt.get('sensorStopVerified') is not True or receipt.get('journalArchived') is not True:raise RuntimeError('receiver completion not established')
 def proof():return independent_verifier(receipt) is True
 if intent.archive_completed(receipt,independent_proof=proof) is not True:raise RuntimeError('launch archive not confirmed')
 return {'run':run,'status':'complete','sensorStopVerified':True,'journalArchived':True,'launchIntentArchived':True}
