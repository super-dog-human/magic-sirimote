"""A pointer arriving after the startup window must not terminate navigation."""
import threading
import unittest
from unittest.mock import Mock, patch

import output_devices as devices
from deferred_mouse import DeferredMouse
from fixture_devices import MemoryDevices
from output_bridge import VerifiedOutputs


class LateMouseTests(unittest.TestCase):
    def test_close_interrupts_thread_waiting_for_missing_pointer(self):
        key = {'path': '/dev/input/event0'}
        partial = Mock(key_fd=10, mouse_fd=None)
        scan = Mock(return_value=(partial, [key], {}))
        provider = DeferredMouse(key, lambda: True, scan=scan, verify=Mock())
        entered = threading.Event()

        def wait_for_missing(delay, **kwargs):
            entered.set()
            kwargs['wait'](5)

        with patch('deferred_mouse.wait_for_mouse', wait_for_missing):
            provider.start()
            self.assertTrue(entered.wait(2))
            provider.close()
        self.assertFalse(provider.thread.is_alive())
        self.assertIsNone(provider.error)
        self.assertIsNone(provider.pending)
        scan.assert_called_once()
        partial.close.assert_called_once()

    def test_missing_pointer_wait_is_cancelled_without_another_scan(self):
        key = {'path': '/dev/input/event0'}
        partial = Mock(key_fd=10, mouse_fd=None)
        scan = Mock(return_value=(partial, [key], {}))
        provider = DeferredMouse(key, lambda: True, scan=scan, verify=Mock())
        with patch('deferred_mouse.wait_for_mouse', side_effect=lambda *a, **k: provider.cancel.set()):
            provider._prepare()
        self.assertIsNone(provider.error)
        self.assertIsNone(provider.pending)
        scan.assert_called_once()
        partial.close.assert_called_once()

    def test_partial_descriptor_close_failure_is_fatal_and_retained(self):
        key = {'path': '/dev/input/event0'}
        partial = Mock(key_fd=10, mouse_fd=None)
        partial.close.side_effect = OSError('close failed')
        scan = Mock(return_value=(partial, [key], {}))
        provider = DeferredMouse(key, lambda: True, scan=scan, verify=Mock())
        provider._prepare()
        with self.assertRaises(OSError):
            provider.poll(Mock())
        with self.assertRaises(OSError):
            provider.close()
        scan.assert_called_once()
        partial.close.assert_called_once()

    def test_changed_key_is_rejected_even_when_pointer_missing(self):
        partial = Mock(key_fd=10, mouse_fd=None)
        provider = DeferredMouse({'path': '/dev/input/event0'}, lambda: True,
            scan=Mock(return_value=(partial, [{'path': '/dev/input/event2'}], {})), verify=Mock())
        provider._prepare()
        with self.assertRaisesRegex(RuntimeError, 'navigation output changed'):
            provider.poll(Mock())
        partial.close.assert_called_once()

    def test_navigation_survives_pointer_arriving_after_15_seconds(self):
        now = [0.]
        key = {'path': '/dev/input/event0'}
        memory = MemoryDevices()
        owner = VerifiedOutputs(1, None, allow_missing_mouse=True,
                                ioctl_fn=memory.ioctl, write_fn=memory.write,
                                sleep_fn=lambda _: None)
        partials = []
        candidate = Mock(key_fd=11, mouse_fd=12, closed=False)
        candidate._managed_key_down.return_value = False
        waits = []

        def wait(delay):
            waits.append(delay)
            self.assertFalse(owner.pointer_ready)
            owner.key_pulse('right')
            now[0] += delay

        def attempt(root, **kwargs):
            if now[0] >= 15:
                return candidate, [dict(key), {'path': '/dev/input/event11'}], {}
            if kwargs.get('allow_missing_mouse'):
                partial = Mock(key_fd=10, mouse_fd=None)
                partials.append(partial)
                return partial, [dict(key)], {}
            raise devices.OutputInventoryIncomplete(complete=True,
                counts={devices.KEY_NAME: 1, devices.MOUSE_NAME: 0}, errors={}, unavailable=0)

        def scan(**kwargs):
            kwargs['wait'] = wait
            return devices.open_verified_outputs(clock=lambda: now[0], attempt_fn=attempt, **kwargs)

        def readiness(delay, **kwargs):
            wait(delay)
            return now[0] >= 15

        provider = DeferredMouse(key, lambda: True, scan=scan, verify=Mock())
        owner.mouse_provider = provider
        with patch('deferred_mouse.wait_for_mouse', readiness, create=True):
            provider._prepare()
            self.assertIsNone(provider.error)
            self.assertTrue(owner.pointer_ready)
        self.assertGreaterEqual(now[0], 15)
        self.assertEqual(owner.mouse_fd, 12)
        self.assertTrue(waits)
        self.assertEqual(owner.key_writes, 2*len(waits))
        self.assertTrue(all(fd == 1 for fd, _ in memory.writes))
        for partial in partials:
            partial.close.assert_called_once()
        closed = []
        owner.close(close_fn=closed.append)
        self.assertEqual(closed, [12, 1, 11])


if __name__ == '__main__':
    unittest.main()
