"""Explicit settings-only stop path for a used activation left in ATTENTION.

This can restore only this activation's attempted settings, on its still-owned
same-generation client, after independently confirmed input quiescence. It does
not change lifecycle phase, reactivate, or release HID/GATT ownership.
"""
from threading import Lock
import math
import time
from types import MappingProxyType

from direct_gatt_read import (TARGET, ADAPTER, HID_SERVICE, REPORT_CHAR,
                              READ_CHARACTERISTICS)
from lifecycle import Controller
from owned_settings_activation import OwnedSettingsActivation, CCCD
from pumping_luna_client import BASE, LunaCallError, PumpingLunaClient
from verified_mode_reader import VerifiedModeReader
from direct_gatt_read import DirectGattReadProbe, _mode_candidate
from cleanup_proof import CleanupProof

_PROXY_TYPE = type(MappingProxyType({}))
_SET_REPORT = "hid/internal/setReport"
_WRITE_CCCD = "gatt/writeDescriptorValue"
_READ_CCCD = "gatt/readDescriptorValues"


class PumpingGattPartialStopClient(PumpingLunaClient):
    """Exact stop-only policy: no enable, selector, init, connect, or release."""
    def __init__(self, *, generation, client_id, **kwargs):
        if (type(generation) is not int or generation <= 0
                or type(client_id) is not str or not client_id.isascii()
                or not client_id.isdecimal() or not 1 <= len(client_id) <= 5
                or not 1 <= int(client_id) <= 65535):
            raise ValueError("Exact owned generation/client required")
        super().__init__(**kwargs)
        self.generation, self.client_id = generation, client_id
        self.attempts = {"sensor0":0,"cccd0":0}
        self.reads = {"mode":0,"cccd":0}

    @staticmethod
    def _exact(value, expected):
        if type(value) is not type(expected): return False
        if type(expected) is dict:
            return set(value)==set(expected) and all(
                PumpingGattPartialStopClient._exact(value[k],v) for k,v in expected.items())
        if type(expected) is list:
            return len(value)==len(expected) and all(
                PumpingGattPartialStopClient._exact(a,b) for a,b in zip(value,expected))
        return value==expected

    def _validate_request(self, method, params, timeout):
        if type(method) is not str: raise ValueError("Exact stop method required")
        if method.startswith(BASE): method=method[len(BASE):]
        common={"clientId":self.client_id,"service":HID_SERVICE,"characteristic":REPORT_CHAR}
        mode_read={"clientId":self.client_id,"service":HID_SERVICE,
                   "characteristics":[REPORT_CHAR]}
        policies={
            _SET_REPORT:(6,{"address":TARGET,"reportType":"feature","reportData":[240,160,0]},"sensor0"),
            _WRITE_CCCD:(6,{**common,"descriptor":CCCD,"value":{"bytes":[0,0]}},"cccd0"),
            _READ_CCCD:(6,{**common,"descriptors":[CCCD]},"cccd-read"),
            READ_CHARACTERISTICS.removeprefix(BASE):(5,mode_read,"mode-read"),
        }
        if method not in policies: raise ValueError("API outside partial activation stop allowlist")
        allowed,expected,category=policies[method]
        if (not self._exact(params,expected) or type(timeout) not in (int,float)
                or not math.isfinite(timeout) or timeout!=allowed):
            raise ValueError("Exact stop payload/timeout required")
        counter = self.attempts if category in self.attempts else self.reads
        key = category if category in self.attempts else category.removesuffix("-read")
        limit = 1
        if counter[key]>=limit: raise LunaCallError("Partial stop operation already consumed")
        counter[key]+=1
        return method,allowed,False


