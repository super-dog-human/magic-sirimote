"""Button edge handling and IR packet encoding, without device access."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'src/runtime')]
import ir_packets
from system_buttons import SystemButtons

class ProtocolTests(unittest.TestCase):
    def test_buttons_hold_and_chord_do_not_duplicate(self):
        actions=[];d=SystemButtons(actions.append);d.bind(1)
        for mask in [0,32,32,0,16,16,0,48,32,0,1,0,8,0]:d.feed(1,bytes([0xfc,0,mask]))
        self.assertEqual(actions,['back','back','home','playpause'])
    def test_ir_encoder_matches_observed_power_packet(self):
        self.assertEqual(ir_packets.encode_entry(1,2,bytes.fromhex('20df10ef')),bytes.fromhex('f001010201000000000020df10ef'))
        self.assertEqual(ir_packets.encode_delete(1,5),bytes.fromhex('f0020105'))
        with self.assertRaises(ValueError):ir_packets.encode_entry(3,2,b'abcd')
