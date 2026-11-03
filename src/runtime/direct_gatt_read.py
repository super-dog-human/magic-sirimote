"""One-shot, injected, read-only GATT Feature candidate probe.

This class never connects/disconnects, pairs, sets reports, writes CCCD, or
changes sensor mode. The caller supplies its own GATT clientId and a freshly
confirmed exact target/adapter link plus a control-validity predicate. Calls:
getServices once; readDescriptorValues once for 2908; and, only when that
descriptor confirms F0/Feature at handle 30, readCharacteristicValues once for
2A4D. Every call has a five-second timeout. No retry or singular fallback.

Returned characteristic bytes are discarded after length/hash and a strictly
shaped mode candidate are derived. All candidates remain unverified; this
probe never sets wirelessReadVerified=True.
"""
from runtime_device import identity as device_identity
from dataclasses import dataclass
import hashlib
import math
import time


TARGET = device_identity().remote
ADAPTER = device_identity().adapter
BASE = "0000{}-0000-1000-8000-00805f9b34fb"
GET_SERVICES = "luna://com.webos.service.bluetooth2/gatt/getServices"
READ_DESCRIPTORS = "luna://com.webos.service.bluetooth2/gatt/readDescriptorValues"
READ_CHARACTERISTICS = "luna://com.webos.service.bluetooth2/gatt/readCharacteristicValues"
HID_SERVICE = BASE.format("1812")
REPORT_CHAR = BASE.format("2a4d")
REPORT_REFERENCE = BASE.format("2908")


@dataclass(frozen=True)
class DirectGattReadResult:
    status: str
    reason: str | None = None
    getServicesAttempts: int = 0
    descriptorReadAttempts: int = 0
    characteristicReadAttempts: int = 0
    reportLayout: str | None = None
    reportHandles: tuple | None = None
    metadataShape: dict | None = None
    reportReference: dict | None = None
    responseLength: int | None = None
    responseSha256: str | None = None
    modeCandidate: dict | None = None
    wirelessReadVerified: bool = False


def _uuid(value):
    if type(value) is not str:
        return None
    low = value.lower()
    if low in ("1812", "2a4d", "2908"):
        return low
    for short in ("1812", "2a4d", "2908"):
        if low == BASE.format(short):
            return short
    return None


def _handle(value):
    if type(value) is int and value > 0 and value <= 65535:
        return value
    if type(value) is str and value.isascii() and value.isdecimal() and len(value) <= 5:
        number = int(value)
        if 0 < number <= 65535:
            return number
    return None


def _mode_candidate(data):
    """Recognize only exact small candidate frames; never label verified."""
    if len(data) == 3 and data[0] in (0x00, 0xF0) and data[1] == 0xA0 and data[2] in (0, 1, 2):
        prefix = "zero" if data[0] == 0 else "F0"
        return {"framing": prefix + "-A0-mode", "mode": data[2], "status": "candidate_only"}
    if len(data) == 2 and data[0] == 0xA0 and data[1] in (0, 1, 2):
        return {"framing": "A0-mode", "mode": data[1], "status": "candidate_only"}
    return None


