import sys,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
from connected_status_pump import ConnectedStatusPump
from controller_status_watch import ResumingControllerWatch
from borrowed_gatt_view import TARGET,ADAPTER

def profile(connected=True):
 return dict(returnValue=True,address=TARGET,adapterAddress=ADAPTER,connected=connected,connecting=False,connectRequest=False)

class Tests(unittest.TestCase):
 def test_event_wakes_wait_but_cannot_create_fresh_connection_observation(self):
  pump=ConnectedStatusPump(poll=Mock(),clock=lambda:10.)
  for role in ('hid','gatt'):
   self.assertTrue(pump._profile_event(role,{**profile(),'subscribed':True}))
  self.assertTrue(pump.poll_event.is_set());self.assertIsNone(pump.snapshot())
  token=pump.tracker.begin_poll()
  self.assertTrue(pump.tracker.commit_poll(token,profile(),profile()))
  self.assertEqual(pump.snapshot()['observedAt'],10.)

 def test_event_during_poll_discards_reply_then_requests_fresh_observation(self):
  now=[0.];calls=[];snapshots=[]
  def poll():
   calls.append(now[0])
   if len(calls)==1:
    pump._profile_event('gatt',{**profile(False),'subscribed':True})
    pump._profile_event('gatt',{**profile(),'subscribed':True})
   return dict(hid=profile(),gatt=profile())
  pump=ConnectedStatusPump(poll=poll,clock=lambda:now[0])
  for role in ('hid','gatt'):pump._profile_event(role,{**profile(),'subscribed':True})
  def wait(delay):
   snapshots.append(pump.snapshot());now[0]+=delay
   if len(calls)==2:pump.stop_event.set()
  pump._wait_poll=wait;pump._poll()
  self.assertEqual(calls,[0.,.1]);self.assertIsNone(snapshots[0])
  self.assertIsNotNone(snapshots[1]);self.assertEqual(snapshots[1]['observedAt'],.1)

 def test_event_burst_still_passes_minimum_poll_interval(self):
  pump=ConnectedStatusPump(poll=Mock());waits=[]
  pump.stop_event=Mock();pump.stop_event.wait.side_effect=lambda delay:waits.append(('floor',delay)) or False
  pump.poll_event=Mock();pump.poll_event.wait.side_effect=lambda delay:waits.append(('event',delay)) or True
  for _ in range(100):pump._wake_poll()
  pump._wait_poll(.5)
  self.assertEqual(waits,[('floor',.1),('event',.4)])
  waits.clear();pump._wait_poll(.1);self.assertEqual(waits,[('floor',.1)])

 def test_stop_or_failed_stream_wakes_remaining_delay(self):
  for failure in (False,True):
   pump=ConnectedStatusPump(poll=Mock())
   if failure:pump._fail()
   else:self.assertTrue(pump.stop())
   self.assertTrue(pump.poll_event.is_set());self.assertTrue(pump.stop_event.is_set())
   self.assertFalse(pump.tracker.is_open());self.assertIsNone(pump.snapshot())

 def test_stop_during_minimum_delay_skips_further_wait(self):
  pump=ConnectedStatusPump(poll=Mock());pump.stop_event=Mock();pump.stop_event.wait.return_value=True
  pump.poll_event=Mock();pump._wait_poll(.5);pump.poll_event.wait.assert_not_called()

 def test_idle_local_sampling_preserves_source_time_and_rejects_stale_data(self):
  now=[10.];client=Mock();client.idle.return_value=True
  value={'generation':2,'sequence':3,'observedAt':10.,'hid':profile(),'gatt':profile()}
  client.connection.return_value={'open':True,'snapshot':value}
  watch=ResumingControllerWatch(client,clock=lambda:now[0]);watch.mark_idle()
  for _ in range(10):
   now[0]+=.1;self.assertTrue(watch._refresh());self.assertEqual(watch.snapshot()['observedAt'],10.)
   self.assertEqual(watch.poll_period(),.1)
  now[0]=13.1;self.assertFalse(watch._refresh());self.assertFalse(watch.is_open())

if __name__=='__main__':unittest.main()
