"""FC hidraw frame demux using the audited pure decoders.

Hidraw includes report ID FC. The downstream touch/compact decoders consume
the value bytes after that prefix. This module does no I/O, sensor
activation, Bluetooth/CCCD work, or output injection.
"""
from collections import Counter

from motion_report import decode_compact_motion
from touch_coordinates import decode_touch

REPORT_ID = 0xFC
MAX_REPORT_BYTES = 64
MAX_REPORTS = 4096
TOUCH_REPORT_LENGTHS = {14, 21}       # FC + ATT values of 13 / 20 bytes
MOTION_REPORT_LENGTHS = {27, 38, 45}  # FC + compact values of 26 / 37 / 44 bytes


def demux_report(report):
    """Return a transient decoder payload only for a fully valid known frame.

    Returned bytes contain neither the FC prefix nor a copy saved by this
    module. Callers can pass them to the existing touch/gyro input session.
    """
    # The caller supplies one complete result of one hidraw read. Never split,
    # join, or attempt byte-stream reassembly here.
    if type(report) is not bytes or not 1 <= len(report) <= MAX_REPORT_BYTES:
        return None
    if report[0] != REPORT_ID:
        return None
    value = report[1:]
    if len(report) in TOUCH_REPORT_LENGTHS:
        return value if decode_touch(value) is not None else None
    if len(report) in MOTION_REPORT_LENGTHS:
        return value if decode_compact_motion(value) is not None else None
    return None


class FrameDemuxSummary:
    """Aggregate counts only; never retain a report or decoded sample."""
    def __init__(self, max_reports=MAX_REPORTS):
        if type(max_reports) is not int or not 1 <= max_reports <= MAX_REPORTS:
            raise ValueError('bounded report count required')
        self.max_reports = max_reports
        self.total = 0
        self.accepted = Counter()
        self.rejected = Counter()
        self.other = 0
        self.decoder_errors = 0
        self.closed = False
        self.close_reason = None

    def feed(self, report):
        if self.closed:
            return None
        if self.total >= self.max_reports:
            self.close('report-budget')
            return None
        self.total += 1
        shape = 'invalid'
        if type(report) is bytes and report and report[0] == REPORT_ID:
            shape = f'fc:{len(report)}'
        try:
            payload = demux_report(report)
        except Exception:
            self.decoder_errors += 1
            if shape in ('fc:14', 'fc:21', 'fc:27', 'fc:38', 'fc:45'):
                self.rejected[shape] += 1
            else:
                self.other += 1
            self.close('decoder-exception')
            return None
        if payload is None:
            if shape in ('fc:14', 'fc:21', 'fc:27', 'fc:38', 'fc:45'):
                self.rejected[shape] += 1
            else:
                self.other += 1
            return None
        self.accepted[shape] += 1
        return payload

    def close(self, reason):
        if not self.closed:
            self.closed = True
            self.close_reason = str(reason)[:48]

    def summary(self):
        return {
            'totalReports': self.total,
            'acceptedByShape': dict(sorted(self.accepted.items())),
            'rejectedByShape': dict(sorted(self.rejected.items())),
            'otherOrUnknown': self.other,
            'decoderErrors': self.decoder_errors,
            'maxReports': self.max_reports,
            'closed': self.closed,
            'closeReason': self.close_reason,
            'rawPayloadStored': False,
            'outputCallbacks': 0,
            'sensorCommands': 0,
            'directionOrMotionClaims': False,
        }
