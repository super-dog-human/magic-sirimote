"""One-shot activation for an already-owned, already-connected Remote generation.

No connect, pairing, discovery, or link release occurs here. The required live
CCCD metadata is caller-supplied and pinned to the measured merged public
Report layout (parent 0x001d, input-report characteristic 0x0023, CCCD 0x0024).
That is an API selection distinction, not a claim that public parent 29 is the
native input handle 35. All report/API framing remains limited to the existing
audited VerifiedModeReader. Any uncertainty stops in ATTENTION; no rollback or
retry is attempted here. Its [F0,F0,A0] SET changes a volatile read cursor;
the old cursor is unknown and is not restored. Tests use explicitly marked
simulation adapters.
"""
from types import MappingProxyType
from threading import Lock
import math
import time

from lifecycle import Controller
from cleanup_proof import CleanupProof
from direct_gatt_read import (TARGET, ADAPTER, HID_SERVICE, REPORT_CHAR,
                              REPORT_REFERENCE, GET_SERVICES, READ_DESCRIPTORS,
                              READ_CHARACTERISTICS)
from pumping_luna_client import BASE, LunaCallError, PumpingLunaClient
from verified_mode_reader import VerifiedModeReader, SET_REPORT, EVIDENCE_SHA256

CCCD = "00002902-0000-1000-8000-00805f9b34fb"
_PROXY_TYPE = type(MappingProxyType({}))
_BINDING_FIELDS = {
    "clientId", "generation", "service", "characteristic", "descriptor",
    "characteristicHandle", "descriptorHandle", "baselineFlags",
    "enableAttempted", "metadataLiveVerified", "selectionMode",
    "expectedInputCharacteristicHandle",
}
_CCCD_READ = "gatt/readDescriptorValues"
_CCCD_WRITE = "gatt/writeDescriptorValue"
_INIT = "hid/internal/setReport"


class PumpingGattActivationClient(PumpingLunaClient):
    """Strict activation-only API allowlist over the bounded monitor-pumping client."""
    def __init__(self, *, generation, client_id, metadata_live_verified, **kwargs):
        if (type(generation) is not int or generation <= 0
                or metadata_live_verified is not True
                or type(client_id) is not str or not client_id.isascii()
                or not client_id.isdecimal() or not 1 <= len(client_id) <= 5
                or not 1 <= int(client_id) <= 65535):
            raise ValueError("Existing exact generation/client and live metadata required")
        super().__init__(**kwargs)
        self.generation, self.client_id = generation, client_id
        self.activation_attempts = {"cccd_write": 0, "init": 0, "selector": 0, "sensor": 0}
        self.read_counts = {"cccd_read": 0, "reference": 0, "mode": 0, "services": 0}

    @staticmethod
    def _exact(value, expected):
        if type(value) is not type(expected):
            return False
        if type(expected) is dict:
            return set(value) == set(expected) and all(
                PumpingGattActivationClient._exact(value[k], v) for k, v in expected.items())
        if type(expected) is list:
            return len(value) == len(expected) and all(
                PumpingGattActivationClient._exact(a, b) for a, b in zip(value, expected))
        return value == expected

    def _validate_request(self, method, params, timeout):
        if type(method) is not str:
            raise ValueError("Exact activation API method required")
        if method.startswith(BASE):
            method = method[len(BASE):]
        reference_method = READ_DESCRIPTORS.removeprefix(BASE)
        selector_method = SET_REPORT.removeprefix(BASE)
        client = self.client_id
        common = {"clientId": client, "service": HID_SERVICE, "characteristic": REPORT_CHAR}
        policies = {
            "gatt/getServices": (5, {"address": TARGET, "subscribe": False}, "services"),
            "gatt/readCharacteristicValues": (5, {"clientId": client, "service": HID_SERVICE,
                                                    "characteristics": [REPORT_CHAR]}, "mode"),
            _CCCD_READ + ":cccd": (6, {**common, "descriptors": [CCCD]}, "cccd_read"),
            reference_method + ":report-reference": (5, {**common, "descriptors": [REPORT_REFERENCE]}, "reference"),
            _CCCD_WRITE: (6, {**common, "descriptor": CCCD, "value": {"bytes": [1, 0]}}, "cccd_write"),
            _INIT + ":init": (6, {"address": TARGET, "reportType": "feature", "reportData": [240, 175]}, "init"),
            selector_method + ":selector": (5, {"address": TARGET, "reportType": "feature", "reportData": [240, 240, 160]}, "selector"),
            _INIT + ":sensor": (6, {"address": TARGET, "reportType": "feature", "reportData": [240, 160, 1]}, "sensor"),
        }
        policy_key = method
        if method == _CCCD_READ and type(params) is dict:
            descriptors = params.get("descriptors")
            if descriptors == [CCCD]:
                policy_key += ":cccd"
            elif descriptors == [REPORT_REFERENCE]:
                policy_key += ":report-reference"
        elif method == _INIT and type(params) is dict:
            reports = params.get("reportData")
            if reports == [240, 175]:
                policy_key = _INIT + ":init"
            elif reports == [240, 240, 160]:
                policy_key = selector_method + ":selector"
            elif reports == [240, 160, 1]:
                policy_key = _INIT + ":sensor"
        if policy_key not in policies:
            raise ValueError("API outside already-owned settings activation allowlist")
        allowed, expected, category = policies[policy_key]
        if (not self._exact(params, expected) or type(timeout) not in (int, float)
                or not math.isfinite(timeout) or timeout != allowed):
            raise ValueError("Activation request shape/timeout mismatch")
        if category in self.activation_attempts:
            if self.activation_attempts[category]:
                raise LunaCallError("One-shot activation write already consumed")
            self.activation_attempts[category] = 1
        else:
            limit = 2 if category in ("cccd_read", "mode") else 1
            if self.read_counts[category] >= limit:
                raise LunaCallError("Activation read budget consumed")
            self.read_counts[category] += 1
        # Base is_write has one disconnect-oriented shared budget. This class
        # applies per-setting counters above and never exposes disconnect.
        return method, allowed, False


