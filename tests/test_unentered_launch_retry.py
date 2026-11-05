"""An accepted-but-unentered app request may be re-dispatched once, silently."""
import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/integrated'),str(ROOT/'src/runtime')]
import tv_launch

class RetryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.state=Path(self.tmp.name);self.run='a'*32
  self.invoke=Mock(return_value=Mock(returncode=0,stdout='{"returnValue":true}'))
  self.launcher=tv_launch.Launcher(self.run,invoke=self.invoke)
  self.launcher.attempted={'B'};self.launcher.accepted_at=10
  self.lease=Mock();self.lease.held.return_value=True
  self.found={'ui':[],'receiver':[],'legacy':[],'controller':[{'pid':1}]}
  self.read=Mock(return_value={'run':self.run})
  self.stack=__import__('contextlib').ExitStack();self.addCleanup(self.stack.close)
  self.stack.enter_context(patch.object(tv_launch.bundle,'active',return_value=True))
  self.stack.enter_context(patch('control_processes.processes',side_effect=lambda:self.found))
  self.stack.enter_context(patch('receiver_request.read_request',self.read))
  self.stack.enter_context(patch('prelaunch_handoff_runtime.write_json_once'))
 def retry(self,now=14):return self.launcher.retry_unentered(receiver_state=self.state,lease=self.lease,clock=lambda:now)
 def test_lost_dispatch_retries_same_request_once_without_new_input(self):
  self.assertTrue(self.retry());self.assertFalse(self.retry(100))
  self.invoke.assert_called_once()
  args=self.invoke.call_args.args[0]
  self.assertEqual(args[-2],tv_launch.URI)
  self.assertEqual(json.loads(args[-1])['params'],{'inputHandoff':self.run})
 def test_no_retry_while_first_launch_is_still_starting(self):
  self.assertFalse(self.retry(12.9));self.invoke.assert_not_called()
 def test_existing_wrapper_or_receiver_suppresses_retry(self):
  for role in ('ui','receiver','legacy'):
   self.found[role]=[{'pid':2}];self.assertFalse(self.retry());self.found[role]=[]
  self.invoke.assert_not_called()
 def test_every_entry_evidence_blocks_retry(self):
  for name in ['receiver-'+k+'-'+self.run+'.json' for k in ('start','ready','progress','result')]+['borrowed-active','recovery-request.json']:
   p=self.state/name;p.write_text('{}');self.assertFalse(self.retry());p.unlink()
  self.invoke.assert_not_called()
 def test_expired_request_is_not_redispatched(self):
  self.read.side_effect=RuntimeError('request invalid or expired')
  with self.assertRaises(RuntimeError):self.retry()
  self.invoke.assert_not_called()
 def test_different_run_or_lost_lease_is_not_retried(self):
  self.read.return_value={'run':'b'*32};self.assertFalse(self.retry())
  self.read.return_value={'run':self.run};self.lease.held.return_value=False;self.assertFalse(self.retry())
  self.invoke.assert_not_called()
 def test_uncertain_retry_is_not_repeated(self):
  self.invoke.side_effect=TimeoutError('transport failed')
  self.assertFalse(self.retry())
  self.assertFalse(self.retry(100));self.invoke.assert_called_once()
