import ctypes
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/native'))
from graphics import Canvas,KeyboardEvent,hex_character

class HexKeypadTests(unittest.TestCase):
    def test_physical_hex_and_numpad_keys_without_ime(self):
        for key,want in ((48,'0'),(57,'9'),(65,'A'),(70,'F'),(97,'a'),(102,'f'),
                         (58,':'),(1073741913,'1'),(1073741921,'9'),(1073741922,'0')):
            self.assertEqual(hex_character(key),want)
        self.assertEqual(hex_character(59,1),':')
        for key in (59,103,13,27,461,1073741905):self.assertIsNone(hex_character(key))

    def test_keypad_text_is_delivered_once_and_done_remains_one_key(self):
        frames=[]
        for key,mod,repeat in ((48,0,0),(57,0,0),(13,0,0),(13,0,1),(59,1,0),(8,0,0)):
            e=KeyboardEvent();e.type=768;e.keysym.sym=key;e.keysym.mod=mod;e.repeat=repeat
            frames.append(bytes(e).ljust(64,b'\0'))
        c=Canvas.__new__(Canvas)
        def poll(buffer):
            if not frames:return 0
            ctypes.memmove(buffer,frames.pop(0),64);return 1
        c.poll=poll
        self.assertEqual(list(c.events()),[('text','0'),('text','9'),('key',13),('text',':'),('key',8)])
