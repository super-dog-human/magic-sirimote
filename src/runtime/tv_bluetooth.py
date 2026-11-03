"""Read-only prelaunch Bluetooth snapshot for a TV-local coordinator."""
from runtime_device import identity as device_identity
import subprocess
from interactive_status_read import read_status
TARGET=device_identity().remote;ADAPTER=device_identity().adapter;NAME=device_identity().name
BUS='luna://com.webos.service.bluetooth2/'
def _call(method,params,invoke):
 if method not in ('device/getStatus','hid/getStatus','gatt/getStatus'):raise ValueError('not read-only')
 expected={'subscribe':False} if method=='device/getStatus' else {'address':TARGET}
 if type(params) is not dict or params!=expected:raise ValueError('unexpected target')
 try:
  return read_status(method,spawn=invoke,timeout=3)
 except (OSError,subprocess.TimeoutExpired,RuntimeError,TimeoutError,ValueError,TypeError):return None
def profiles(invoke=subprocess.Popen):
 out={}
 for role in ('hid','gatt'):
  r=_call(role+'/getStatus',{'address':TARGET},invoke)
  out[role]={'returncode':0,'reply':r} if r is not None else {'returncode':None,'reply':None}
 return out
def preflight(invoke=subprocess.Popen):
 d=_call('device/getStatus',{'subscribe':False},invoke);lst=d.get('devices') if isinstance(d,dict) and d.get('returnValue') is True else None
 items=[x for x in lst if isinstance(x,dict) and str(x.get('address','')).lower()==TARGET and x.get('name')==NAME] if isinstance(lst,list) else []
 if len(items)!=1:return False
 x=items[0]
 if x.get('paired') is not True or x.get('blocked') is not False or x.get('pairing') is not False or x.get('connectedProfiles')!=['gatt']:return False
 p=profiles(invoke)
 for role,connected in (('hid',False),('gatt',True)):
  r=p[role]['reply']
  if not isinstance(r,dict) or r.get('returnValue') is not True or str(r.get('address','')).lower()!=TARGET or str(r.get('adapterAddress','')).lower()!=ADAPTER or r.get('connected') is not connected or r.get('connecting') is not False or r.get('connectRequest') is not False:return False
 return True
