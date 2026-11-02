"""Offline adapter for direct status-based connection detection.

No sensor, connection request, pairing or input operations. Never installed.
"""
import subprocess,time
from connected_status_watch import ConnectedStatusWatch
from profile_subscription_pump import ProfileSubscriptionPump

class ConnectedStatusPump(ProfileSubscriptionPump):
 def __init__(self,*,poll,spawn=subprocess.Popen,clock=time.monotonic,ack_timeout=10):
  # Base tracker is replaced before any process/thread starts.
  super().__init__(generation=1,client_id='1',poll=poll,spawn=spawn,clock=clock,ack_timeout=ack_timeout)
  self.tracker=ConnectedStatusWatch(clock=clock)
 def _poll(self):
  deadline=self.clock()+self.ack_timeout
  while not self.stop_event.is_set():
   token=self.tracker.begin_poll()
   if token is not None:
    try:
     p=self.poll()
     if type(p) is not dict:self._fail();return
     self.tracker.commit_poll(token,p.get('hid'),p.get('gatt'))
     if not self.tracker.is_open():self._fail();return
    except Exception:self._fail();return
   elif self.clock()>=deadline:self._fail();return
   self.stop_event.wait(.1 if token is None else .5)
