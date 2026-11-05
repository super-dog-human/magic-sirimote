import sys,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
from connected_status_watch import ConnectedStatusWatch
from borrowed_gatt_view import TARGET,ADAPTER
from resident_supervisor_loop import run_loop

def profile(connected=True):
 return dict(returnValue=True,address=TARGET,adapterAddress=ADAPTER,connected=connected,connecting=False,connectRequest=False)

class Tests(unittest.TestCase):
 def watch(self):
  w=ConnectedStatusWatch(clock=time.monotonic)
  for role in ('hid','gatt'):w.event(role,{**profile(),'subscribed':True})
  return w
 def poll(self,w):return w.commit_poll(w.begin_poll(),profile(),profile())
 def waiter(self,w,stop=None):
  stop=stop or threading.Event();entered=threading.Event();done=threading.Event();result=[]
  original=w.changed.wait
  def wait(timeout):entered.set();return original(timeout)
  w.changed.wait=wait
  def run():
   result.append(w.wait_for_connection(.5,stop));done.set()
  t=threading.Thread(target=run);t.start();self.addCleanup(t.join,1)
  self.assertTrue(entered.wait(.3));return done,result
 def test_fresh_poll_wakes_waiting_consumer(self):
  w=self.watch();done,result=self.waiter(w)
  self.assertTrue(self.poll(w));self.assertTrue(done.wait(.3));self.assertEqual(result,[True])
 def test_poll_published_before_wait_is_not_lost(self):
  w=self.watch();self.poll(w)
  with unittest.mock.patch.object(w.changed,'wait',side_effect=AssertionError('unnecessary wait')):
   self.assertTrue(w.wait_for_connection(.5,threading.Event()))
 def test_events_and_discarded_poll_do_not_admit_connection(self):
  w=self.watch();done,result=self.waiter(w);token=w.begin_poll()
  w.event('hid',{**profile(),'subscribed':True})
  self.assertFalse(w.commit_poll(token,profile(),profile()))
  self.assertFalse(done.wait(.08));self.assertIsNone(w.snapshot())
  self.poll(w);self.assertTrue(done.wait(.3));self.assertEqual(result,[True])
 def test_disconnect_invalidates_old_snapshot_before_wait(self):
  w=self.watch();self.poll(w);generation=w.snapshot()['generation']
  w.event('gatt',{**profile(False),'subscribed':True})
  done,result=self.waiter(w);self.assertFalse(done.wait(.06))
  self.poll(w);self.assertTrue(done.wait(.3));self.assertEqual(result,[True]);self.assertGreater(w.snapshot()['generation'],generation)
 def test_closed_watch_wakes_without_admitting(self):
  w=self.watch();done,result=self.waiter(w);w.close()
  self.assertTrue(done.wait(.3));self.assertEqual(result,[False]);self.assertIsNone(w.snapshot())
 def test_stop_interrupts_without_connection(self):
  w=self.watch();stop=threading.Event();done,result=self.waiter(w,stop);stop.set()
  self.assertTrue(done.wait(.3));self.assertEqual(result,[False])
 def test_stale_and_disconnected_observations_timeout(self):
  for stale in (False,True):
   w=self.watch()
   if stale:
    self.poll(w);w.clock=lambda:time.monotonic()+10
   else:w.commit_poll(w.begin_poll(),profile(False),profile(False))
   self.assertFalse(w.wait_for_connection(.01,threading.Event()));self.assertIsNone(w.snapshot())
 def test_loop_waits_on_publication_then_rechecks_admission(self):
  w=self.watch();lease=Mock();lease.held.return_value=True;stop=threading.Event();cycle=Mock()
  cycle.begin.return_value={'status':'attention','reason':'receiver-package-mismatch'}
  original=w.wait_for_connection
  def publish(timeout,stop):self.poll(w);return original(timeout,stop)
  w.wait_for_connection=Mock(side_effect=publish)
  result=run_loop(watch=w,lease=lease,cycle_factory=lambda:cycle,stop=stop)
  self.assertEqual(result,{'status':'attention','reason':'receiver-package-mismatch'})
  w.wait_for_connection.assert_called_once_with(.5,stop);cycle.begin.assert_called_once();cycle.close.assert_called_once()
 def test_loop_close_during_wait_never_creates_cycle(self):
  w=self.watch();lease=Mock();lease.held.return_value=True;cycle=Mock()
  def close(timeout,stop):w.close();return False
  w.wait_for_connection=close
  result=run_loop(watch=w,lease=lease,cycle_factory=cycle,stop=threading.Event())
  self.assertEqual(result['reason'],'status-watch-closed');cycle.assert_not_called()

if __name__=='__main__':unittest.main()