class DirectGattReadProbe:
    def __init__(self, call, clock=time.monotonic):
        self._call = call
        self._clock = clock
        self.used = False

    def _fail(self, reason, **counts):
        return DirectGattReadResult("attention", reason, **counts)

    def run(self, *, link, client_id, control_valid):
        """Consume once. ``control_valid`` is bool/callable, rechecked each step."""
        if self.used:
            return self._fail("probe instance already used")
        self.used = True
        if not isinstance(link, dict) or set(link) != {
            "remote", "adapter", "generation", "connected", "connecting", "paired"
        }:
            return self._fail("invalid confirmed-link record")
        if (link["remote"] != TARGET or link["adapter"] != ADAPTER or
                type(link["generation"]) is not int or link["generation"] <= 0 or
                link["connected"] is not True or link["connecting"] is not False or
                link["paired"] is not True):
            return self._fail("link is not the exact connected, paired target/adapter")
        if (type(client_id) is not str or not client_id.isascii() or
                not client_id.isdecimal() or not 0 < len(client_id) <= 5 or
                not 1 <= int(client_id) <= 65535):
            return self._fail("invalid caller-owned clientId")

        counts = {"getServicesAttempts": 0, "descriptorReadAttempts": 0,
                  "characteristicReadAttempts": 0}
        started = self._now()
        if started is None:
            return self._fail("invalid monotonic clock", **counts)

        if not self._control_ok(control_valid):
            return self._fail("control invalid before getServices", **counts)
        counts["getServicesAttempts"] = 1
        services_reply, ended = self._invoke(GET_SERVICES, {"address": TARGET, "subscribe": False}, started)
        if services_reply is None:
            return self._fail("getServices failed, timed out, or clock invalid", **counts)
        if not self._reply_ok(services_reply) or not self._identity(services_reply, client_id):
            return self._fail("getServices rejected or identity mismatch", **counts)
        selected = self._select_report_29(services_reply)
        if selected is None:
            return self._fail("Report layout or 2908 handle is ambiguous/unknown", **counts,
                              metadataShape=self._report_shape(services_reply))
        layout, handles, metadata_shape = selected
        metadata = {"handle": 30, "reportId": 0xF0, "reportType": 3,
                    "status": "verified_descriptor_metadata"}

        if not self._control_ok(control_valid):
            return self._fail("control invalid before Report Reference read", **counts)
        counts["descriptorReadAttempts"] = 1
        params = {"clientId": client_id, "service": HID_SERVICE,
                  "characteristic": REPORT_CHAR, "descriptors": [REPORT_REFERENCE]}
        descriptor_reply, ended2 = self._invoke(READ_DESCRIPTORS, params, ended)
        if descriptor_reply is None:
            return self._fail("Report Reference read failed/uncertain", **counts)
        if not self._reply_ok(descriptor_reply) or not self._identity(descriptor_reply, client_id):
            return self._fail("Report Reference read rejected or identity mismatch", **counts)
        if not self._descriptor_f0_verified(descriptor_reply):
            # Preserve only bounded shape metadata; never carry descriptor bytes onward.
            shape = self._descriptor_shape(descriptor_reply)
            return self._fail("Report Reference did not verify handle 30 as F0/Feature",
                              **counts, reportLayout=layout, reportHandles=handles,
                              metadataShape=metadata_shape, reportReference=shape)

        if not self._control_ok(control_valid):
            return self._fail("control invalid before characteristic read", **counts,
                              reportLayout=layout, reportHandles=handles,
                              metadataShape=metadata_shape, reportReference=metadata)
        counts["characteristicReadAttempts"] = 1
        params = {"clientId": client_id, "service": HID_SERVICE,
                  "characteristics": [REPORT_CHAR]}
        char_reply, ended3 = self._invoke(READ_CHARACTERISTICS, params, ended2)
        if char_reply is None:
            return self._fail("characteristic read failed/uncertain", **counts,
                              reportLayout=layout, reportHandles=handles,
                              metadataShape=metadata_shape, reportReference=metadata)
        if not self._reply_ok(char_reply) or not self._identity(char_reply, client_id):
            return self._fail("characteristic read rejected or identity mismatch", **counts,
                              reportLayout=layout, reportHandles=handles,
                              metadataShape=metadata_shape, reportReference=metadata)
        candidate = self._extract_candidate(char_reply)
        if candidate is None:
            return self._fail("characteristic response was not exactly one 2A4D/handle-29 value",
                              **counts, reportLayout=layout, reportHandles=handles,
                              metadataShape=metadata_shape,
                              reportReference=metadata)
        data = candidate
        return DirectGattReadResult(
            "read_returned", **counts, reportLayout=layout, reportHandles=handles,
            metadataShape=metadata_shape, reportReference=metadata, responseLength=len(data),
            responseSha256=hashlib.sha256(bytes(data)).hexdigest(),
            modeCandidate=_mode_candidate(data), wirelessReadVerified=False)

    def _invoke(self, uri, params, previous):
        start = self._now()
        if start is None or start < previous or start - previous > 5:
            return None, None
        try:
            reply = self._call(uri, params, timeout=5)
        except Exception:
            return None, None
        end = self._now()
        if end is None or end < start or end - start > 5:
            return None, None
        return reply, end

    def _now(self):
        try:
            value = self._clock()
            return float(value) if type(value) in (int, float) and math.isfinite(value) else None
        except Exception:
            return None

    @staticmethod
    def _control_ok(control):
        try:
            value = control() if callable(control) else control
            return value is True
        except Exception:
            return False

    @staticmethod
    def _reply_ok(reply):
        return type(reply) is dict and reply.get("returnValue") is True

    @staticmethod
    def _identity(reply, client_id):
        return (type(reply.get("address")) is str and reply["address"].lower() == TARGET and
                type(reply.get("adapterAddress")) is str and reply["adapterAddress"].lower() == ADAPTER and
                ("clientId" not in reply or reply["clientId"] == client_id))

    @staticmethod
    def _select_report_29(reply):
        services = reply.get("services")
        if type(services) is not list or len(services) > 64:
            return None
        hid = [s for s in services if type(s) is dict and _uuid(s.get("service")) == "1812"]
        if len(hid) != 1:
            return None
        chars = hid[0].get("characteristics")
        if type(chars) is not list or len(chars) > 64:
            return None
        reports = [c for c in chars if type(c) is dict and _uuid(c.get("characteristic")) == "2a4d"]
        handles = [_handle(c.get("instanceId")) for c in reports]
        if any(h is None for h in handles):
            return None
        handles = tuple(sorted(handles))
        if handles == (29,):
            layout = "merged-parent-29"
        elif handles == (29, 32, 35):
            layout = "distinct-first-29"
        else:
            return None
        shape = DirectGattReadProbe._report_shape(reply)
        ref_handles = shape["reportReferenceDescriptorHandles"]
        if layout == "merged-parent-29":
            # Public merged getServices may expose the last reference only (37),
            # while the UUID-based descriptor read can still resolve native 30.
            if (not ref_handles or len(ref_handles) > 3 or len(set(ref_handles)) != len(ref_handles) or
                    any(h not in (30, 33, 37) for h in ref_handles)):
                return None
        else:
            first = next(c for c in reports if _handle(c.get("instanceId")) == 29)
            descs = first.get("descriptors")
            if type(descs) is not list or len(descs) > 16:
                return None
            first_refs = [d for d in descs
                          if type(d) is dict and _uuid(d.get("descriptor")) == "2908"]
            if len(first_refs) != 1 or _handle(first_refs[0].get("instanceId")) != 30:
                return None
        return layout, handles, shape

    @staticmethod
    def _report_shape(reply):
        """Bounded service metadata only; never copy descriptor values/payloads."""
        services = reply.get("services")
        if type(services) is not list or len(services) > 64:
            return {"serviceCount": None, "hidServiceCount": None,
                    "reportHandles": [], "reportReferenceDescriptorHandles": [],
                    "reportReferenceDescriptorCount": 0}
        hid = [s for s in services if type(s) is dict and _uuid(s.get("service")) == "1812"]
        report_handles = []
        ref_handles = []
        ref_count = 0
        for service in hid[:2]:
            chars = service.get("characteristics")
            if type(chars) is not list or len(chars) > 64:
                continue
            for char in chars:
                if type(char) is not dict or _uuid(char.get("characteristic")) != "2a4d":
                    continue
                handle = _handle(char.get("instanceId"))
                report_handles.append(handle)
                descs = char.get("descriptors")
                if type(descs) is not list or len(descs) > 16:
                    continue
                for desc in descs:
                    if type(desc) is dict and _uuid(desc.get("descriptor")) == "2908":
                        ref_count += 1
                        ref_handles.append(_handle(desc.get("instanceId")))
        return {"serviceCount": len(services), "hidServiceCount": len(hid),
                "reportHandles": report_handles[:8],
                "reportReferenceDescriptorHandles": ref_handles[:8],
                "reportReferenceDescriptorCount": min(ref_count, 16)}

    @staticmethod
    def _descriptor_f0_verified(reply):
        values = reply.get("values")
        if type(values) is not list or not 1 <= len(values) <= 16 or any(type(v) is not dict for v in values):
            return False
        refs = [v for v in values if _uuid(v.get("descriptor")) == "2908"]
        # Other returned descriptors (e.g. CCCD 36) are ignored. A different
        # Report Reference handle or duplicate match makes selection ambiguous.
        if len(refs) != 1 or _handle(refs[0].get("instanceId")) != 30:
            return False
        item = refs[0]
        data = item.get("value", {}).get("bytes") if type(item.get("value")) is dict else None
        return (type(data) is list and
                len(data) == 2 and all(type(b) is int and 0 <= b <= 255 for b in data) and
                data == [0xF0, 3])

    @staticmethod
    def _descriptor_shape(reply):
        values = reply.get("values")
        if type(values) is not list:
            return {"container": type(values).__name__, "count": None}
        return {"container": "list", "count": min(len(values), 16),
                "entries": [{"descriptor": _uuid(v.get("descriptor")) if type(v) is dict else None,
                             "handle": _handle(v.get("instanceId")) if type(v) is dict else None,
                             "byteCount": (len(v.get("value", {}).get("bytes"))
                                           if type(v) is dict and type(v.get("value")) is dict and
                                           type(v["value"].get("bytes")) is list else None)}
                            for v in values[:16]]}

    @staticmethod
    def _extract_candidate(reply):
        values = reply.get("values")
        if type(values) is not list or not 1 <= len(values) <= 16 or any(type(v) is not dict for v in values):
            return None
        reports = [v for v in values if _uuid(v.get("characteristic")) == "2a4d"]
        # A plural reply containing another Report UUID instance is ambiguous;
        # ignore unrelated characteristics without retaining their value data.
        if len(reports) != 1 or _handle(reports[0].get("instanceId")) != 29:
            return None
        item = reports[0]
        value = item.get("value")
        if type(value) is not dict:
            return None
        data = value.get("bytes")
        if (type(data) is not list or not 0 < len(data) <= 209 or
                any(type(b) is not int or not 0 <= b <= 255 for b in data)):
            return None
        return data
