"""Pure bounded REL packet grouping candidate; no device or I/O operations."""
import struct

_RECORD = struct.Struct('=iiHHi')
_MAX_INPUT = 2**31 - 1
_MAX_REL_RECORDS = 128
_REL_PER_GROUP = 10
_MAX_GROUPS = (_MAX_REL_RECORDS + _REL_PER_GROUP - 1) // _REL_PER_GROUP
_MAX_PACKET_RECORDS = _MAX_REL_RECORDS + _MAX_GROUPS
_MAX_PACKET_BYTES = _MAX_PACKET_RECORDS * _RECORD.size

class RelativePacketBudgetExceeded(ValueError):
    """Valid integer motion exceeds the fixed one-frame output budget."""


def _axis_record_count(value: int) -> int:
    return (abs(value) + 14) // 15


def _axis_fragments(value: int, code: int):
    sign = 1 if value > 0 else -1
    remaining = abs(value)
    while remaining:
        amount = min(15, remaining)
        yield (2, code, sign * amount)
        remaining -= amount


def _pack(records) -> bytes:
    return b''.join(_RECORD.pack(0, 0, kind, code, value)
                    for kind, code, value in records)


def encode_grouped_relative_batch(dx: int, dy: int) -> bytes:
    """Encode interleaved signed axis chunks, groups <=10, SYN each.

    Rejects non-exact integers, zero vectors, int32 overflow, and more than
    128 REL records before constructing or encoding any packet records.
    Future callers should deliver the returned complete batch in one write.
    """
    if type(dx) is not int or type(dy) is not int:
        raise TypeError('exact integer deltas required')
    if dx == 0 and dy == 0:
        raise ValueError('zero relative batch rejected')
    if abs(dx) > _MAX_INPUT or abs(dy) > _MAX_INPUT:
        raise ValueError('int32 relative delta overflow')
    rel_count = _axis_record_count(dx) + _axis_record_count(dy)
    if rel_count > _MAX_REL_RECORDS:
        raise RelativePacketBudgetExceeded('relative record budget exceeded')

    # Avoid explicitly sending the whole horizontal leg before the vertical
    # leg. This does not claim that native acceleration preserves ray geometry.
    xparts=list(_axis_fragments(dx,0));yparts=list(_axis_fragments(dy,1))
    fragments=[]
    for index in range(max(len(xparts),len(yparts))):
        if index<len(xparts):fragments.append(xparts[index])
        if index<len(yparts):fragments.append(yparts[index])
    records = []
    for start in range(0, len(fragments), _REL_PER_GROUP):
        records.extend(fragments[start:start + _REL_PER_GROUP])
        records.append((0, 0, 0))
    packet = _pack(records)
    if len(records) > _MAX_PACKET_RECORDS or len(packet) > _MAX_PACKET_BYTES:
        raise AssertionError('fixed grouped packet bound violated')
    return packet


def encode_neutral_cursor_flush() -> bytes:
    """Return REL_X +1, REL_X -1, SYN: 48 bytes and zero signed net delta."""
    return _pack(((2, 0, 1), (2, 0, -1), (0, 0, 0)))
