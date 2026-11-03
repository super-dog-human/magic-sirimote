"""Screen-only power control on a separate worker; no I/O on import.

Input must be paused and drained before toggle() is called. A fresh TV state
selects each command; uncertain writes are observed, never automatically replayed.
"""
import ctypes as C
import json
import threading
import time

class ScreenPowerClient:
 def __init__(self,stop):
  self.stop=stop;self.handle=C.c_void_p();self.context=None
  class Error(C.Structure):
   _fields_=[('code',C.c_int),('message',C.c_char_p),('file',C.c_char_p),('line',C.c_int),('func',C.c_char_p),('padding',C.c_void_p),('magic',C.c_ulong)]
  self.lib=C.CDLL('libluna-service2.so.3');self.glib=C.CDLL('libglib-2.0.so.0');self.callback=C.CFUNCTYPE(C.c_bool,C.c_void_p,C.c_void_p,C.c_void_p);self.error=Error()
  def fn(lib,name,result,args):
   f=getattr(lib,name);f.restype=result;f.argtypes=args;return f
  ep=C.POINTER(Error)
  self.init=fn(self.lib,'LSErrorInit',C.c_bool,[ep]);self.free=fn(self.lib,'LSErrorFree',None,[ep])
  self.register=fn(self.lib,'LSRegister',C.c_bool,[C.c_char_p,C.POINTER(C.c_void_p),ep]);self.unregister=fn(self.lib,'LSUnregister',C.c_bool,[C.c_void_p,ep])
  self.attach=fn(self.lib,'LSGmainContextAttach',C.c_bool,[C.c_void_p,C.c_void_p,ep])
  self.send=fn(self.lib,'LSCallOneReply',C.c_bool,[C.c_void_p,C.c_char_p,C.c_char_p,self.callback,C.c_void_p,C.POINTER(C.c_ulong),ep]);self.cancel=fn(self.lib,'LSCallCancel',C.c_bool,[C.c_void_p,C.c_ulong,ep])
  self.payload=fn(self.lib,'LSMessageGetPayload',C.c_char_p,[C.c_void_p])
  self.new=fn(self.glib,'g_main_context_new',C.c_void_p,[]);self.iterate=fn(self.glib,'g_main_context_iteration',C.c_int,[C.c_void_p,C.c_int]);self.unref=fn(self.glib,'g_main_context_unref',None,[C.c_void_p])
  self.init(C.byref(self.error))
  try:
   if not self.register(None,C.byref(self.handle),C.byref(self.error)):raise RuntimeError('screen client registration failed')
   self.context=self.new()
   if not self.attach(self.handle,self.context,C.byref(self.error)):raise RuntimeError('screen client attach failed')
  except BaseException:self.close();raise
 def call(self,method):
  if method not in ('getPowerState','turnOffScreen','turnOnScreen'):raise ValueError('screen method not allowed')
  if self.stop.is_set():return None
  replies=[]
  @self.callback
  def receive(_handle,message,_data):
   try:
    raw=self.payload(message)
    if raw is not None and len(raw)<=4096:
     value=json.loads(raw)
     if type(value) is dict:replies.append(value)
   except Exception:replies.append(None)
   return True
  token=C.c_ulong();params={'subscribe':False} if method=='getPowerState' else {'standbyMode':'active'}
  uri=('luna://com.webos.service.tvpower/power/'+method).encode()
  if not self.send(self.handle,uri,json.dumps(params).encode(),receive,None,C.byref(token),C.byref(self.error)):return None
  deadline=time.monotonic()+2
  while not replies and not self.stop.is_set() and time.monotonic()<deadline:
   self.iterate(self.context,False);self.stop.wait(.005)
  if not replies:self.cancel(self.handle,token,C.byref(self.error))
  return replies[0] if replies else None
 def close(self):
  if self.handle.value:self.unregister(self.handle,C.byref(self.error));self.handle=C.c_void_p()
  if self.context:self.unref(self.context);self.context=None
  self.free(C.byref(self.error))

class ScreenPowerWorker:
 def __init__(self,*,client_factory=ScreenPowerClient,clock=time.monotonic,interval=.5):
  if not callable(client_factory) or not callable(clock) or not .1<=interval<=5:raise ValueError('invalid screen worker')
  self.factory=client_factory;self.clock=clock;self.interval=interval
  self.lock=threading.Lock();self.stop_event=threading.Event();self.wake=threading.Event();self.thread=None
  self.state=None;self.sampled=None;self.pending=False;self.requested=False
 def blocked(self):
  with self.lock:
   return self.pending or self.state!='Active' or self.sampled is None or not 0<=self.clock()-self.sampled<=3
 def toggle(self):
  with self.lock:
   if self.pending or self.stop_event.is_set():return False
   self.pending=True;self.requested=True
  self.wake.set();return True
 def start(self):
  if self.thread is not None:raise RuntimeError('screen worker already started')
  self.thread=threading.Thread(target=self._run,name='screen-power',daemon=True);self.thread.start()
 def _state(self,reply):
  if type(reply) is dict and reply.get('returnValue') is True and reply.get('processing','')=='':
   state=reply.get('state')
   if state in ('Active','Screen Off'):return state
  return None
 def _step(self,client):
  with self.lock:
   requested=self.requested;self.requested=False
  # No output can resume while a toggle is in flight, even when this read
  # observes Active before the subsequent screen-off write.
  state=self._state(client.call('getPowerState'))
  if requested and not self.stop_event.is_set():
   method={'Active':'turnOffScreen','Screen Off':'turnOnScreen'}.get(state)
   if method is not None:
    client.call(method)  # one attempt for this physical press
    state=self._state(client.call('getPowerState'))
  with self.lock:
   self.state=state;self.sampled=self.clock()
   if requested:self.pending=False
 def _run(self):
  client=None
  try:
   client=self.factory(self.stop_event)
   while not self.stop_event.is_set():
    self.wake.clear()
    self._step(client)
    # A request arriving during a read must not wait behind the polling timer.
    with self.lock:queued=self.requested
    if not queued:self.wake.wait(self.interval)
  except Exception:
   with self.lock:self.state=None;self.sampled=None
  finally:
   if client is not None:client.close()
 def stop(self,timeout=4):
  self.stop_event.set();self.wake.set()
  if self.thread is not None:self.thread.join(timeout)
  return self.thread is None or not self.thread.is_alive()
