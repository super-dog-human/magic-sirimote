"""Accept only an unchanged, fully connected or fully idle profile state.

This is point-in-time profile evidence, not exclusive ownership of the device.
No connection, sensor or GATT operation is sent here.
"""
import time

def make_check(*,profiles,valid,guard,wait=time.sleep,max_attempts=3):
 if not all(callable(x) for x in (profiles,valid,guard,wait)) or type(max_attempts) is not int or not 1<=max_attempts<=3:raise ValueError('invalid profile check')
 accepted=[None]
 def check():
  for i in range(max_attempts):
   if guard() is not True:return False
   try:
    data=profiles();states=[];unavailable=False
    for role in ('hid','gatt'):
     entry=data.get(role,{}) if type(data) is dict else {}
     reply=entry.get('reply') if type(entry) is dict else None
     if valid(reply) is not True:unavailable=True;continue
     if reply.get('connecting') is not False or reply.get('connectRequest') is not False:return False
     if type(reply.get('connected')) is not bool:return False
     states.append(reply['connected'])
   except Exception:unavailable=True
   if not unavailable:
    if len(states)!=2 or states[0]!=states[1]:return False
    state='connected' if states[0] else 'idle'
    if accepted[0] is not None and accepted[0]!=state:return False
    if guard() is not True:return False
    accepted[0]=state;return True
   if i+1<max_attempts:
    if guard() is not True:return False
    wait(.2)
  return False
 return check
