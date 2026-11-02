#!/usr/bin/env python3
"""Demonstrate the real button decoder using synthetic packets. No device I/O."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'runtime'))
from system_buttons import SystemButtons

def main():
    decoder=SystemButtons(lambda action:print('  TV action:',action))
    decoder.bind(1)
    for label,mask in [('MENU',0x20),('Microphone',0x10),('TV',0x01),('Play/Pause',0x08)]:
        print(label)
        decoder.feed(1,bytes([0xfc,0,0]))
        decoder.feed(1,bytes([0xfc,0,mask]))
        decoder.feed(1,bytes([0xfc,0,mask])) # Held button: no duplicate action.
    print('Synthetic input only. No Bluetooth, TV connection, or IR transmission.')
if __name__=='__main__':main()
