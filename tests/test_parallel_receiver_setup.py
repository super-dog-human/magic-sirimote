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


 def test_resumed_input_queue_exists_before_initialization_response(self):
  import os
  args,outputs,sink=self.fixture();reader,writer=os.pipe();opened=[]
  def opening(**kwargs):
   self.assertEqual(kwargs,{'wait_for_target':False});opened.append(True);return reader
  def initialize(**kwargs):
   self.assertEqual(opened,[True])
   os.write(writer,bytes.fromhex('fce00800'))
   return object()
  def session(*a,**k):
   self.assertEqual(os.read(reader,4),bytes.fromhex('fce00800'))
   return {'status':'complete'}
  args.update(open_target=opening,close_target=os.close,open_before_input=True,gatt_lookup_reply={})
  try:
   with patch.object(entry.borrowed_runtime,'initialize_input',side_effect=initialize),patch.object(entry,'run_once',side_effect=session):
    result=entry.run_connected_once(**args)
   self.assertEqual(result['status'],'complete')
   with self.assertRaises(OSError):os.fstat(reader)
  finally:os.close(writer)

 def test_resumed_open_failure_sends_no_input_initialization(self):
  args,outputs,sink=self.fixture()
  args.update(open_before_input=True,gatt_lookup_reply={})
  args['open_target'].side_effect=RuntimeError('target inventory incomplete')
  with patch.object(entry.borrowed_runtime,'initialize_input') as init,patch.object(entry,'run_once') as session:
   result=entry.run_connected_once(**args)
  init.assert_not_called();session.assert_not_called();args['close_target'].assert_not_called()
  self.assertEqual(result['diagnostic'],'target-inventory-incomplete')

 def test_resumed_initialization_failure_closes_preopened_input(self):
  args,outputs,sink=self.fixture();args.update(open_before_input=True,gatt_lookup_reply={})
  with patch.object(entry.borrowed_runtime,'initialize_input',side_effect=RuntimeError('failed')):
   result=entry.run_connected_once(**args)
  self.assertEqual(result['status'],'attention');args['close_target'].assert_called_once_with(3)

 def test_missing_preopen_initializes_once_then_opens_normally(self):
  args,outputs,sink=self.fixture();events=[]
  args.update(open_before_input=True,gatt_lookup_reply={})
  def opening(**options):
   events.append(('open',options))
   if options:raise RuntimeError('target not present')
   return 3
  def initialize(**kwargs):events.append(('initialize',{}));return object()
  args['open_target']=opening
  with patch.object(entry.borrowed_runtime,'initialize_input',side_effect=initialize) as init,patch.object(entry,'run_once',return_value={'status':'complete'}):
   result=entry.run_connected_once(**args)
  self.assertEqual(result['status'],'complete');init.assert_called_once()
  self.assertEqual(events,[('open',{'wait_for_target':False}),('initialize',{}),('open',{})])
  args['close_target'].assert_called_once_with(3)

 def test_missing_preopen_does_not_ignore_stop(self):
  args,outputs,sink=self.fixture();args.update(open_before_input=True,gatt_lookup_reply={},abort=lambda:True)
  args['open_target'].side_effect=RuntimeError('target not present')
  with patch.object(entry.borrowed_runtime,'initialize_input') as init:
   result=entry.run_connected_once(**args)
  init.assert_not_called();args['close_target'].assert_not_called()
  self.assertEqual(result['status'],'attention')

 def test_preopen_cannot_use_an_original_controller_handoff(self):
  for options in ({'gatt_lookup_reply':None},{'gatt_lookup_reply':{},'input_handoff_check':lambda:True}):
   args,outputs,sink=self.fixture();args.update(open_before_input=True,**options)
   with self.assertRaises(ValueError):entry.run_connected_once(**args)
   args['open_target'].assert_not_called()


if __name__=='__main__':unittest.main()
