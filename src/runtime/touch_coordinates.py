"""Candidate gen-1 touch decoder. No device, network, audio or input injection.

Consumes ATT value bytes WITHOUT the hidraw FC report-id prefix. Signed 12-bit
encoding is reported by open-appleremote on A1962; validate on this A1513 before
connecting any output to a real cursor. Only known touch shapes are accepted.
"""


def signed12(value):
    assert type(value) is int and 0 <= value < 4096
    return value - 4096 if value & 2048 else value


def decode_touch(value):
    if type(value) not in (bytes, bytearray):
        return None
    if len(value) not in (13, 20) or value[0] not in (1, 2):
        return None
    count = value[0]
    if len(value) != 6 + 7 * count or value[2] != 0x32:
        return None
    fingers = []
    for index in range(count):
        offset = 6 + 7 * index
        low, packed, high = value[offset:offset + 3]
        fingers.append({'x': signed12(low | ((packed & 15) << 8)),
                        'y': signed12((packed >> 4) | (high << 4)),
                        'state': value[offset + 6] & 7})
    return {'clock': value[3] | (value[4] << 8), 'buttons': value[1], 'fingers': fingers}


class TouchSummary:
    """Bounded semantic results only; never store unknown/audio payloads."""
    def __init__(self):
        self.summary = {'inputValues': 0, 'touchFrames': 0, 'nonTouchValues': 0,
                        'oneFingerFrames': 0, 'twoFingerFrames': 0, 'activeFrames': 0,
                        'xRange': None, 'yRange': None, 'stateCounts': [0] * 8,
                        'coordinateChanges': 0, 'candidateSamples': [], 'samplesDropped': 0,
                        'candidateEncoding': 'signed-12-bit; not yet validated on this A1513'}
        self.previous = None

    def feed(self, value, elapsed_ms):
        self.summary['inputValues'] += 1
        decoded = decode_touch(value)
        if decoded is None:
            self.summary['nonTouchValues'] += 1
            self.previous = None
            return None
        self.summary['touchFrames'] += 1
        self.summary['oneFingerFrames' if len(decoded['fingers']) == 1 else 'twoFingerFrames'] += 1
        for finger in decoded['fingers']:
            self.summary['stateCounts'][finger['state']] += 1
            if finger['state'] not in (3, 4):
                continue
            self.summary['activeFrames'] += 1
            for key, axis in (('xRange', 'x'), ('yRange', 'y')):
                old = self.summary[key]
                coordinate = finger[axis]
                self.summary[key] = [coordinate, coordinate] if old is None else [min(old[0], coordinate), max(old[1], coordinate)]
        first = decoded['fingers'][0]
        current = (first['x'], first['y'])
        if self.previous is not None and current != self.previous:
            self.summary['coordinateChanges'] += 1
        self.previous = current if first['state'] in (3, 4) and len(decoded['fingers']) == 1 else None
        # A few evenly spaced positions are enough to assess plausibility,
        # without retaining the full trajectory or any input/audio bytes.
        if first['state'] in (3, 4) and self.summary['touchFrames'] % 50 == 1:
            if len(self.summary['candidateSamples']) < 12:
                self.summary['candidateSamples'].append({'ms': int(elapsed_ms), 'fingers': len(decoded['fingers']),
                                                        'x': first['x'], 'y': first['y'], 'state': first['state']})
            else:
                self.summary['samplesDropped'] += 1
        return decoded


class RelativeTouch:
    """Offline candidate only. No real cursor output; reset across lifts/gaps."""
    def __init__(self, gain=0.5):
        assert type(gain) in (int, float) and 0 < gain <= 2
        self.gain, self.previous = gain, None

    def feed(self, value):
        decoded = decode_touch(value)
        old, self.previous = self.previous, None
        if decoded is None or len(decoded['fingers']) != 1 or decoded['buttons']:
            return None
        finger = decoded['fingers'][0]
        if finger['state'] not in (3, 4):
            return None
        current = (finger['x'], finger['y'], decoded['clock'])
        self.previous = current
        if old is None or finger['state'] == 3:
            return None
        dx, dy = current[0] - old[0], current[1] - old[1]
        ticks = (current[2] - old[2]) & 65535
        if not 0 < ticks <= 200 or max(abs(dx), abs(dy)) > 300:
            return None
        return {'dx': dx * self.gain, 'dy': -dy * self.gain}