class OwnedSettingsActivation:
    def __init__(self, controller, proof, call, pump, mode_reader, cccd_binding, *,
                 clock=time.monotonic, simulation=False):
        self.controller, self.proof, self.call, self.pump = controller, proof, call, pump
        self.mode_reader = mode_reader
        self.cccd_binding = (MappingProxyType(dict(cccd_binding))
                             if type(cccd_binding) is _PROXY_TYPE else cccd_binding)
        self.clock, self.simulation = clock, simulation
        self.used = False
        self.lock = Lock()
        self._last_now = None
        self.attempts = {"cccdRead": 0, "cccdEnable": 0, "cccdVerify": 0,
                         "init": 0, "sensorBaseline": 0, "sensorEnable": 0,
                         "sensorVerify": 0}
        self.captured_cccd_baseline = None
        self.result = None

    def _valid_binding(self):
        c, reader, b = self.controller, self.mode_reader, self.cccd_binding
        if (type(b) is not _PROXY_TYPE or set(b) != _BINDING_FIELDS
                or type(b["clientId"]) is not str or b["clientId"] != reader.client_id
                or type(b["generation"]) is not int or b["generation"] != c.generation
                or type(b["service"]) is not str or b["service"] != HID_SERVICE
                or type(b["characteristic"]) is not str or b["characteristic"] != REPORT_CHAR
                or type(b["descriptor"]) is not str or b["descriptor"] != CCCD
                or type(b["characteristicHandle"]) is not int or b["characteristicHandle"] != 29
                or type(b["descriptorHandle"]) is not int or b["descriptorHandle"] != 36
                or b["baselineFlags"] is not None
                or type(b["enableAttempted"]) is not bool or b["enableAttempted"] is not False
                or type(b["metadataLiveVerified"]) is not bool or b["metadataLiveVerified"] is not True
                or type(b["selectionMode"]) is not str
                or b["selectionMode"] != "unique-cccd-in-merged-report"
                or type(b["expectedInputCharacteristicHandle"]) is not int
                or b["expectedInputCharacteristicHandle"] != 35):
            return False
        return True

    def _validate(self):
        c, reader = self.controller, self.mode_reader
        identity = self.proof.identity if type(self.proof) is CleanupProof else None
        if (type(c) is not Controller or type(self.proof) is not CleanupProof
                or identity.remote != TARGET or identity.adapter != ADAPTER
                or type(identity.generation) is not int or identity.generation != c.generation
                or self.proof.input_authorized is not True or self.proof.output_quiesced is not False
                or type(reader) is not VerifiedModeReader
                or not callable(self.pump) or not callable(self.call)
                or (type(self.call) is not PumpingGattActivationClient and self.simulation is not True)
                or type(self.simulation) is not bool
                or not callable(self.clock)
                or c.phase != "READ_CCCD_BASELINE" or type(c.generation) is not int or c.generation <= 0
                or c.owned_link is not True or c.authorized is not True or c.context_valid is not True
                or c.cccd_attempted is not False or c.sensor_attempted is not False or c.init_done is not False
                or reader.closed is not False or reader.reference_verified is not False
                or reader.used_bind is not True or reader.inflight is not False
                or type(reader.selector_attempts) is not int or reader.selector_attempts != 0
                or type(reader.read_attempts) is not int or reader.read_attempts != 0
                or reader.link.get("remote") != TARGET or reader.link.get("adapter") != ADAPTER
                or type(reader.link.get("generation")) is not int or reader.link["generation"] != c.generation
                or reader.link.get("connected") is not True or reader.link.get("connecting") is not False
                or reader.link.get("paired") is not True or reader.client_id is None
                or reader.call is not self.call or reader.control_valid != self.proof.check_continuity
                or reader.control_valid is None
                or not callable(reader.control_valid) or not self._valid_binding()):
            return False
        return True

    def _now(self):
        value = self.clock()
        if (type(value) not in (int, float) or not math.isfinite(value)
                or (self._last_now is not None and value < self._last_now)):
            raise RuntimeError("activation monotonic clock invalid")
        self._last_now = value
        return value

    def _guard(self):
        c, reader = self.controller, self.mode_reader
        if (c.phase in ("ATTENTION", "CLEANUP") or c.authorized is not True or c.context_valid is not True
                or c.generation != reader.link.get("generation") or reader.closed is not False
                or self.proof.check_continuity() is not True
                or self.proof.input_authorized is not True or self.proof.output_quiesced is not False
                or self.proof.identity.generation != c.generation
                or reader.control_valid() is not True):
            raise RuntimeError("activation context/link control invalid")
        self._now()

    def _call(self, method, params, timeout, *, attempt_key=None):
        self._guard()
        self.pump()
        self._guard()
        error = None
        reply = None
        try:
            if attempt_key is not None:
                if self.attempts[attempt_key] != 0:
                    raise RuntimeError("one-shot activation write already consumed")
                self.attempts[attempt_key] = 1
            reply = self.call(method, params, timeout=timeout)
        except BaseException as caught:
            error = caught
        try:
            self.pump()
            self._guard()
        except BaseException as caught:
            if error is None:
                error = caught
        if error is not None:
            raise error
        return reply

    def _event(self, kind, **values):
        event = {"type": kind, "generation": self.controller.generation, "ok": True, **values}
        actions = self.controller.handle(event, self._now())
        if self.controller.phase == "ATTENTION":
            raise RuntimeError("lifecycle rejected activation confirmation")
        return actions

    @staticmethod
    def _identity(reply, *, client_id=None, require_adapter=False):
        if (type(reply) is not dict or reply.get("returnValue") is not True
                or type(reply.get("address")) is not str or reply["address"].lower() != TARGET):
            return False
        if require_adapter and type(reply.get("adapterAddress")) is not str:
            return False
        if ("adapterAddress" in reply and (type(reply["adapterAddress"]) is not str
                                            or reply["adapterAddress"].lower() != ADAPTER)):
            return False
        return (client_id is None or "clientId" not in reply
                or (type(reply["clientId"]) is str and reply["clientId"] == client_id))

    def _cccd_flags(self, reply, expected):
        if not self._identity(reply, client_id=self.mode_reader.client_id, require_adapter=True):
            return False
        values = reply.get("values")
        if type(values) is not list or len(values) > 16:
            return False
        matches = [v for v in values if type(v) is dict
                   and type(v.get("descriptor")) is str
                   and v["descriptor"].lower() in (CCCD, "2902")]
        if len(matches) != 1:
            return False
        item = matches[0]
        handle = item.get("instanceId")
        if not (type(handle) is str and handle.isascii() and handle.isdecimal()
                and len(handle) <= 5 and int(handle) == 36):
            return False
        value = item.get("value")
        if type(value) is not dict or set(value) != {"bytes"}:
            return False
        data = value["bytes"]
        if (type(data) is not list or len(data) != 2
                or any(type(x) is not int or x < 0 or x > 255 for x in data)):
            return False
        flags = data[0] | (data[1] << 8)
        return flags == expected

    def _reader_event(self, purpose):
        original = self.mode_reader.call
        try:
            self.mode_reader.call = lambda method, params, timeout=5: self._call(method, params, timeout)
            self.attempts["sensorBaseline" if purpose == "baseline" else "sensorVerify"] += 1
            event = self.mode_reader.controller_event(purpose, self.controller.generation)
        finally:
            self.mode_reader.call = original
        if type(event) is not dict or event.get("ok") is not True:
            raise RuntimeError("verified mode reader did not confirm mode")
        if purpose == "baseline":
            actions = self._event("sensor_baseline", value=event.get("value"))
            if not any(getattr(a, "name", None) == "enable_sensor" for a in actions):
                raise RuntimeError("sensor baseline did not authorize enable")
        else:
            actions = self._event("sensor_verified", enabled=event.get("enabled"))
            if not any(getattr(a, "name", None) == "start_output" for a in actions):
                raise RuntimeError("sensor readback did not authorize output")

    def _write_ack(self, reply, *, feature=False):
        if feature:
            # The audited F0/AF and sensor-mode APIs can return only
            # returnValue; target binding is enforced by this live reader/link.
            if type(reply) is not dict or reply.get("returnValue") is not True:
                return False
            for key, expected in (("address", TARGET), ("adapterAddress", ADAPTER)):
                if key in reply and (type(reply[key]) is not str or reply[key].lower() != expected):
                    return False
            return True
        return self._identity(reply, client_id=self.mode_reader.client_id, require_adapter=True)

    def _attention(self, error):
        c = self.controller
        if self.attempts["init"] and not c.init_done:
            c.recovery_required.add("init_state")
        if c.phase != "ATTENTION":
            c._attention("settings activation uncertain: " + type(error).__name__)
        self.mode_reader.close("settings-activation-attention")
        self.result = {"status": "attention", "reason": type(error).__name__,
                       "originalFailure": type(error).__name__,
                       "simulated": self.simulation, "attempts": dict(self.attempts),
                       "capturedCccdBaseline": self.captured_cccd_baseline,
                       "writeAttempts": {"cccdEnable": self.attempts["cccdEnable"],
                           "init": self.attempts["init"], "sensorEnable": self.attempts["sensorEnable"]},
                       "modeReferenceVerified": self.mode_reader.reference_verified is True,
                       "recoveryRequiresFreshQuiescedProof": True,
                       "wirelessReadVerified": False, "active": False}
        return self.result

    def execute(self):
        if not self.lock.acquire(blocking=False):
            return {"status": "attention", "reason": "activation already running", "active": False}
        try:
            if self.used:
                return {"status": "attention", "reason": "activation already consumed", "active": False}
            self.used = True
            if not self._validate():
                return self._attention(ValueError("activation preconditions invalid"))
            try:
                # READ_CCCD_BASELINE: unique merged-parent metadata was pinned
                # before construction; read the actual current flags now.
                self.attempts["cccdRead"] = 1
                baseline = self._call(_CCCD_READ, {"clientId": self.mode_reader.client_id,
                    "service": HID_SERVICE, "characteristic": REPORT_CHAR, "descriptors": [CCCD]}, 6)
                if not self._cccd_flags(baseline, 0):
                    raise RuntimeError("CCCD baseline was not exact disabled handle 36")
                self.captured_cccd_baseline = 0
                actions = self._event("cccd_baseline", value=0)
                if not any(getattr(a, "name", None) == "write_cccd" for a in actions):
                    raise RuntimeError("CCCD baseline did not authorize enable")

                # ENABLE_CCCD and VERIFY_CCCD; consume intent before each write.
                cccd_write = {"clientId": self.mode_reader.client_id, "service": HID_SERVICE,
                    "characteristic": REPORT_CHAR, "descriptor": CCCD, "value": {"bytes": [1, 0]}}
                if not self._write_ack(self._call(_CCCD_WRITE, cccd_write, 6,
                        attempt_key="cccdEnable")):
                    self._event("cccd_enabled", ok=False)
                    raise RuntimeError("CCCD enable acknowledgement uncertain")
                actions = self._event("cccd_enabled")
                if not any(getattr(a, "name", None) == "read_cccd" for a in actions):
                    raise RuntimeError("CCCD acknowledgement did not authorize verification")
                self.attempts["cccdVerify"] = 1
                enabled = self._call(_CCCD_READ, {"clientId": self.mode_reader.client_id,
                    "service": HID_SERVICE, "characteristic": REPORT_CHAR, "descriptors": [CCCD]}, 6)
                if not self._cccd_flags(enabled, 1):
                    raise RuntimeError("CCCD enable readback was not exact handle 36 flags 1")
                actions = self._event("cccd_verified", value=1)
                if not any(getattr(a, "name", None) == "initialize" for a in actions):
                    raise RuntimeError("CCCD readback did not authorize initialization")

                # One audited F0/AF initialization after verified CCCD.
                if not self._write_ack(self._call(_INIT, {"address": TARGET,
                        "reportType": "feature", "reportData": [240, 175]}, 6,
                        attempt_key="init"), feature=True):
                    self._event("init_write_ok", ok=False)
                    raise RuntimeError("F0/AF acknowledgement uncertain")
                actions = self._event("init_write_ok")
                if not any(getattr(a, "name", None) == "read_sensor_mode" for a in actions):
                    raise RuntimeError("F0/AF acknowledgement did not authorize sensor baseline")

                self._reader_event("baseline")
                if not self._write_ack(self._call(_INIT, {"address": TARGET,
                        "reportType": "feature", "reportData": [240, 160, 1]}, 6,
                        attempt_key="sensorEnable"), feature=True):
                    self._event("sensor_enabled", ok=False)
                    raise RuntimeError("sensor-mode 1 acknowledgement uncertain")
                actions = self._event("sensor_enabled")
                if not any(getattr(a, "name", None) == "verify_sensor" for a in actions):
                    raise RuntimeError("sensor enable acknowledgement did not authorize readback")
                self._reader_event("enabled")
                cleanup_binding = {key: self.cccd_binding[key] for key in (
                    "clientId", "generation", "service", "characteristic", "descriptor",
                    "characteristicHandle", "descriptorHandle", "baselineFlags", "metadataLiveVerified")}
                # Replace the unverified metadata placeholder only after the
                # actual handle-36 descriptor read confirmed disabled flags.
                cleanup_binding["baselineFlags"] = 0
                cleanup_binding["enableAttempted"] = True
                self.result = {"status": "active", "active": True, "simulated": self.simulation,
                    "generation": self.controller.generation, "wirelessReadVerified": False,
                    "modeReferenceVerified": self.mode_reader.reference_verified is True,
                    "activationBinding": self.cccd_binding,
                    "cleanupBinding": MappingProxyType(cleanup_binding),
                    "modeReader": self.mode_reader, "attempts": dict(self.attempts)}
                return self.result
            except BaseException as error:
                result = self._attention(error)
                if not isinstance(error, Exception):
                    raise
                return result
        finally:
            self.lock.release()


__all__ = ("OwnedSettingsActivation", "PumpingGattActivationClient")
