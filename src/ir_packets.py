#!/usr/bin/env python3
"""Pure A1513 IR configuration encoding. Prints examples; never transmits."""
ENTRIES=(('Volume up',0x02,0,'20df40bf'),('Volume down',0x04,0,'20dfc03f'),
         ('Home',0x01,0,'20df3ec1'),('Power hold',0x01,2,'20df10ef'))

def _selector(button,delay):
    if type(button) is not int or button not in (1,2,4,8,16,32,64,128):
        raise ValueError('Expected one button bit')
    if type(delay) is not int or not 0<=delay<=255:raise ValueError('Invalid delay selector')

def encode_entry(button,delay,nec):
    _selector(button,delay)
    if type(nec) is not bytes or len(nec)!=4:raise ValueError('Expected four NEC bytes in wire order')
    return bytes([0xf0,1,button,delay,1,0,0,0,0,0])+nec

def encode_delete(button,delay):
    _selector(button,delay)
    return bytes([0xf0,2,button,delay])

def main():
    print('INSPECTION ONLY. No connection or transmission. Read docs/IR.md before using these bytes.')
    for name,button,delay,nec in ENTRIES:
        print(name+': '+encode_entry(button,delay,bytes.fromhex(nec)).hex(' '))
if __name__=='__main__':main()
