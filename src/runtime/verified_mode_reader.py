"""TV-only experimental mode reader grounded in the audited0/1 round trip.

No sensor-mode SET, connections, CCCD or native input. The caller must own its
new HID/GATT session and serialize all Feature requests. Not a boot service or
a new recovery policy. The audited compatibility scope is this Main0241 /
Radio0107 Remote; revalidate if its firmware/identity/protocol changes.
"""
import hashlib
import math
import time
from direct_gatt_read import (DirectGattReadProbe, TARGET, ADAPTER,
                              READ_CHARACTERISTICS, HID_SERVICE, REPORT_CHAR,
                              _mode_candidate)

EVIDENCE_SHA256 = 'e8d07fa2d7c63683533593c91dbdbf701d3259d025ba76f302aee7c5f924a6e9'
SET_REPORT = 'luna://com.webos.service.bluetooth2/hid/internal/setReport'


class VerifiedModeReader:
    def __init__(self, call, *, audited_evidence_sha256, exclusive_feature_access,
                 clock=time.monotonic):
        if audited_evidence_sha256 != EVIDENCE_SHA256 or exclusive_feature_access is not True:
            raise ValueError('Audited evidence and serialized exclusive Feature access required')
        self.call, self.clock = call, clock
        self.link = self.client_id = self.control_valid = None
        self.used_bind = self.closed = self.inflight = False
        self.selector_attempts = self.read_attempts = 0
        self.reference_verified = False
        self.last_time = None
        self.reason = None

    def bind(self, *, link, client_id, owned_hid, owned_gatt, control_valid):
        if self.used_bind or self.closed:
            self.closed = True
            raise RuntimeError('One owned connection generation per reader')
        self.used_bind = True
        if (owned_hid is not True or owned_gatt is not True or not callable(control_valid)
                or type(link) is not dict or set(link) != {'remote','adapter','generation','connected','connecting','paired'}
                or link['remote'] != TARGET or link['adapter'] != ADAPTER
                or type(link['generation']) is not int or link['generation'] <= 0
                or link['connected'] is not True or link['connecting'] is not False or link['paired'] is not True
                or type(client_id) is not str or not client_id.isascii() or not client_id.isdecimal()
                or not 1 <= len(client_id) <= 5 or not 1 <= int(client_id) <= 65535):
            self.closed = True
            raise ValueError('Exact new owned target and caller-owned GATT client required')
        self.link, self.client_id, self.control_valid = dict(link), client_id, control_valid

    def _check(self):
        if self.closed or self.link is None or self.control_valid() is not True:
            raise RuntimeError('Owned session/control no longer valid')
        now = self.clock()
        if (type(now) not in (int,float) or not math.isfinite(now)
                or (self.last_time is not None and now < self.last_time)):
            raise RuntimeError('Non-finite or reversed clock')
        self.last_time = now
        return now

    def read(self, generation):
        if self.inflight:
            self.closed = True
            raise RuntimeError('Concurrent Feature access rejected')
        self.inflight = True
        try:
            started = self._check()
            if type(generation) is not int or generation != self.link['generation']:
                raise RuntimeError('Stale connection generation')
            if self.selector_attempts == 0:
                self.selector_attempts = 1
                ack = self.call(SET_REPORT, {'address':TARGET,'reportType':'feature',
                                             'reportData':[240,240,160]}, timeout=5)
                if type(ack) is not dict or ack.get('returnValue') is not True:
                    raise RuntimeError('Read-selector SET not acknowledged; no retry')
                for key,expected in (('address',TARGET),('adapterAddress',ADAPTER)):
                    if key in ack and (type(ack[key]) is not str or ack[key].lower() != expected):
                        raise RuntimeError('Selector reply identity differs')
                self._check()
                initial = DirectGattReadProbe(self.call, clock=self.clock).run(
                    link=self.link, client_id=self.client_id, control_valid=self.control_valid)
                self.read_attempts += initial.characteristicReadAttempts
                if initial.status != 'read_returned' or initial.reportReference != {
                        'handle':30,'reportId':240,'reportType':3,'status':'verified_descriptor_metadata'}:
                    raise RuntimeError('Live F0/Feature reference or baseline read not confirmed')
                candidate = initial.modeCandidate
                digest = initial.responseSha256
                self.reference_verified = True
            else:
                if not self.reference_verified:
                    raise RuntimeError('Unverified or failed reference; no read retry')
                self._check()
                self.read_attempts += 1
                reply = self.call(READ_CHARACTERISTICS,
                                  {'clientId':self.client_id,'service':HID_SERVICE,
                                   'characteristics':[REPORT_CHAR]}, timeout=5)
                if (not DirectGattReadProbe._reply_ok(reply)
                        or not DirectGattReadProbe._identity(reply, self.client_id)):
                    raise RuntimeError('Mode response identity or API result differs')
                data = DirectGattReadProbe._extract_candidate(reply)
                candidate = None if data is None else _mode_candidate(data)
                digest = None if data is None else hashlib.sha256(bytes(data)).hexdigest()
            ended = self._check()
            if ended-started > (25 if self.read_attempts == 1 else 10):
                raise RuntimeError('Mode read exceeded bounded validation window')
            if candidate not in ({'framing':'A0-mode','mode':0,'status':'candidate_only'},
                                  {'framing':'A0-mode','mode':1,'status':'candidate_only'}):
                raise RuntimeError('Unvalidated mode/framing; no guessed interpretation')
            return {'generation':generation,'mode':candidate['mode'],'observedAt':ended,
                    'verification':'live-reference + audited UART-correlated API format',
                    'responseSha256':digest,'evidenceSha256':EVIDENCE_SHA256}
        except Exception as error:
            self.closed = True
            self.reason = type(error).__name__ + ': ' + str(error)[:180]
            raise
        finally:
            self.inflight = False

    def controller_event(self, purpose, generation):
        if purpose not in ('baseline','enabled','cleanup'):
            raise ValueError('Explicit lifecycle read purpose required')
        value = self.read(generation)
        event = {'type':{'baseline':'sensor_baseline','enabled':'sensor_verified',
                         'cleanup':'sensor_cleanup_verified'}[purpose],
                 'generation':generation,'ok':True}
        if purpose == 'enabled':event['enabled'] = value['mode'] == 1
        else:event['value'] = value['mode']
        return event

    def summary(self):
        return {'closed':self.closed,'reason':self.reason,'selectorAttempts':self.selector_attempts,
                'characteristicReadAttempts':self.read_attempts,'referenceVerified':self.reference_verified,
                'sensorModeSets':0,'cccdWrites':0,'connectionOperations':0,'inputWrites':0,
                'rawAttTraceCaptured':False,'productionRecoveryPolicyImplemented':False}

    def close(self, reason='session-ended'):
        self.closed = True
        self.reason = reason
