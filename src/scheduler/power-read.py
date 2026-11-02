"""Read-only anonymous LS2 client capability probe; no service impersonation."""
import ctypes as C,json,time
class Error(C.Structure):
 _fields_=[('code',C.c_int),('message',C.c_char_p),('file',C.c_char_p),('line',C.c_int),('func',C.c_char_p),('padding',C.c_void_p),('magic',C.c_ulong)]
lib=C.CDLL('libluna-service2.so.3');glib=C.CDLL('libglib-2.0.so.0')
CB=C.CFUNCTYPE(C.c_bool,C.c_void_p,C.c_void_p,C.c_void_p)
def fn(name,restype,args):
 f=getattr(lib,name);f.restype=restype;f.argtypes=args;return f
init=fn('LSErrorInit',C.c_bool,[C.POINTER(Error)]);free=fn('LSErrorFree',None,[C.POINTER(Error)])
register=fn('LSRegister',C.c_bool,[C.c_char_p,C.POINTER(C.c_void_p),C.POINTER(Error)])
unregister=fn('LSUnregister',C.c_bool,[C.c_void_p,C.POINTER(Error)])
attach=fn('LSGmainContextAttach',C.c_bool,[C.c_void_p,C.c_void_p,C.POINTER(Error)])
call=fn('LSCallOneReply',C.c_bool,[C.c_void_p,C.c_char_p,C.c_char_p,CB,C.c_void_p,C.POINTER(C.c_ulong),C.POINTER(Error)])
cancel=fn('LSCallCancel',C.c_bool,[C.c_void_p,C.c_ulong,C.POINTER(Error)])
payload=fn('LSMessageGetPayload',C.c_char_p,[C.c_void_p])
glib.g_main_context_new.restype=C.c_void_p;glib.g_main_context_new.argtypes=[]
glib.g_main_context_iteration.restype=C.c_int;glib.g_main_context_iteration.argtypes=[C.c_void_p,C.c_int]
glib.g_main_context_unref.argtypes=[C.c_void_p];glib.g_main_context_unref.restype=None
error=Error();init(C.byref(error));handle=C.c_void_p();context=None;out={'anonymousClient':True,'writes':0,'replies':[]}
def checked(ok,stage):
 if not ok:
  out['failure']={'stage':stage,'code':error.code,'message':error.message.decode(errors='replace') if error.message else None}
  raise RuntimeError(stage)
try:
 checked(register(None,C.byref(handle),C.byref(error)),'register')
 context=glib.g_main_context_new();checked(attach(handle,context,C.byref(error)),'attach')
 for role in ('power',):
  replies=[]
  @CB
  def receive(sh,msg,data):
   try:replies.append(json.loads(payload(msg)))
   except Exception:replies.append({'invalidReply':True})
   return True
  token=C.c_ulong();checked(call(handle,b'luna://com.webos.service.tvpower/power/getPowerState',b'{"subscribe":false}',receive,None,C.byref(token),C.byref(error)),'call-'+role)
  deadline=time.monotonic()+3
  while not replies and time.monotonic()<deadline:
   glib.g_main_context_iteration(context,False);time.sleep(.005)
  if not replies:
   cancel(handle,token,C.byref(error));raise RuntimeError('reply-timeout')
  out['replies'].append({'role':role,'reply':replies[0]})
  if replies[0].get('returnValue') is not True:break
except Exception as exc:out['exception']=str(exc)
finally:
 if handle.value:out['unregistered']=bool(unregister(handle,C.byref(error)))
 if context:glib.g_main_context_unref(context)
 free(C.byref(error))
probe_result=out

reply=out['replies'][0]['reply'] if out.get('replies') else {}
result={'state':'Unavailable'}
if out.get('unregistered') is True and reply.get('returnValue') is True and type(reply.get('state')) is str:
 result={'state':reply['state']}
 if 'processing' in reply:result['processing']=reply['processing']
else:result['errorCode']=reply.get('errorCode');result['errorText']=str(reply.get('errorText',out.get('exception','unknown')))[:200]
print(json.dumps(result))
