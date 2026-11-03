"""Cleanup-only capability, separate from permission to emit input.

No I/O or automatic adoption. The transport must supply messages from its
already authenticated owned monitor channel, never page/HTTP/user JSON. A
page visibility loss revokes input, NOT monitor identity. Monitor
loss/replacement revokes this capability too.
"""
from dataclasses import dataclass,asdict
import math
import re
import time
from lifecycle import REMOTE,ADAPTER
from input_session_policy import InputSessionPolicy


@dataclass(frozen=True)
class LinkIdentity:
    run: str
    remote: str
    adapter: str
    controller: int
    handle: int
    generation: int
    root_pid: int
    monitor_pid: int
    service_pid: int


class CleanupProof:
    def __init__(self,identity,*,clear_baseline,wake_cue_sent,new_owned_link,
                 monitor_channel_owned,clock=time.monotonic,session_policy=None):
        if session_policy is not None and type(session_policy) is not InputSessionPolicy:
            raise ValueError('Exact InputSessionPolicy required')
        if (not isinstance(identity,LinkIdentity)
                or not isinstance(identity.run,str) or not re.fullmatch('[a-f0-9]{24}',identity.run)
                or identity.remote!=REMOTE or identity.adapter!=ADAPTER
                or type(identity.controller) is not int or identity.controller!=0
                or type(identity.handle) is not int or not 0<=identity.handle<=4095
                or any(type(n) is not int or not 0<n<2**31 for n in
                       (identity.generation,identity.root_pid,identity.monitor_pid,identity.service_pid))
                or len({identity.root_pid,identity.monitor_pid,identity.service_pid})!=3
                or any(value is not True for value in
                       (clear_baseline,wake_cue_sent,new_owned_link,monitor_channel_owned))):
            raise ValueError('Exact fresh run-owned monitor identity required; no borrowed link')
        self.identity,self.clock=identity,clock
        self.session_policy=session_policy
        self.max_lifetime_seconds=(180 if session_policy is None
                                   else session_policy.runtime_seconds)
        self.started=self.last_time=clock()
        if type(self.started) not in (int,float) or not math.isfinite(self.started):
            raise ValueError('Finite monotonic time required')
        self.sequence=0
        self.last_heartbeat=None
        self.revoked=self.release_consumed=False
        self.input_authorized=True
        self.output_quiesced=False
        self.reason=None

    def revoke(self,reason):
        self.revoked=True;self.input_authorized=False;self.reason=reason

    def visibility_lost(self):
        # No state here can re-enable output. Keep the independent monitor
        # alive, quiesce/destroy own input devices in the future transport.
        self.input_authorized=False

    def confirm_output_quiesced(self,*,owned_input_devices_removed):
        if owned_input_devices_removed is not True:
            self.revoke('owned-input-cleanup-not-confirmed')
            return False
        self.input_authorized=False;self.output_quiesced=True
        return True

    def _time(self):
        now=self.clock()
        if (type(now) not in (int,float) or not math.isfinite(now)
                or now<self.last_time or now-self.started>self.max_lifetime_seconds):
            self.revoke('monitor-deadline-or-clock-invalid')
            return None
        if now-(self.started if self.last_heartbeat is None else self.last_heartbeat)>2:
            self.revoke('monitor-continuity-expired')
            return None
        self.last_time=now
        return now

    def monitor_event(self,event,*,authenticated_owned_channel):
        now=self._time()
        if self.revoked or now is None:return False
        expected=set(asdict(self.identity))|{'type','sequence'}
        if (authenticated_owned_channel is not True or type(event) is not dict
                or set(event)!=expected or event.get('type')!='same-live-target'
                or type(event.get('sequence')) is not int or event['sequence']!=self.sequence+1
                or any(type(event.get(key)) is not type(value) or event[key]!=value
                       for key,value in asdict(self.identity).items())):
            self.revoke('monitor-channel-identity-sequence-or-link-changed')
            return False
        self.sequence=event['sequence'];self.last_heartbeat=now
        return True

    def monitor_closed(self):self.revoke('monitor-closed')
    def target_disconnected(self):self.revoke('target-disconnected')
    def replacement_observed(self):self.revoke('target-or-controller-replaced')

    def check_continuity(self):
        """Revalidate the existing authenticated lease; never grants input."""
        return self._time() is not None and not self.revoked and self.last_heartbeat is not None

    def release_action(self,*,generation,hid_status,status_observed_at,authenticated_status_channel):
        now=self._time()
        if self.revoked or self.release_consumed:return None
        # Consume on the first cleanup decision, including bad evidence. Never
        # use a second status as a reason to retry an uncertain disconnect.
        self.release_consumed=True
        if self.input_authorized or not self.output_quiesced:
            self.revoke('input-not-quiesced-and-removed');return None
        if (now is None or self.last_heartbeat is None or now-self.last_heartbeat>2
                or type(generation) is not int or generation!=self.identity.generation):
            self.revoke('cleanup-proof-stale-or-generation-mismatch');return None
        v=hid_status
        if (authenticated_status_channel is not True
                or type(status_observed_at) not in (int,float) or not math.isfinite(status_observed_at)
                or not self.started<=status_observed_at<=now or now-status_observed_at>1
                or type(v) is not dict or v.get('returnValue') is not True
                or v.get('address')!=REMOTE or v.get('adapterAddress')!=ADAPTER
                or v.get('connected') is not True or v.get('connecting') is not False
                or v.get('connectRequest') is not False):
            self.revoke('fresh-exact-hid-state-not-confirmed');return None
        return {'method':'hid/disconnect','parameters':{'address':REMOTE},
                'generation':generation,'monitorSequence':self.sequence,
                'cleanupOnly':True,'automaticRetries':0}

    def summary(self):
        return {'revoked':self.revoked,'reason':self.reason,'inputAuthorized':self.input_authorized,
                'ownedInputQuiescenceConfirmed':self.output_quiesced,
                'releaseDecisionConsumed':self.release_consumed,'monitorSequence':self.sequence,
                'deviceOperations':0,'deployedIntoLegacyTrial':False}
