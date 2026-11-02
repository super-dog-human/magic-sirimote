"""One bounded interactive Luna request; no retry or device policy here.

The caller must validate the exact method and arguments before dispatch and
must journal a potentially mutating request before calling this function.
After any spawn or timeout error the delivery outcome remains unknown.
"""
import json,os,selectors,subprocess,time

def _unique(pairs):
 out={}
 for k,v in pairs:
  if k in out:raise RuntimeError('duplicate JSON key')
  out[k]=v
 return out

def call(uri,params,*,timeout,spawn=subprocess.Popen,clock=time.monotonic):
 if uri!='luna://org.codex.siriremote.v20scheduler20261031a.service/receiverPin' or params!={} or type(timeout) not in (int,float) or not 0<timeout<=35 or not callable(spawn) or not callable(clock):raise ValueError('invalid bounded call')
 payload=json.dumps(params,separators=(',',':'));p=None;selector=None;failure=None;result=None;stopped=False
 try:
  p=spawn(['/usr/bin/luna-send-pub','-i','-f',uri,payload],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True)
  if p.stdout is None or p.stderr is None:raise RuntimeError('missing streams')
  selector=selectors.DefaultSelector()
  for f,label in ((p.stdout,'out'),(p.stderr,'err')):os.set_blocking(f.fileno(),False);selector.register(f,selectors.EVENT_READ,label)
  end=clock()+timeout;last=end-timeout;out=bytearray();err=bytearray()
  while True:
   now=clock()
   if now<last or now>=end:raise TimeoutError('reply unknown')
   last=now
   for key,_ in selector.select(min(.1,end-now)):
    try:chunk=os.read(key.fileobj.fileno(),4096)
    except BlockingIOError:continue
    if not chunk:selector.unregister(key.fileobj);continue
    target=out if key.data=='out' else err;target.extend(chunk)
    if len(out)>65536 or len(err)>4096:raise RuntimeError('output limit')
   if out:
    try:
     text=out.decode('utf8');v,n=json.JSONDecoder(object_pairs_hook=_unique).raw_decode(text.lstrip())
     if type(v) is not dict or text.lstrip()[n:].strip():raise RuntimeError('invalid reply')
     result=v;break
    except (UnicodeDecodeError,json.JSONDecodeError):pass
   if p.poll() is not None and not selector.get_map():raise RuntimeError('reply unavailable')
 except Exception as exc:failure=exc
 finally:
  if selector is not None:selector.close()
  if p is not None:
   try:
    if p.poll() is None:
     p.terminate()
     try:p.wait(timeout=1)
     except subprocess.TimeoutExpired:p.kill();p.wait(timeout=1)
    stopped=p.poll() is not None
   except (OSError,subprocess.TimeoutExpired):stopped=False
   for f in (p.stdout,p.stderr):
    if f is not None:f.close()
 if not stopped:raise RuntimeError('request process exit unconfirmed') from failure
 if failure is not None:raise failure
 return result
