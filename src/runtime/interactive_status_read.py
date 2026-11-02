"""Bounded one-reply status read through the interactive Luna client.

Only three read-only status methods are allowed. The caller must interpret
errors (including GATT error 106) rather than treating them as disconnection.
"""
import json,os,selectors,subprocess,time
from borrowed_gatt_view import TARGET
BUS='luna://com.webos.service.bluetooth2/'
METHODS={'device/getStatus':{'subscribe':False},'hid/getStatus':{'address':TARGET,'subscribe':False},'gatt/getStatus':{'address':TARGET,'subscribe':False}}

def read_status(method,*,spawn=subprocess.Popen,clock=time.monotonic,timeout=3):
 if method not in METHODS or not callable(spawn) or not callable(clock) or type(timeout) not in (int,float) or not 0<timeout<=5:raise ValueError('invalid status request')
 argv=['/usr/bin/luna-send-pub','-i','-f',BUS+method,json.dumps(METHODS[method],separators=(',',':'))]
 p=None;sel=None;result=None;failure=None;stopped=False
 try:
  p=spawn(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True)
  if p.stdout is None or p.stderr is None:raise RuntimeError('missing status streams')
  sel=selectors.DefaultSelector()
  for fd,label in ((p.stdout,'out'),(p.stderr,'err')):
   os.set_blocking(fd.fileno(),False);sel.register(fd,selectors.EVENT_READ,label)
  deadline=clock()+timeout;last=deadline-timeout;out=bytearray();err=bytearray()
  while True:
   now=clock()
   if now<last or now>=deadline:raise TimeoutError('status reply timeout')
   last=now
   for key,_ in sel.select(min(.1,deadline-now)):
    try:chunk=os.read(key.fileobj.fileno(),4096)
    except BlockingIOError:continue
    if not chunk:sel.unregister(key.fileobj);continue
    buf=out if key.data=='out' else err;buf.extend(chunk)
    if len(out)>65536 or len(err)>4096:raise RuntimeError('status output limit')
   if out:
    try:
     text=out.decode('utf8');v,end=json.JSONDecoder().raw_decode(text.lstrip())
     if type(v) is not dict:raise RuntimeError('status response not object')
     if text.lstrip()[end:].strip():raise RuntimeError('multiple status replies')
     result=v;break
    except (UnicodeDecodeError,json.JSONDecodeError):pass
   if p.poll() is not None and not sel.get_map():raise RuntimeError('status exited without reply')
 except Exception as exc:failure=exc
 finally:
  if sel is not None:sel.close()
  if p is not None:
   try:
    if p.poll() is None:
     p.terminate()
     try:p.wait(timeout=1)
     except subprocess.TimeoutExpired:p.kill();p.wait(timeout=1)
    stopped=p.poll() is not None
   except (OSError,subprocess.TimeoutExpired):stopped=False
   for stream in (p.stdout,p.stderr):
    if stream is not None:stream.close()
 if not stopped:raise RuntimeError('status process stop unconfirmed') from failure
 if failure is not None:raise failure
 return result
