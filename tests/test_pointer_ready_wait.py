import unittest
from unittest.mock import Mock,patch
import output_devices as devices
from output_sysfs import wait_for_mouse,InventoryUnavailable


class PointerReadyWaitTests(unittest.TestCase):
    def setUp(self):
        self.now=0.;self.live=True;self.waits=[]
    def wait(self,delay):
        self.waits.append(delay);self.now+=delay
    def run_wait(self,read,**options):
        return wait_for_mouse(1,wait=self.wait,guard=lambda:self.live,
                              clock=lambda:self.now,read=read,**options)
    def test_new_mouse_interrupts_delay(self):
        read=lambda:{0:('LGE RCU',1,1),**({9:('ClickableMouse',1,9)} if self.now>=.2 else {})}
        self.assertTrue(self.run_wait(read));self.assertAlmostEqual(self.now,.2)
    def test_unrelated_device_does_not_interrupt_delay(self):
        self.assertFalse(self.run_wait(lambda:{4:('other mouse',1,4)}))
        self.assertAlmostEqual(self.now,1.)
    def test_missing_sysfs_preserves_delay(self):
        read=Mock(side_effect=PermissionError())
        self.assertFalse(self.run_wait(read));self.assertEqual(self.waits,[1.])
        read.assert_called_once()
    def test_mid_wait_metadata_failure_preserves_remaining_delay(self):
        read=Mock(side_effect=[{0:('LGE RCU',1,1)},InventoryUnavailable()])
        self.assertFalse(self.run_wait(read));self.assertAlmostEqual(self.now,1.)
        self.assertEqual(len(self.waits),2)
    def test_cancellation_does_not_wait_or_authorize(self):
        self.live=False;read=Mock()
        self.assertFalse(self.run_wait(read));read.assert_not_called()
        self.assertEqual(self.waits,[])
    def test_read_count_bounded_if_wait_does_not_block(self):
        read=Mock(return_value={0:('LGE RCU',1,1)})
        self.wait=lambda _:None
        self.assertFalse(self.run_wait(read));self.assertEqual(read.call_count,21)
    def test_backwards_clock_rejected(self):
        def wait(_):self.now=-1
        self.wait=wait
        with self.assertRaises(RuntimeError):self.run_wait(lambda:{0:('LGE RCU',1,1)})
    def test_hint_retries_actual_validation_and_does_not_return_outputs(self):
        missing=devices.OutputInventoryIncomplete(complete=True,counts={'LGE RCU':1,'ClickableMouse':0},errors={},unavailable=1)
        success=(object(),[],{'inventorySource':'sysfs-verified'})
        scan=Mock(side_effect=[missing,success]);hint=Mock(return_value=True)
        with patch.object(devices,'_open_with_sysfs',scan),patch('output_sysfs.wait_for_mouse',hint),patch.object(devices,'_report'):
            result=devices.open_verified_outputs(allow_retry=lambda:True,clock=lambda:self.now,wait=self.wait)
        self.assertIs(result,success);self.assertEqual(scan.call_count,2)
        hint.assert_called_once();self.assertEqual(self.waits,[])
    def test_incomplete_inventory_never_uses_hint(self):
        missing=devices.OutputInventoryIncomplete(complete=False,counts={'LGE RCU':1,'ClickableMouse':0},errors={'EACCES':1},unavailable=1)
        with patch.object(devices,'_open_with_sysfs',side_effect=missing),patch('output_sysfs.wait_for_mouse') as hint,patch.object(devices,'_report'):
            with self.assertRaises(devices.OutputInventoryIncomplete):
                devices.open_verified_outputs(allow_retry=lambda:True,clock=lambda:self.now,wait=self.wait,retry_window=1)
        hint.assert_not_called();self.assertEqual(self.waits,[1.])


if __name__=='__main__':unittest.main()
