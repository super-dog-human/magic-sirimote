"""Offline two-application owner repair workflow for one retained run.

Caller is responsible for pinning the application package and proving no
competing app processes. This function changes modes only, not file content,
sensor state, Bluetooth state, or launch records.
"""
import os,re
from repair import repair

def run(role,plan,*,controller_state,receiver_state,journal_state,guard,apply=False,repair_fn=repair,owner=None,group=5000,state_uid=5999):
 if role not in ('controller','receiver') or type(plan) is not dict or type(plan.get('run')) is not str or re.fullmatch('[0-9a-f]{32}',plan['run']) is None or type(apply) is not bool or not callable(guard) or not callable(repair_fn):raise ValueError('invalid owner workflow')
 owner=os.getuid() if owner is None else owner
 if role=='controller':targets=((controller_state,'controllerState',state_uid),(receiver_state,'receiverControllerOwned',state_uid))
 else:targets=((receiver_state,'receiverOwned',state_uid),(journal_state,'receiverJournal',owner))
 def checked(path,key,dir_uid,mutate):
  if guard() is not True:raise RuntimeError('repair guard unavailable')
  result=repair_fn(path,plan[key],owner=owner,group=group,expected_directory_owner=dir_uid,apply=mutate)
  if type(result) is not dict or result.get('status')!=('repaired' if mutate else 'validated') or result.get('count')!=len(plan[key]):raise RuntimeError('repair result unconfirmed')
 for path,key,uid in targets:checked(path,key,uid,False)
 if apply:
  for path,key,uid in targets:checked(path,key,uid,True)
  for path,key,uid in targets:checked(path,key,uid,False)
 return {'status':'repaired' if apply else 'validated','role':role,'run':plan['run'],'sensorState':'unverified'}
