import errno,unittest
from output_devices import open_verified_outputs,OutputCloseError,failure_code
from test_rcu_output_device import Inventory

class RetryTests(unittest.TestCase):
 def setUp(self):self.now=0.;self.calls=0;self.guard=True;self.waits=[]
 def wait(self,n):self.waits.append(n);self.now+=n
 def run_attempts(self,attempt,**kwargs):
  return open_verified_outputs(allow_retry=lambda:self.guard,wait=self.wait,clock=lambda:self.now,attempt_fn=attempt,**kwargs)
 def test_missing_boot_device_later_appears_and_inventory_reverified(self):
  f=Inventory();del f.names[9]
  def attempt(*a,**k):
   self.calls+=1
   if self.calls==3:f.names[9]='ClickableMouse'
   return f.run()
  out,records,inventory=self.run_attempts(attempt)
  self.assertEqual(self.calls,3);self.assertEqual(self.waits,[1.,1.]);self.assertTrue(inventory['inventoryComplete'])
  self.assertEqual(f.rw,[0,9]);out.close(close_fn=f.close)
 def test_failure_expires_without_success_or_output(self):
  def attempt(*a,**k):self.calls+=1;raise PermissionError(errno.EACCES,'unavailable')
  with self.assertRaises(PermissionError):self.run_attempts(attempt,retry_window=3)
  self.assertEqual(self.now,3);self.assertEqual(self.calls,3)
 def test_stop_during_wait_prevents_next_attempt(self):
  def attempt(*a,**k):self.calls+=1;raise RuntimeError('not ready')
  def wait(n):self.now+=n;self.guard=False
  self.wait=wait
  with self.assertRaises(RuntimeError):self.run_attempts(attempt)
  self.assertEqual(self.calls,1)
 def test_descriptor_cleanup_failure_never_retried(self):
  def attempt(*a,**k):self.calls+=1;raise OutputCloseError('close failed')
  with self.assertRaises(OutputCloseError):self.run_attempts(attempt)
  self.assertEqual(self.calls,1);self.assertEqual(self.waits,[])
 def test_real_inventory_close_failure_is_classified(self):
  f=Inventory()
  def close(fd):raise OSError(errno.EIO,'close uncertain')
  f.close=close
  with self.assertRaises(OutputCloseError):f.run()
 def test_duplicate_nodes_remain_rejected(self):
  f=Inventory();f.names[1]='LGE RCU'
  with self.assertRaises(RuntimeError):self.run_attempts(lambda *a,**k:f.run(),retry_window=2)
  self.assertEqual(f.rw,[])
 def test_default_without_guard_does_not_retry(self):
  def attempt(*a,**k):self.calls+=1;raise RuntimeError('not ready')
  with self.assertRaises(RuntimeError):open_verified_outputs(attempt_fn=attempt)
  self.assertEqual(self.calls,1)
 def test_backwards_clock_aborts(self):
  def attempt(*a,**k):self.now=-1;self.calls+=1;raise RuntimeError('not ready')
  with self.assertRaises(RuntimeError):self.run_attempts(attempt)
  self.assertEqual(self.calls,1)
 def test_failure_categories_omit_exception_details(self):
  self.assertEqual(failure_code(PermissionError(errno.EACCES,'private path')),'output-open-permission')
  self.assertEqual(failure_code(RuntimeError('Builtin-key-already-held')),'output-open-key-held')
  self.assertEqual(failure_code(RuntimeError('output-node-inventory-incomplete-or-nonunique: secret')),'output-open-inventory')
  self.assertEqual(failure_code(RuntimeError('private data')),'output-open-other')
if __name__=='__main__':unittest.main()
