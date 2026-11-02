"""Scoped scan provider; not enabled until scan-stop proof is implemented.

Uses a target-filtered subscription and never stores raw advertisements. Child
exit alone is not proof that the TV's radio scan stopped; the caller must
independently supply a trustworthy stop check before a wake can be returned.
"""
import codecs,json,os,selectors,subprocess,time
from target_scan_wake import TargetScanWake,TARGET
from preflight_errors import PreflightUnsafe

class JsonObjects:
 def __init__(self):self.buf='';self.decoder=json.JSONDecoder(object_pairs_hook=self._unique)
 @staticmethod
 def _unique(pairs):
  d={}
  for k,v in pairs:
   if k in d:raise ValueError('duplicate JSON field')
   d[k]=v
  return d
 def feed(self,text):
  self.buf+=text
  if len(self.buf)>32768:raise ValueError('scan buffer limit')
  result=[]
  while True:
   self.buf=self.buf.lstrip()
   if not self.buf:return result
   try:value,end=self.decoder.raw_decode(self.buf)
   except json.JSONDecodeError:
    if len(self.buf)>16384:raise ValueError('scan object limit')
    return result
   if end>16384 or type(value) is not dict:raise ValueError('invalid scan message')
   result.append(value);self.buf=self.buf[end:]

def observe_once(*,verify_scan_stopped,popen=subprocess.Popen,clock=time.monotonic,max_seconds=180):
 if not callable(verify_scan_stopped) or type(max_seconds) not in (int,float) or not 0<max_seconds<=180:raise ValueError('invalid scan configuration')
 gate=TargetScanWake(clock=clock);parser=JsonObjects();decoder=codecs.getincrementaldecoder('utf-8')();child=None;seen=False;total=0;exited=False
 try:
  child=popen(['/usr/bin/luna-send-pub','-i','-f','luna://com.webos.service.bluetooth2/le/startScan',json.dumps({'address':TARGET,'subscribe':True},separators=(',',':'))],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,close_fds=True)
  with selectors.DefaultSelector() as selector:
   selector.register(child.stdout,selectors.EVENT_READ);deadline=clock()+max_seconds
   while clock()<deadline and not seen:
    if child.poll() is not None:raise RuntimeError('scan stream exited')
    if not selector.select(min(.5,max(0,deadline-clock()))):continue
    chunk=os.read(child.stdout.fileno(),4096)
    if not chunk:raise RuntimeError('scan stream ended')
    total+=len(chunk)
    if total>262144:raise RuntimeError('scan stream limit')
    for msg in parser.feed(decoder.decode(chunk)):
     if gate.accept(msg):seen=True
     if gate.closed:raise RuntimeError('scan rejected')
 finally:
  if child is not None:
   try:
    if child.poll() is None:
     child.terminate()
     try:child.wait(timeout=2)
     except subprocess.TimeoutExpired:
      child.kill()
      try:child.wait(timeout=2)
      except subprocess.TimeoutExpired:pass
    exited=child.poll() is not None
   finally:
    if child.stdout is not None:child.stdout.close()
    # This gate must also run on malformed data, unexpected EOF and timeout.
    # Otherwise a failed scan could be followed by a new operation while the
    # server-side subscription is still active.
    if not exited:raise PreflightUnsafe('scan-stop-unverified')
    try:stopped=verify_scan_stopped() is True
    except Exception as exc:raise PreflightUnsafe('scan-stop-unverified') from exc
    if not stopped:raise PreflightUnsafe('scan-stop-unverified')
 return gate.consume() if seen else False
