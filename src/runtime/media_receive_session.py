"""Experimental lifecycle composition; no automatic installation or startup."""
import runtime_bundle as bundle
from screen_power import ScreenPowerWorker
from media_toggle import PlaybackSnapshot,MediaAwareSink
from media_status_worker import MediaStatusWorker
from borrowed_sustained_receive import receive_sustained

class MediaResources:
 def __init__(self,system_key_sink,*,worker_factory=MediaStatusWorker,screen_factory=ScreenPowerWorker):
  self.snapshot=PlaybackSnapshot();self.worker=worker_factory(self.snapshot)
  self.sink=MediaAwareSink(system_key_sink,self.snapshot)
  self.screen=screen_factory() if bundle.active() else None
  self.worker_started=False;self.screen_started=False;self.closed=False
 def start(self):
  self.worker_started=True
  self.worker.start()
  if self.screen is not None:
   self.screen_started=True;self.screen.start()
 def close(self):
  if self.closed:return
  self.closed=True
  try:
   if self.screen_started and self.screen.stop() is not True:raise RuntimeError('screen-worker-stop-unconfirmed')
  finally:
   if self.worker_started and self.worker.stop() is not True:raise RuntimeError('media-worker-stop-unconfirmed')

def receive_with_media(session,outputs,fd,*,system_key_sink,worker_factory=MediaStatusWorker,receive=receive_sustained,screen_factory=ScreenPowerWorker,**kwargs):
 if not callable(getattr(system_key_sink,'pulse',None)) or not callable(worker_factory) or not callable(receive):raise ValueError('invalid dependencies')
 if 'system_key_emit' in kwargs:raise ValueError('duplicate emitter')
 resources=MediaResources(system_key_sink,worker_factory=worker_factory,screen_factory=screen_factory)
 try:
  resources.start()
  return receive(session,outputs,fd,system_key_emit=resources.sink.pulse,**({"screen_control":resources.screen} if resources.screen is not None else {}),**kwargs)
 finally:resources.close()
