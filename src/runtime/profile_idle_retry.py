"""Bounded read-only rechecks of temporarily unavailable profile status."""
import time

def idle(*,profiles,valid,guard,wait=time.sleep,max_attempts=3):
 if not all(callable(x) for x in (profiles,valid,guard,wait)) or type(max_attempts) is not int or not 1<=max_attempts<=3:raise ValueError('invalid profile check')
 for i in range(max_attempts):
  if guard() is not True:return False
  try:
   result=profiles();unavailable=False
   for role in ('hid','gatt'):
    entry=result.get(role,{}) if type(result) is dict else {}
    reply=entry.get('reply') if type(entry) is dict else None
    if valid(reply) is not True:unavailable=True;continue
    if any(reply.get(k) is not False for k in ('connected','connecting','connectRequest')):return False
  except Exception:unavailable=True
  if not unavailable:return guard() is True
  if i+1<max_attempts:
   if guard() is not True:return False
   wait(.2)
 return False
