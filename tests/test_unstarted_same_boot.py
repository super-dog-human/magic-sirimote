"""An expired launch that never entered the receiver can retire without reboot."""
import test_unstarted_boot as base
import unittest
from unittest.mock import patch
import orphan_reconcile as mod

class SameBootTests(unittest.TestCase):
 setUp=base.RecoveryTests.setUp
 tearDown=base.RecoveryTests.tearDown
 put=base.RecoveryTests.put
 def retire(self, **kwargs):
  return mod._archive_unstarted_after_boot(c=self.c,b=self.d,intent=self.intent,intent_stat=(self.a/'receiver-launch-intent.json').stat(),controller_app=str(self.a),receiver_app=str(self.b),receiver_package='unused',pin={},lease=self.lease,owner=self.uid,group=self.group,boot_time=self.boot-100,allow_current_boot=True,now_ms=self.boot*1000,native_idle=kwargs.get('native_idle',lambda:True))
 def test_expired_same_boot_preserves_evidence_without_stop_claim(self):
  self.assertEqual(self.retire()['priorOutcome'],'not-started-expired')
  self.assertFalse(list(self.b.glob('receiver-result-*')))
  self.assertTrue((self.b/('request-unstarted-'+self.run+'.json')).exists())
 def test_expiry_still_required(self):
  original=mod._read
  def future(*args,**kwargs):
   value,info=original(*args,**kwargs)
   if 'expiresEpochMs' in value:value['expiresEpochMs']=self.boot*1000+1
   return value,info
  with patch.object(mod,'_read',side_effect=future):
   with self.assertRaisesRegex(RuntimeError,'not expired'):self.retire()
 def test_native_wrapper_blocks_archive(self):
  with self.assertRaisesRegex(RuntimeError,'proof unavailable'):self.retire(native_idle=lambda:False)
  self.assertTrue((self.b/'request.json').exists())
 def test_starting_native_wrapper_during_archive_blocks_next_step(self):
  calls=iter([True,True,False])
  with self.assertRaises(RuntimeError):self.retire(native_idle=lambda:next(calls))
  self.assertTrue((self.a/'receiver-launch-intent.json').exists())
 def test_sensor_or_start_evidence_blocks_same_boot(self):
  for name in ('borrowed-active','receiver-start-'+self.run+'.json','receiver-ready-'+self.run+'.json'):
   p=self.b/name;p.write_text('{}')
   self.assertIsNone(self.retire());p.unlink()
 def test_old_controller_must_have_exited(self):
  with patch.object(mod,'_ended',return_value=False):
   with self.assertRaises(RuntimeError):self.retire()
 def test_pin_change_blocks_same_boot(self):
  with patch.object(mod.package,'package_matches',return_value=False):
   with self.assertRaises(RuntimeError):self.retire()
