"""Read-only media polling for play/pause decisions.
"""
import json
import os
import selectors
import subprocess
import threading
import time

COMMAND=('/usr/bin/luna-send-pub','-i','-f',
         'luna://com.webos.media/getForegroundAppInfo','{"subscribe":false}')

class ChildUnreaped(RuntimeError):pass

def read_one(stop, *, command=COMMAND, timeout=2.0, max_bytes=16384):
 """Read one bounded reply, then always terminate and reap the exact child."""
 child=None;selector=None;data=bytearray();result=None
 try:
  child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,close_fds=True)
  selector=selectors.DefaultSelector();selector.register(child.stdout,selectors.EVENT_READ)
  deadline=time.monotonic()+timeout
  while not stop.is_set() and time.monotonic()<deadline:
   events=selector.select(min(.1,max(0.,deadline-time.monotonic())))
   if not events:
    if child.poll() is not None:break
    continue
   chunk=os.read(child.stdout.fileno(),min(4096,max_bytes+1-len(data)))
   if not chunk:break
   data.extend(chunk)
   if len(data)>max_bytes:break
   try:
    parsed,end=json.JSONDecoder().raw_decode(data.decode('utf-8').lstrip())
    if type(parsed) is dict:result=parsed
    break
   except (UnicodeDecodeError,json.JSONDecodeError):pass
 except (OSError,ValueError):pass
 finally:
  if selector is not None:selector.close()
  if child is not None:
   if child.poll() is None:
    try:child.terminate()
    except ProcessLookupError:pass
   try:
    try:child.wait(timeout=.5)
    except subprocess.TimeoutExpired:
     try:child.kill()
     except ProcessLookupError:pass
     try:child.wait(timeout=1)
     except subprocess.TimeoutExpired:raise ChildUnreaped('media query child not reaped')
   finally:
    if child.stdout is not None:child.stdout.close()
 return result if not stop.is_set() else None

class MediaStatusWorker:
 def __init__(self,snapshot,*,interval=1.0,query=read_one):
  if not callable(getattr(snapshot,'update',None)) or not callable(getattr(snapshot,'ticket',None)) or not callable(query) or not .1<=interval<=60:raise ValueError('invalid worker')
  self.snapshot=snapshot;self.interval=interval;self.query=query;self.stop_event=threading.Event();self.thread=None;self.child_unreaped=False
 def start(self):
  if self.thread is not None:raise RuntimeError('already started')
  self.thread=threading.Thread(target=self._run,name='media-status',daemon=True);self.thread.start()
 def _run(self):
  try:
   while not self.stop_event.is_set():
    ticket=self.snapshot.ticket()
    try:reply=self.query(self.stop_event)
    except ChildUnreaped:
     self.child_unreaped=True;self.stop_event.set();break
    except Exception:reply=None
    self.snapshot.update(reply,ticket=ticket)
    if self.stop_event.wait(self.interval):break
  finally:self.snapshot.update(None)
 def stop(self,timeout=4.0):
  self.stop_event.set()
  if self.thread is None:return True
  self.thread.join(timeout)
  return not self.thread.is_alive() and not self.child_unreaped
