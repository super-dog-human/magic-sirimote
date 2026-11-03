import struct
import unittest
from unittest.mock import patch
import hid_input
from runtime_device import registered_name_matches


class NamelessRemoteTests(unittest.TestCase):
    def test_registered_name_is_optional_only_for_paired_devices(self):
        for name in ('SERIAL', '', None):
            self.assertTrue(registered_name_matches({'paired':True,'name':name},'SERIAL'))
        self.assertFalse(registered_name_matches({'paired':False,'name':''},'SERIAL'))
        self.assertFalse(registered_name_matches({'paired':True,'name':'OTHER'},'SERIAL'))
    def test_hid_model_and_address_remain_required_without_display_name(self):
        def check(name, address, product=0x0266):
            replies=[struct.pack('=IHH',5,0x004c,product),name.encode()+b'\0',address.encode()+b'\0']
            with patch.object(hid_input,'ioctl',side_effect=replies):return hid_input.identity(1)['matches']
        self.assertTrue(check('',hid_input.TARGET))
        self.assertTrue(check(hid_input.NAME,hid_input.TARGET))
        self.assertFalse(check('OTHER',hid_input.TARGET))
        self.assertFalse(check('','02:aa:bb:cc:dd:ee'))
        self.assertFalse(check('',hid_input.TARGET,0x0267))


if __name__=='__main__':unittest.main()
