"""Experimental in-process rollover for a verified continuous input link.

The caller owns the device FDs and separately verifies sensor/link continuity.
This class never connects, reconnects, enables sensors, or persists user input.
"""
import math,time
from grouped_prefix_output import GroupedPrefixOutput as CombinedReceiver
from input_session_policy import InputSessionPolicy
from touch_coordinates import decode_touch
from decoder import decode as decode_prefix
from normalize import normalize
from navigation_mode import NavigationMode

class RollingReceiver:
    def __init__(self,outputs,*,continuity,mode_verified,clock=time.monotonic,seconds=7200,history_limit=32,navigation_verified=None):
        if not callable(continuity) or not callable(mode_verified) or not callable(clock):raise ValueError('verified control callbacks required')
        if navigation_verified is not None and not callable(navigation_verified):raise ValueError('invalid navigation authorization')
        self.navigation_verified=navigation_verified
        self.navigation=NavigationMode()
        self.outputs=outputs;self.continuity=continuity;self.mode_verified=mode_verified;self.clock=clock
        self.policy=InputSessionPolicy.sustained(seconds);self.history_limit=history_limit
        # Explicit bounded grace; never rewrite a child deadline or freeze time.
        self.child_policy=InputSessionPolicy.sustained(min(7200,self.policy.runtime_seconds))
        self.paused=False;self.physical_neutral=False
        self.receiver=None;self.started=None;self.generation=0;self.closed=False;self.rotations=0;self.completed_actions=0;self.last_time=None;self.complete_frames=0
        self.stop_reason=None
        self.decoded_kinds=dict.fromkeys(('no-touch','one-touch','two-touch','rejected'),0)
    def _live(self):
        try:return self.continuity() is True and (self.mode_verified() is True or (self.navigation_verified is not None and self.navigation_verified() is True))
        except Exception:return False
    def _new(self):
        r=CombinedReceiver(self.outputs,clock=self.clock,sensor_input_verified=False,session_policy=self.child_policy,max_actions=self.policy.max_actions,action_history_limit=self.history_limit)
        # Only the coordinate basis survives an in-process rollover or screen
        # pause on this verified sensor session. Filters, pending displacement,
        # deadlines and button state belong to the new child and stay fresh.
        if self.receiver is not None:
            r.router.pose.reference_inverse=self.receiver.router.pose.reference_inverse
        r.router.navigation=self.navigation
        self.generation+=1
        if not r.bind(self.generation):raise RuntimeError('receiver-bind-failed')
        self.receiver=r;self.started=self.clock();self.last_time=self.started
    def start(self):
        if self.receiver is not None or self.closed or not self._live():raise RuntimeError('control-not-ready')
        self._new()
    def _neutral(self):
        r=self.receiver;p=r.router.press
        return (self.physical_neutral and r.pending_direction is None and not p.core.down
                and not p.center_down_known and p.pending_swipe is None and p.gesture is None
                and not r.transport.queue and r.transport.tail_due is None)
    def _advance(self):
        if self.closed or self.receiver is None:return False
        if not self._live():self.stop('control-lost');return False
        now=self.clock()
        if type(now) not in (int,float) or not math.isfinite(now) or now<self.last_time:self.stop('clock-invalid');return False
        self.last_time=now
        if self.paused:return True
        elapsed=now-self.started
        if elapsed>=self.child_policy.seconds:
            self.stop('drain-deadline-without-neutral');return False
        remaining_actions=self.policy.max_actions-self.receiver.router.press.core.stats['pressAttempts']
        if (elapsed>=self.policy.seconds-2 or remaining_actions<=1) and self._neutral():
            try:
                self.receiver.stop('rollover')
                self.completed_actions+=self.receiver.semantic_actions
                self._new();self.rotations+=1
            except BaseException:
                self.closed=True
                raise
        return True
    def pause_output(self):
        if self.closed or self.paused:return
        # Finish releases and the neutral cursor tail BEFORE screen-off dispatch.
        self.receiver.stop('screen-paused')
        self.completed_actions+=self.receiver.semantic_actions
        self.paused=True;self.physical_neutral=False
    def resume_output(self):
        if self.closed or not self.paused:return
        if not self._live():raise RuntimeError('control-not-ready')
        self._new();self.paused=False;self.rotations+=1
    def begin_wake_press(self):
        if not self._advance() or self.paused:return False
        # Reuse the normal click destination, budgets, release and cleanup.
        self.receiver.router.pose._clear_tracking()
        return self.receiver.router.press.begin_wake_press(self.generation)
    def feed_raw(self,generation,report):
        if type(generation) is not int or generation!=1:return False
        if not self._advance():return False
        if self.paused:return False
        try:
            parsed=decode_prefix(report)
            kind=parsed['kind'] if parsed is not None else 'rejected'
            self.decoded_kinds[kind]=min(100000000,self.decoded_kinds[kind]+1)
            motion_verified=self.mode_verified() is True
            if not motion_verified:self.receiver.bridge.sensor_input_verified=False
            if motion_verified and parsed is not None and parsed.get('kind')=='no-touch':
                self.receiver.bridge.sensor_input_verified=True;self.complete_frames+=1
            result=self.receiver.feed_raw(self.generation,report)
            sample=normalize(report)
            self.physical_neutral=False
            if sample is not None:
                value=sample['touch_value']
                touch=decode_touch(value)
                self.physical_neutral=(value[1]==0 and (
                    (len(value)==2 and value[0]==0) or
                    (touch is not None and all(f['state']==7 for f in touch['fingers']))))
            # Process the release in its owning generation before retiring it.
            self._advance()
            return result
        except BaseException:
            self.stop('receiver-failed')
            raise
    def tick(self):
        if not self._advance():return False
        try:
            if not self.mode_verified():self.receiver.bridge.sensor_input_verified=False
            if not self.paused:self.receiver.tick()
            return True
        except BaseException:
            self.stop('receiver-failed')
            raise
    def stop(self,reason='requested'):
        if self.closed:return
        self.stop_reason=reason
        self.closed=True
        if self.receiver is not None:
            self.receiver.bridge.sensor_input_verified=False
            self.receiver.stop(reason)
    def summary(self):
        return {'closed':self.closed,'rotations':self.rotations,
                'stopReason':self.stop_reason,'decodedKinds':dict(self.decoded_kinds),
                'nominalSegmentSeconds':self.policy.seconds,
                'maxNeutralGraceSeconds':self.child_policy.seconds-self.policy.seconds,
                'hardSegmentSeconds':self.child_policy.seconds,
                'semanticActionCount':self.completed_actions+(self.receiver.semantic_actions if self.receiver else 0),
                'completeMotionFrames':self.complete_frames,'rawReportsPersisted':False,
                'current':self.receiver.summary() if self.receiver else None}
