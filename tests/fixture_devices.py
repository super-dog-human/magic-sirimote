import math
import struct
import unittest

from combined_receiver import CombinedReceiver
from output_bridge import (VerifiedOutputs, EVENT, EV_KEY, EV_REL, BTN_LEFT, KEYS, KEY_CODES,
                           IOCG_EVENT_BITS, IOCG_KEY_BITS, IOCG_REL_BITS, IOCG_KEY_STATE,
                           KEY_BYTES)


def bits(*values):
    out = bytearray(KEY_BYTES)
    for value in values: out[value // 8] |= 1 << (value % 8)
    return bytes(out)


class MemoryDevices:
    def __init__(self):
        self.held = {1: set(), 2: set()}
        self.writes = []
        self.short = False

    def ioctl(self, fd, request, buf, mutate):
        if request == IOCG_EVENT_BITS: value = bits(0, 1, 2)
        elif request == IOCG_KEY_BITS: value = bits(*(KEY_CODES if fd == 1 else (BTN_LEFT,)))
        elif request == IOCG_REL_BITS: value = bits(0, 1)
        elif request == IOCG_KEY_STATE: value = bits(*self.held[fd])
        else: raise AssertionError(request)
        buf[:] = value
        return 0

    def write(self, fd, packet):
        if self.short: return len(packet) - 1
        events = [EVENT.unpack(packet[i:i + EVENT.size]) for i in range(0, len(packet), EVENT.size)]
        self.writes.append((fd, events))
        for _, _, kind, code, value in events:
            if kind == EV_KEY:
                if value: self.held[fd].add(code)
                else: self.held[fd].discard(code)
        return len(packet)


def touch(x, y, state, clock, buttons=0):
    x &= 0xfff; y &= 0xfff
    return b'\xfc' + bytes((1, buttons, 0x32, clock & 255, clock >> 8, 0,
                            x & 255, ((x >> 8) & 15) | ((y & 15) << 4), y >> 4,
                            0, 0, 0, state))


def motion(angle=0):
    return b'\xfc' + bytes((4, 0)) + struct.pack('<3f6h', 0., 0., math.sin(angle / 2), 0, 0, 0, 0, 0, 0)
