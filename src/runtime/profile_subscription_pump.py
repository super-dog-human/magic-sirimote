"""Subscription/poll adapter for connection status.

Only status subscriptions and reads are requested. Loss of either stream
invalidates the generation. The supplied poll must be bounded by its caller.
"""
import codecs,json,math,os,selectors,subprocess,threading,time
from profile_continuity import ProfileContinuity,TARGET
from scan_wake_provider import JsonObjects
import tv_bluetooth

def bounded_profile_poll(invoke=subprocess.Popen):
 wrapped=tv_bluetooth.profiles(invoke);out={}
 for role in ('hid','gatt'):
  item=wrapped.get(role) if type(wrapped) is dict else None
  if type(item) is not dict or item.get('returncode')!=0 or type(item.get('reply')) is not dict:raise RuntimeError('profile-poll-unavailable')
  out[role]=item['reply']
 return out

class ProfileSubscriptionPump:
 def __init__(self,*,generation,client_id,poll,spawn=subprocess.Popen,clock=time.monotonic,ack_timeout=10):
  if not callable(poll) or not callable(spawn) or type(ack_timeout) not in (int,float) or not 0<ack_timeout<=30:raise ValueError('invalid pump dependencies')
  self.tracker=ProfileContinuity(generation=generation,client_id=client_id,clock=clock)
  self.poll=poll;self.spawn=spawn;self.clock=clock;self.ack_timeout=ack_timeout;self.stop_event=threading.Event();self.children=[];self.threads=[]
 def start(self):
  if self.children or self.threads:raise RuntimeError('pump already started')
  try:
   for role in ('hid','gatt'):
    args=['/usr/bin/luna-send-pub','-i','-f','luna://com.webos.service.bluetooth2/'+role+'/getStatus',json.dumps({'address':TARGET,'subscribe':True},separators=(',',':'))]
    self.children.append((role,self.spawn(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,close_fds=True)))
   self.threads=[threading.Thread(target=self._events,daemon=True),threading.Thread(target=self._poll,daemon=True)]
   for thread in self.threads:thread.start()
  except BaseException:self.stop();raise
 def _fail(self):self.tracker.close();self.stop_event.set()
 def _events(self):
  try:
   with selectors.DefaultSelector() as selector:
    parsers={};decoders={};windows={}
    for role,child in self.children:
     if child.stdout is None:raise RuntimeError('missing stream')
     selector.register(child.stdout,selectors.EVENT_READ,role);parsers[role]=JsonObjects();decoders[role]=codecs.getincrementaldecoder('utf-8')();windows[role]=[self.clock(),0]
    while not self.stop_event.is_set():
     for key,_ in selector.select(.25):
      role=key.data;raw=os.read(key.fileobj.fileno(),4096)
      if not raw:raise RuntimeError('subscription ended')
      now=self.clock();start,count=windows[role]
      if type(now) not in (int,float) or not math.isfinite(now) or now<start:raise RuntimeError('invalid subscription clock')
      if now-start>=60:start,count=now,0
      count+=len(raw);windows[role]=[start,count]
      if count>1_048_576:raise RuntimeError('subscription rate limit')
      for obj in parsers[role].feed(decoders[role].decode(raw)):
       if not self.tracker.event(role,obj):raise RuntimeError('subscription invalid')
  except Exception:self._fail()
 def _poll(self):
  deadline=self.clock()+self.ack_timeout
  while not self.stop_event.is_set():
   if self.tracker.acknowledged():
    try:
     p=self.poll()
     if type(p) is not dict or not self.tracker.poll(p.get('hid'),p.get('gatt')):self._fail();return
    except Exception:self._fail();return
   elif self.clock()>=deadline:self._fail();return
   self.stop_event.wait(.1 if not self.tracker.acknowledged() else 1)
 def snapshot(self):return None if self.stop_event.is_set() else self.tracker.snapshot()
 def stop(self,timeout=5):
  self.stop_event.set();self.tracker.close();ok=True
  for _,child in self.children:
   if child.poll() is None:
    try:child.terminate();child.wait(timeout=1)
    except subprocess.TimeoutExpired:
     child.kill()
     try:child.wait(timeout=1)
     except subprocess.TimeoutExpired:ok=False
    except OSError:ok=False
   if child.stdout is not None:child.stdout.close()
  for thread in self.threads:
   if thread.ident is not None:thread.join(timeout)
   if thread.is_alive():ok=False
  return ok
