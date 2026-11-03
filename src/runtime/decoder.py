"""Pure parser for 21-byte FC report prefixes; no device I/O.
"""
import math
import struct


def decode(frame):
    if type(frame) not in (bytes, bytearray) or len(frame) != 21 or frame[0] != 0xfc:
        return None
    value = frame[1:]
    kind = value[0]
    if kind == 4:
        orientation = struct.unpack_from('<3f', value, 2)
        if not all(math.isfinite(x) for x in orientation) or sum(x*x for x in orientation) > 1.0001:
            return None
        return {'kind': 'no-touch', 'buttons': value[1], 'orientation3': orientation,
                'complete_sensor_report': False, 'physical_axes_validated': False}
    if kind in (5, 6):
        # The one/two-contact block is complete; orientation is not.
        contacts = kind & 3
        size = (0, 13, 20)[contacts]
        touch = bytes([contacts]) + bytes(value[1:size])
        if len(touch) != size or touch[2] != 0x32:
            return None
        signed = lambda v: v - 4096 if v & 2048 else v
        lo, packed, hi = touch[6:9]
        return {'kind': 'one-touch' if contacts == 1 else 'two-touch', 'buttons': touch[1],
                'x': signed(lo | ((packed & 15) << 8)),
                'y': signed((packed >> 4) | (hi << 4)),
                'state': touch[12] & 7, 'clock': touch[3] | touch[4] << 8,
                'complete_sensor_report': False, 'physical_axes_validated': False}
    return None
