import sys,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
import postconnect_receiver_entry as entry


class Tests(unittest.TestCase):
 def fixture(self):
  outputs=Mock();outputs.verify_released.return_value=True
  outputs.summary.return_value=dict(keyFrameWrites=0,clickFrameWrites=0,motionFrameWrites=0)
  sink=Mock();sink.verify_released.return_value=True
  watch=Mock();watch.snapshot.return_value={'generation':1}
  args=dict(watch=watch,lease=Mock(),paired_check=lambda:True,
   external_feature_guard=lambda:True,record=lambda _:True,open_target=Mock(return_value=3),
   open_outputs=Mock(return_value=outputs),close_target=Mock(),duration=None,
   abort=lambda:False,clock=lambda:0.,open_system_keys=Mock(return_value=(sink,4)),close_system_keys=Mock())
  return args,outputs,sink

 def test_local_preparation_overlaps_input_start_without_receiving_early(self):
  args,outputs,sink=self.fixture();input_started=threading.Event();outputs_started=threading.Event()
  main=threading.get_ident();workers=[]
  def local():
   workers.append(threading.get_ident());outputs_started.set()
   if not input_started.wait(2):raise RuntimeError('input was not started concurrently')
   return outputs
  def initialize(**kwargs):
   input_started.set()
   self.assertTrue(outputs_started.wait(2))
   return object()
  args['open_outputs']=local
  with patch.object(entry.borrowed_runtime,'initialize_input',side_effect=initialize),patch.object(entry,'run_once',return_value={'status':'complete'}) as session:
   result=entry.run_connected_once(**args)
  self.assertEqual(result['status'],'complete');session.assert_called_once()
  self.assertEqual(len(workers),1);self.assertNotEqual(workers[0],main)
  outputs.close.assert_called_once();args['close_system_keys'].assert_called_once_with(4)
  args['close_target'].assert_called_once_with(3)
  outputs.best_effort_release.assert_not_called()

 def test_input_failure_joins_preparation_and_closes_late_handles(self):
  args,outputs,sink=self.fixture();ready=threading.Event();finish=threading.Event()
  def local():
   ready.set()
   if not finish.wait(2):raise RuntimeError('test preparation did not finish')
   return outputs
  def initialize(**kwargs):
   self.assertTrue(ready.wait(2));finish.set();raise RuntimeError('input failed')
  args['open_outputs']=local
  with patch.object(entry.borrowed_runtime,'initialize_input',side_effect=initialize),patch.object(entry,'run_once') as session:
   result=entry.run_connected_once(**args)
  self.assertEqual(result['status'],'attention');session.assert_not_called()
  outputs.close.assert_called_once();args['close_system_keys'].assert_called_once_with(4)
  args['open_target'].assert_not_called()

 def test_partial_output_failure_closes_resources_and_never_enables_sensor(self):
  args,outputs,sink=self.fixture();args['open_system_keys'].side_effect=OSError('unavailable')
  with patch.object(entry.borrowed_runtime,'initialize_input',return_value=object()),patch.object(entry,'run_once') as session:
   result=entry.run_connected_once(**args)
  self.assertEqual(result['reason'],'resource-close-unverified')
  self.assertIn('output-preparation-failed',result['errors']);session.assert_not_called()
  outputs.close.assert_called_once();args['close_target'].assert_called_once_with(3)
  args['close_system_keys'].assert_not_called()

 def test_connection_changed_during_parallel_open_rejects_session(self):
  args,outputs,sink=self.fixture()
  args['watch'].snapshot.side_effect=[{'generation':1},{'generation':2}]
  with patch.object(entry.borrowed_runtime,'initialize_input',return_value=object()),patch.object(entry,'run_once') as session:
   result=entry.run_connected_once(**args)
  self.assertEqual(result['status'],'attention');session.assert_not_called()
  outputs.close.assert_called_once();args['close_system_keys'].assert_called_once_with(4)
  args['close_target'].assert_called_once_with(3)

 def test_cleanup_failure_cannot_be_reported_as_complete(self):
  args,outputs,sink=self.fixture();outputs.close.side_effect=OSError('unconfirmed')
  with patch.object(entry.borrowed_runtime,'initialize_input',return_value=object()),patch.object(entry,'run_once',return_value={'status':'complete'}):
   result=entry.run_connected_once(**args)
  self.assertEqual(result['reason'],'resource-close-unverified')
  self.assertIn('output-close-error',result['errors'])
  args['close_system_keys'].assert_called_once_with(4);args['close_target'].assert_called_once_with(3)

 def test_both_local_inventories_run_concurrently(self):
  args,outputs,sink=self.fixture();a=threading.Event();b=threading.Event()
  def local():
   a.set()
   if not b.wait(2):raise RuntimeError('system keys were serialized')
   return outputs
  def system():
   b.set()
   if not a.wait(2):raise RuntimeError('outputs were serialized')
   return sink,4
  args.update(open_outputs=local,open_system_keys=system)
  with patch.object(entry.borrowed_runtime,'initialize_input',return_value=object()),patch.object(entry,'run_once',return_value={'status':'complete'}):
   result=entry.run_connected_once(**args)
  self.assertEqual(result['status'],'complete')
  outputs.close.assert_called_once();args['close_system_keys'].assert_called_once_with(4)

 def test_second_thread_start_failure_still_joins_and_closes_first(self):
  args,outputs,sink=self.fixture();start=threading.Thread.start;count=[0]
  def start_one(thread):
   count[0]+=1
   if count[0]==2:raise RuntimeError('thread unavailable')
   return start(thread)
  with patch.object(entry.threading.Thread,'start',start_one),patch.object(entry.borrowed_runtime,'initialize_input',return_value=object()),patch.object(entry,'run_once') as session:
   result=entry.run_connected_once(**args)
  self.assertEqual(result['reason'],'resource-close-unverified');session.assert_not_called()
  outputs.close.assert_called_once();args['open_system_keys'].assert_not_called()

 def test_missing_target_cleanup_evidence_requires_all_preparations_closed(self):
  for failure in (None,'close','release','preparation'):
   args,outputs,sink=self.fixture()
   args['open_target'].side_effect=RuntimeError('target not present')
   if failure=='close':outputs.close.side_effect=OSError('failed')
   if failure=='release':sink.verify_released.return_value=False
   if failure=='preparation':args['open_system_keys'].side_effect=OSError('failed')
   with patch.object(entry.borrowed_runtime,'initialize_input',return_value=object()),patch.object(entry,'run_once') as session:
    result=entry.run_connected_once(**args)
   session.assert_not_called();outputs.close.assert_called_once()
   if failure is None:
    self.assertTrue(result['resourcesClosed']);self.assertEqual(result['setupStage'],'open-target')
    self.assertEqual(result['diagnostic'],'target-not-present')
   else:
    self.assertNotIn('resourcesClosed',result)
    self.assertEqual(result['reason'],'resource-close-unverified')


if __name__=='__main__':unittest.main()
