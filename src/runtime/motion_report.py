"""Strict parser for Main 0241 compact CoreMotion FC values.

No-touch 26-byte values validated in a receive-only TV trial on 2026-10-17.
Combined one-touch 37-byte values validated in a receive-only trial that
day; two-touch 44-byte shape remains synthetic-test-only. Accepts complete
ATT values without FC report ID; performs no reassembly or speculative/audio
parsing. Does not label the six scaled values as gyro or acceleration, infer
physical axes, or produce input events. Callers must authenticate the
target/link/handle.
"""
import math
import struct
from touch_coordinates import decode_touch


def decode_compact_motion(value):
    if type(value) not in (bytes, bytearray) or len(value) < 2:
        return None
    # Only compact motion (0x04), with zero/one/two touch contacts. No expanded
    # mode, audio (0x10), unknown flag combinations, or trailing bytes.
    kind = value[0]
    if kind not in (4, 5, 6):
        return None
    contacts = kind & 3
    prefix_length = (2, 13, 20)[contacts]
    if len(value) != prefix_length + 24:
        return None
    touch = None
    if contacts:
        touch = decode_touch(bytes((contacts,)) + value[1:prefix_length])
        if touch is None:
            return None
    orientation = struct.unpack_from('<3f', value, prefix_length)
    # Firmware normalizes a four-component vector and transmits three with a
    # canonical sign. A unit-vector bound is a candidate sanity check, not proof
    # of a quaternion convention or a valid physical measurement.
    if not all(math.isfinite(n) for n in orientation):
        return None
    norm_squared = sum(n * n for n in orientation)
    if norm_squared > 1.0001:
        return None
    groups = struct.unpack_from('<6h', value, prefix_length + 12)
    return {'buttons': value[1], 'touch': touch,
            'orientation3': orientation, 'orientationNormSquared': norm_squared,
            'scaledVectorA': groups[:3], 'scaledVectorB': groups[3:],
            'format': 'Main0241 compact candidate; physical labels not validated'}


def decode_no_touch_orientation_prefix(value):
    """alternative only: complete 12-byte orientation inside a short value.

    Never call this a complete sensor report or apply it to touch-bearing values:
    with touch data, not all three floats fit in the same 20-byte prefix. No
    reconstruction of missing sensor bytes or quaternion component is performed.
    Actual prefix correspondence and axes need a new authorized observation.
    """
    if type(value) not in (bytes,bytearray) or len(value)!=20 or value[0]!=4:
        return None
    orientation=struct.unpack_from('<3f',value,2)
    if not all(math.isfinite(n) for n in orientation) or sum(n*n for n in orientation)>1.0001:
        return None
    return {'buttons':value[1],'orientation3':orientation,'completeSensorBlock':False,
            'missingSensorBytes':6,'touchBearing':False,'format':'unvalidated Main0241 no-touch compact prefix'}
