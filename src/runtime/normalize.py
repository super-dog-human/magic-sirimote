"""Normalization of observed FC21 prefixes; no output or device access.

The orientation candidate is incomplete. Touch and button fields are
forwarded as complete legacy touch values, without manufacturing absent
motion bytes.
"""
from decoder import decode
from touch_coordinates import decode_touch


def normalize(frame):
    if type(frame) in (bytes, bytearray) and frame and frame[0] == 0xfc:
        value = bytes(frame[1:])
        if len(value) == 2 and value[0] == 0:
            return {'touch_value': value, 'orientation3': None, 'touch_active': False}
        if decode_touch(value) is not None:
            return {'touch_value': value, 'orientation3': None, 'touch_active': True}
    sample = decode(frame)
    if sample is None:
        return None
    if sample['kind'] == 'no-touch':
        return {'touch_value': bytes((0, sample['buttons'])),
                'orientation3': sample['orientation3'], 'touch_active': False}
    count = 1 if sample['kind'] == 'one-touch' else 2
    size = (0, 13, 20)[count]
    return {'touch_value': bytes((count,)) + bytes(frame[2:1+size]),
            'orientation3': None, 'touch_active': True}
