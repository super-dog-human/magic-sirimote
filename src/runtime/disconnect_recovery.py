"""Offline recovery gate; injected bounded device adapters only, no TV calls.

The old receipt remains attention. A separate recovery record permits a new
session only after old process exit, a newly acquired cooperative Feature lease,
and readback on the exact reconnected generation. This grants no connection or
enable authority and makes no claim about arbitrary TV Feature users.
"""
import re

class DisconnectRecovery:
 def __init__(self, *, run, generation, watch, old_receiver_exited,
              acquire_feature_lease, read_mode, disable_mode, record):
  if (type(run) is not str or not re.fullmatch('[a-f0-9]{32}', run)
      or type(generation) is not int or generation < 1
      or not callable(getattr(watch, 'snapshot', None))
      or not callable(getattr(watch, 'disconnected_snapshot', None))
      or not all(callable(f) for f in (old_receiver_exited, acquire_feature_lease,
                                     read_mode, disable_mode, record))):
   raise ValueError('exact prior run and recovery dependencies required')
  self.run=run; self.generation=generation; self.watch=watch
  self.exited=old_receiver_exited; self.acquire=acquire_feature_lease
  self.read=read_mode; self.disable=disable_mode; self.record=record
  self.disconnected=None; self.attempted=False; self.done=False
 def observe(self):
  if self.done or self.attempted:raise RuntimeError('recovery already consumed')
  d=self.watch.disconnected_snapshot()
  if type(d) is dict and type(d.get('generation')) is int and d['generation']>self.generation:
   self.disconnected=d['generation']
  if self.disconnected is None:return None
  c=self.watch.snapshot()
  if type(c) is not dict or type(c.get('generation')) is not int or c['generation']<self.disconnected:return None
  if self.exited() is not True:return None
  # Acquisition must actually obtain a fresh lock; process exit alone is never
  # treated as proof that the old Feature lease was released.
  lease=self.acquire()
  if lease is None:return None
  self.attempted=True
  gen=c['generation']
  def valid():
   now=self.watch.snapshot()
   return (self.exited() is True and lease.held() is True and
           type(now) is dict and now.get('generation')==gen)
  evidence={'run':self.run,'priorGeneration':self.generation,
            'reconnectedGeneration':gen,'priorSensorState':'uncertain',
            'featureExclusivity':'cooperative-only-unproven'}
  try:
   if not valid():raise RuntimeError('recovery control unavailable')
   if self.record({**evidence,'stage':'recovery-intent'}) is not True:raise RuntimeError('recovery intent unrecorded')
   mode=self.read(gen, valid, timeout=6)
   if type(mode) is not int or mode not in (0,1) or not valid():raise RuntimeError('recovery baseline unverified')
   if mode==1:
    # Acknowledgement alone is insufficient; readback decides success.
    self.disable(gen, valid, timeout=6)
    if not valid():raise RuntimeError('recovery connection lost')
    mode=self.read(gen, valid, timeout=6)
   if type(mode) is not int or mode!=0 or not valid():raise RuntimeError('recovery zero unverified')
   result={**evidence,'stage':'recovery-zero-confirmed','modeZeroVerified':True,
           'oldReceiverExitVerified':True,'priorReceiptStatus':'attention',
           'status':'recovered','generation':gen}
   if self.record(result) is not True:raise RuntimeError('recovery proof unrecorded')
   self.done=True
   return result
  finally:lease.close()
