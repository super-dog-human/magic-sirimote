"""Adapter for direct status-based connection detection.

Performs status reads only, without pairing, sensor or input operations.
"""
import subprocess,threading,time
from connected_status_watch import ConnectedStatusWatch
from profile_subscription_pump import ProfileSubscriptionPump

class ConnectedStatusPump(ProfileSubscriptionPump):
 def __init__(self,*,poll,spawn=subprocess.Popen,clock=time.monotonic,ack_timeout=10):
  # Base tracker is replaced before any process/thread starts.
  super().__init__(generation=1,client_id='1',poll=poll,spawn=spawn,clock=clock,ack_timeout=ack_timeout)
  self.tracker=ConnectedStatusWatch(clock=clock)
  self.poll_event=threading.Event()
 def _wake_poll(self):self.poll_event.set()
 def _wait_poll(self,delay):
  # Coalesce notifications and cap reads at ten per second, even during an
  # event burst. Stop interrupts both waits; notifications interrupt only the
  # remaining steady-state delay. They never substitute for a fresh poll.
  if self.stop_event.wait(min(.1,delay)):return
  if delay>.1:self.poll_event.wait(delay-.1)
 def _poll(self):
  started=self.clock();deadline=started+self.ack_timeout
  burst_until=started+2;connected_generation=None
  while not self.stop_event.is_set():
   self.poll_event.clear()
   token=self.tracker.begin_poll()
   if token is not None:
    try:
     p=self.poll()
     if type(p) is not dict:self._fail();return
     self.tracker.commit_poll(token,p.get('hid'),p.get('gatt'))
     if not self.tracker.is_open():self._fail();return
     current=self.tracker.snapshot()
     if current is not None and current['generation']!=connected_generation:
      connected_generation=current['generation'];burst_until=self.clock()+2
    except Exception:self._fail();return
   elif self.clock()>=deadline:self._fail();return
   # Sample more often just after connection changes. The required stable
   # observation span is unchanged; normal steady-state polling stays slow.
   self._wait_poll(.1 if token is None or self.clock()<burst_until else .5)
