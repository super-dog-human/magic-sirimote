"""Experimental lifecycle composition; no automatic installation or startup."""
from media_toggle import PlaybackSnapshot,MediaAwareSink
from media_status_worker import MediaStatusWorker
from borrowed_sustained_receive import receive_sustained

def receive_with_media(session,outputs,fd,*,system_key_sink,worker_factory=MediaStatusWorker,receive=receive_sustained,**kwargs):
 if not callable(getattr(system_key_sink,'pulse',None)) or not callable(worker_factory) or not callable(receive):raise ValueError('invalid dependencies')
 if 'system_key_emit' in kwargs:raise ValueError('duplicate emitter')
 snapshot=PlaybackSnapshot();worker=worker_factory(snapshot);sink=MediaAwareSink(system_key_sink,snapshot)
 worker.start()
 try:
  return receive(session,outputs,fd,system_key_emit=sink.pulse,**kwargs)
 finally:
  if worker.stop() is not True:raise RuntimeError('media-worker-stop-unconfirmed')
