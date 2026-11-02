"""Offline normalization of observed FC21 prefixes; no output or device access.

The orientation candidate is incomplete. Touch and button fields are forwarded
as complete legacy touch values, without manufacturing absent motion bytes.
"""
from decoder import decode


def normalize(frame):
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
