import sys,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
from connected_status_pump import ConnectedStatusPump
from controller_status_watch import ResumingControllerWatch
from borrowed_gatt_view import TARGET,ADAPTER
from prelaunch_handoff_runtime import lookup_before_input

def profile(connected=True):
 return dict(returnValue=True,address=TARGET,adapterAddress=ADAPTER,connected=connected,connecting=False,connectRequest=False)

class Tests(unittest.TestCase):
 def test_poll_burst_ends_and_restarts_only_after_connection_change(self):
  now=[0.];waits=[];disconnected=[False];stopped=[False]
  def poll():
   if now[0]>=3 and not disconnected[0]:
    disconnected[0]=True
    pump.tracker.event('hid',{**profile(False),'subscribed':True})
    return {'hid':profile(False),'gatt':profile()}
   return {'hid':profile(),'gatt':profile()}
  pump=ConnectedStatusPump(poll=poll,clock=lambda:now[0])
  for role in ('hid','gatt'):pump.tracker.event(role,{**profile(),'subscribed':True})
  def wait(seconds):
   waits.append((round(now[0],3),seconds));now[0]+=seconds
   if now[0]>=6:stopped[0]=True
  pump.stop_event=Mock();pump.stop_event.is_set.side_effect=lambda:stopped[0];pump._wait_poll=wait
  pump._poll()
  self.assertTrue(all(delay==.1 for at,delay in waits if at<1.9))
  self.assertTrue(any(delay==.5 for at,delay in waits if 2<=at<3))
  self.assertTrue(all(delay==.1 for at,delay in waits if 3.6<=at<5))
  self.assertTrue(pump.tracker.is_open())

 def test_receiver_idle_sampling_catches_first_connection(self):
  client=Mock();client.idle.return_value=True;client.active.return_value=True
  client.connection.return_value={'open':True,'snapshot':None}
  watch=ResumingControllerWatch(client,clock=lambda:10.)
  self.assertTrue(watch.mark_idle());self.assertTrue(watch._refresh());self.assertEqual(watch.poll_period(),.1)
  client.connection.return_value={'open':True,'snapshot':{'generation':2,'sequence':1,'observedAt':10.,'hid':profile(),'gatt':profile()}}
  self.assertTrue(watch._refresh());self.assertEqual(watch.poll_period(),.1)
  self.assertTrue(watch.mark_active());self.assertEqual(watch.poll_period(),.5)

 def test_faster_sampling_keeps_half_second_stable_requirement(self):
  now=[0.];watch=Mock();watch.is_open.return_value=True
  watch.snapshot.side_effect=lambda:{'generation':2,'observedAt':now[0]}
  lease=Mock();lease.held.return_value=True;records=[]
  requester=Mock(return_value={'returnValue':True,'address':TARGET,'adapterAddress':ADAPTER,'clientId':'5'})
  def wait(seconds):now[0]+=seconds
  result=lookup_before_input(watch=watch,lease=lease,record=lambda stage,value:records.append((stage,now[0])),
   requester_factory=lambda **_:requester,clock=lambda:now[0],wait=wait)
  self.assertEqual(result[1],2)
  self.assertGreaterEqual(records[-1][1]-.05,.5)
  self.assertLess(records[-1][1],.7)

 def test_lookup_gap_keeps_fast_observation_without_granting_input(self):
  now=[10.];client=Mock();client.idle.return_value=True;client.active.return_value=True
  sample={'generation':2,'sequence':1,'observedAt':10.,'hid':profile(),'gatt':profile()}
  client.connection.return_value={'open':True,'snapshot':sample}
  watch=ResumingControllerWatch(client,clock=lambda:now[0])
  self.assertTrue(watch.mark_idle());self.assertTrue(watch._refresh())
  # The GATT lookup's transitional notification must invalidate control,
  # but need not slow down the observer while reconnection is underway.
  now[0]=10.1;client.connection.return_value={'open':True,'snapshot':None}
  self.assertTrue(watch._refresh());self.assertIsNone(watch.snapshot())
  self.assertEqual(watch.poll_period(),.1)
  now[0]=10.3;client.connection.return_value={'open':True,'snapshot':{**sample,'generation':3,'observedAt':10.3}}
  self.assertTrue(watch._refresh());self.assertEqual(watch.snapshot()['generation'],3)
  self.assertEqual(watch.poll_period(),.1)
  self.assertTrue(watch.mark_active());self.assertEqual(watch.poll_period(),.5)

 def test_idle_sampling_does_not_grant_control_for_absent_connection(self):
  now=[10.];client=Mock();client.idle.return_value=True;client.active.return_value=True
  client.connection.return_value={'open':True,'snapshot':{'generation':2,'sequence':1,'observedAt':10.,'hid':profile(),'gatt':profile()}}
  watch=ResumingControllerWatch(client,clock=lambda:now[0])
  watch.mark_idle();watch._refresh()
  client.connection.return_value={'open':True,'snapshot':None}
  now[0]=10.1;watch._refresh();self.assertEqual(watch.poll_period(),.1)
  now[0]=12.1;watch._refresh();self.assertEqual(watch.poll_period(),.1)
  self.assertIsNone(watch.snapshot())
  client.connection.return_value={'open':False,'snapshot':None}
  self.assertFalse(watch._refresh());self.assertFalse(watch.is_open())

if __name__=='__main__':unittest.main()