class PartialActivationStop:
    """Single-use, proof-gated stop of settings after activation ATTENTION."""
    def __init__(self, activation, call, pump, context_valid, *, clock=time.monotonic,
                 simulation=False):
        self.activation,self.call,self.pump,self.context_valid=activation,call,pump,context_valid
        self.clock,self.simulation=clock,simulation
        self.lock=Lock();self.used=False;self._last_now=None
        self.attempts={"sensor0":0,"sensorModeRead":0,"cccd0":0,"cccdRead":0}
        self.result=None

    def _validate(self):
        a=self.activation
        if type(a) is not OwnedSettingsActivation or a.used is not True or type(a.result) is not dict:
            return False
        c,p,r,b=a.controller,a.proof,a.mode_reader,a.cccd_binding
        if (type(c) is not Controller or type(r) is not VerifiedModeReader
                or c.phase!="ATTENTION" or c.output_enabled is not False
                or type(p) is not CleanupProof or p is not a.proof
                or p.input_authorized is not False or p.output_quiesced is not True
                or p.identity.remote!=TARGET or p.identity.adapter!=ADAPTER
                or type(p.identity.generation) is not int or p.identity.generation!=c.generation
                or type(b) is not _PROXY_TYPE or b.get("clientId")!=r.client_id
                or b.get("generation")!=c.generation or b.get("metadataLiveVerified") is not True
                or type(a.captured_cccd_baseline) is not int or a.captured_cccd_baseline != 0
                or a.result.get("status")!="attention"
                or type(r) is not VerifiedModeReader or type(r.link) is not dict
                or r.link.get("remote")!=TARGET or r.link.get("adapter")!=ADAPTER
                or type(r.link.get("generation")) is not int or r.link["generation"]!=c.generation
                or r.link.get("connected") is not True or r.link.get("connecting") is not False
                or r.link.get("paired") is not True or r.used_bind is not True
                or r.inflight is not False
                or type(r.selector_attempts) is not int
                or type(a.attempts.get("cccdEnable")) is not int
                or a.attempts["cccdEnable"] not in (0,1)
                or type(a.attempts.get("sensorEnable")) is not int
                or a.attempts["sensorEnable"] not in (0,1)
                or not callable(self.call) or not callable(self.pump)
                or not callable(self.context_valid) or not callable(self.clock)
                or type(self.simulation) is not bool
                or (type(self.call) is not PumpingGattPartialStopClient and self.simulation is not True)):
            return False
        if type(self.call) is PumpingGattPartialStopClient:
            if self.call.generation!=c.generation or self.call.client_id!=r.client_id:
                return False
        try:
            return self.activation.proof.check_continuity() is True and self.context_valid() is True
        except Exception:
            return False

    def _now(self):
        value=self.clock()
        if (type(value) not in (int,float) or not math.isfinite(value)
                or (self._last_now is not None and value<self._last_now)):
            raise RuntimeError("partial stop monotonic clock invalid")
        self._last_now=value

    def _guard(self):
        a=self.activation;p=a.proof;c=a.controller
        if (c.phase!="ATTENTION" or c.output_enabled is not False
                or p.input_authorized is not False or p.output_quiesced is not True
                or p.check_continuity() is not True or self.context_valid() is not True
                or p.identity.generation!=c.generation):
            raise RuntimeError("partial stop ownership/quiescence proof invalid")
        self._now()

    def _call(self, method, params, timeout, counter_key):
        self._guard();self.pump();self._guard()
        self.attempts[counter_key]+=1
        reply=None;call_error=None
        try:
            reply=self.call(method,params,timeout=timeout)
        except BaseException as error:
            call_error=error
        try:
            self.pump();self._guard()
        except BaseException as error:
            if call_error is None:call_error=error
        if call_error is not None:raise call_error
        return reply

    @staticmethod
    def _ack(reply, *, client_id=None):
        return (type(reply) is dict and reply.get("returnValue") is True
                and ("address" not in reply or (type(reply["address"]) is str and reply["address"].lower()==TARGET))
                and ("adapterAddress" not in reply or (type(reply["adapterAddress"]) is str
                     and reply["adapterAddress"].lower()==ADAPTER))
                and (client_id is None or "clientId" not in reply or reply.get("clientId")==client_id))

    def _cccd_zero(self, reply):
        if (not self._ack(reply,client_id=self.activation.mode_reader.client_id)
                or reply.get('address')!=TARGET or reply.get('adapterAddress')!=ADAPTER):return False
        values=reply.get("values")
        if type(values) is not list or len(values)>16:return False
        matches=[]
        for item in values:
            if type(item) is dict and type(item.get("descriptor")) is str \
                    and item["descriptor"].lower() in (CCCD,"2902"):
                matches.append(item)
        if len(matches)!=1:return False
        item=matches[0];handle=item.get("instanceId")
        if type(handle) is not str or not handle.isascii() or not handle.isdecimal() \
                or len(handle)>5 or int(handle)!=36:return False
        value=item.get("value")
        return (type(value) is dict and set(value)=={"bytes"}
            and type(value["bytes"]) is list and len(value["bytes"])==2
            and all(type(v) is int and 0<=v<=255 for v in value["bytes"])
            and value["bytes"]==[0,0])

    def _mode_zero(self, reply):
        if not DirectGattReadProbe._reply_ok(reply) or not DirectGattReadProbe._identity(
                reply,self.activation.mode_reader.client_id):return False
        data=DirectGattReadProbe._extract_candidate(reply)
        candidate=None if data is None else _mode_candidate(data)
        return candidate=={"framing":"A0-mode","mode":0,"status":"candidate_only"}

    def execute(self):
        if not self.lock.acquire(blocking=False):
            return {"status":"attention","reason":"partial stop already running",
                    "leaseCleanupComplete":False,"active":False}
        try:
            if self.used:
                return {"status":"attention","reason":"partial stop already consumed",
                    "leaseCleanupComplete":False,"active":False}
            self.used=True
            if not self._validate():
                return {"status":"attention","reason":"partial stop preconditions invalid",
                    "leaseCleanupComplete":False,"active":False,"attempts":dict(self.attempts)}
            a=self.activation;r=a.mode_reader;client_id=r.client_id
            original=a.result.get("originalFailure",a.result.get("reason"))
            status={"status":"attention","active":False,"leaseCleanupComplete":False,
                "controllerPhase":"ATTENTION","originalFailure":original,
                "sensorDisableAttempted":False,"sensorDisableAcknowledged":False,
                "sensorModeZeroVerified":False,"sensorModeReadSkipped":False,
                "cccdRestoreAttempted":False,"cccdRestoreAcknowledged":False,
                "cccdZeroVerified":False,"attempts":self.attempts}
            self.result=status
            try:
                self._guard()
                if a.attempts["sensorEnable"]==1:
                    status["sensorDisableAttempted"]=True
                    try:
                        reply=self._call(_SET_REPORT,{"address":TARGET,"reportType":"feature",
                            "reportData":[240,160,0]},6,"sensor0")
                        status["sensorDisableAcknowledged"]=self._ack(reply)
                    except Exception as error:
                        status["sensorDisableError"]=type(error).__name__
                    if (r.reference_verified is True and r.selector_attempts==1
                            and type(r.client_id) is str and self._guard() is None):
                        # This direct GET is a distinct post-stop read; the original
                        # VerifiedModeReader object is never reopened or invoked.
                        try:
                            reply=self._call(READ_CHARACTERISTICS,
                                {"clientId":client_id,"service":HID_SERVICE,
                                 "characteristics":[REPORT_CHAR]},5,"sensorModeRead")
                            status["sensorModeZeroVerified"]=self._mode_zero(reply)
                        except Exception as error:
                            status["sensorModeReadError"]=type(error).__name__
                    else:
                        status["sensorModeReadSkipped"]=True
                if a.attempts["cccdEnable"]==1:
                    self._guard()
                    status["cccdRestoreAttempted"]=True
                    try:
                        reply=self._call(_WRITE_CCCD,{"clientId":client_id,"service":HID_SERVICE,
                            "characteristic":REPORT_CHAR,"descriptor":CCCD,
                            "value":{"bytes":[0,0]}},6,"cccd0")
                        status["cccdRestoreAcknowledged"]=self._ack(reply,client_id=client_id)
                    except Exception as error:
                        status["cccdRestoreError"]=type(error).__name__
                    self._guard()
                    try:
                        reply=self._call(_READ_CCCD,{"clientId":client_id,"service":HID_SERVICE,
                            "characteristic":REPORT_CHAR,"descriptors":[CCCD]},6,"cccdRead")
                        status["cccdZeroVerified"]=self._cccd_zero(reply)
                    except Exception as error:
                        status["cccdReadError"]=type(error).__name__
            except Exception as error:
                # Preserve the original activation failure and single-use stop
                # counters. Never retry an uncertain partial-stop operation.
                status["stopError"]=type(error).__name__
            finally:
                status["attempts"]=dict(self.attempts)
                status["controllerPhase"]="ATTENTION"
                status["leaseCleanupComplete"]=False
                status["active"]=False
            return status
        finally:
            self.lock.release()


__all__=("PartialActivationStop","PumpingGattPartialStopClient")
