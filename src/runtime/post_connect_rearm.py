"""Rearm gate for a completed finite connected-input session.

One live disconnected poll followed by a new connected poll is required; an
unknown or stale status is never considered a disconnect. This does not
launch, pair, connect, stop sensors, or demonstrate durable background
execution.
"""
class PostConnectRearm:
 def __init__(self,watch,*,generation,result):
  if (not callable(getattr(watch,'snapshot',None)) or not callable(getattr(watch,'disconnected_snapshot',None)) or type(generation) is not int or generation<=0 or type(result) is not dict or result.get('status')!='complete' or result.get('sensorStopVerified') is not True or result.get('journalArchived') is not True):raise ValueError('completed session evidence required')
  self.watch=watch;self.generation=generation;self.disconnected_generation=None;self.consumed=False
 def observe(self):
  if self.consumed:raise RuntimeError('rearm already consumed')
  if self.disconnected_generation is None:
   d=self.watch.disconnected_snapshot()
   if type(d) is dict and type(d.get('generation')) is int and d['generation']>self.generation:self.disconnected_generation=d['generation']
   return None
  c=self.watch.snapshot()
  if type(c) is not dict or type(c.get('generation')) is not int or c['generation']<self.disconnected_generation:return None
  self.consumed=True;return {'generation':c['generation'],'status':'eligible'}
