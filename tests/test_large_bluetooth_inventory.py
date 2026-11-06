import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from bootstrap_connect import BootstrapClient
from pumping_luna_client import LunaCallError
from interactive_status_read import read_status


class LargeInventoryTests(unittest.TestCase):
    def client(self, size):
        self.children = []
        def spawn(argv, **kwargs):
            code = "import json;print(json.dumps({'returnValue':True,'devices':[{'name':'x'*%d}]}),flush=True)" % size
            child = subprocess.Popen([sys.executable, '-c', code], **kwargs)
            self.children.append(child)
            return child
        return BootstrapClient(pump=lambda: None, guard=lambda: True,
                               spawn=spawn, get_euid=lambda: 1000)

    def test_inventory_above_old_bound_is_parsed_and_child_reaped(self):
        client = self.client(90000)
        with patch('resident_autoconnect.verify_self', return_value=True):
            reply = client('device/getStatus', {'subscribe': False}, timeout=4)
        self.assertTrue(reply['returnValue'])
        self.assertEqual(len(reply['devices'][0]['name']), 90000)
        self.assertIsNotNone(self.children[0].poll())

    def test_inventory_still_has_finite_bound_and_reaps_child(self):
        client = self.client(1024 * 1024 + 1)
        with patch('resident_autoconnect.verify_self', return_value=True):
            with self.assertRaisesRegex(LunaCallError, 'stdout exceeded bound'):
                client('device/getStatus', {'subscribe': False}, timeout=4)
        self.assertIsNotNone(self.children[0].poll())

    def test_individual_profile_read_keeps_small_bound(self):
        client = self.client(90000)
        self.assertEqual(client._stdout_limit('hid/getStatus'), 65536)
        self.assertEqual(client._stdout_limit('gatt/getStatus'), 65536)

    def test_receiver_pairing_check_accepts_same_large_inventory(self):
        client = self.client(90000)
        result = read_status('device/getStatus', spawn=client.spawn)
        self.assertTrue(result['returnValue'])
        self.assertIsNotNone(self.children[0].poll())

    def test_receiver_status_bounds_remain_enforced(self):
        for method, size in [('device/getStatus', 1024*1024+1), ('hid/getStatus', 90000)]:
            client = self.client(size)
            with self.assertRaisesRegex(RuntimeError, 'status output limit'):
                read_status(method, spawn=client.spawn)
            self.assertIsNotNone(self.children[0].poll())
