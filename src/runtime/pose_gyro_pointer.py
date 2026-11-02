"""Uncapped pointing-ray displacement from compact orientation, not rate*host dt.

Pure candidate. Physical mounting/axis convention still needs live comparison.
Gain4000 matches the accepted prior scale at small angles; no absolute screen
coordinate assumption, auto-centering, native click/keys or device access.
"""
import math
import time
from gyro_pointer import GyroPointer
from motion_report import decode_compact_motion
from pose_math import compact_quaternion,conjugate,pointing_angles,shortest_angle,PoseRateAgreement


class PoseGyroPointer(GyroPointer):
    PERIOD=.020
    FILTER_TAU=.015
    ANGLE_DEADBAND=.00035  # Lower angular hysteresis, NOT a maximum speed.
    ABSOLUTE_RATE_LIMIT=20.
    MAX_SPEED=None
    MAX_FRAME=None

    def __init__(self,*,clock=time.monotonic,max_seconds=30.,session_policy=None):
        super().__init__(axes=(2,0),signs=(-1,-1),gain=500.,clock=clock,max_seconds=max_seconds,
                         calibration_batch_tolerant=True,session_policy=session_policy)
        self.gain=4000.
        self.agreement=PoseRateAgreement()
        self.pose_counts=dict.fromkeys(('activeSamples','coalescedSamples','renderTicks','renderFrames',
            'malformedActive','implausibleRates','blockedActive','staleReset','geometryRejected',
            'deadbandAxes','speedLimited','frameLimited','tokenLimited'),0)
        self.render_bins=[0]*6

    def _reset(self):
        super()._reset()
        self.reference_inverse=None
        self._clear_tracking()

    def _clear_tracking(self):
        self.pending=self.last_pose=self.filtered_angles=self.output_angles=None
        self.unwrapped=[0.,0.]
        self.render_at=self.next_tick_at=None
        self.previous=None
        if hasattr(self,'agreement'):self.agreement.break_link()

    def feed(self,generation,value):
        if self.bias is None:
            GyroPointer.feed(self,generation,value)
            if self.bias is not None:
                q=compact_quaternion(decode_compact_motion(value)['orientation3'])
                assert q is not None
                self.reference_inverse=conjugate(q)
                self._clear_tracking()
            return None
        now=self._now()
        if now is None:return None
        if type(generation) is not int or generation!=self.generation or self.generation is None:
            self.counts['staleFrames']+=1;return None
        sample=decode_compact_motion(value)
        if sample is None:
            self._clear_tracking();self.pose_counts['malformedActive']+=1;return None
        if self.previous is not None and now-self.previous>self.MAX_GAP:
            self._clear_tracking();self.pose_counts['staleReset']+=1
        self.previous=now
        touch=sample['touch']
        if sample['buttons'] or (touch is not None and len(touch['fingers'])!=1):
            self._clear_tracking();self.pause_until=now+self.RELEASE_PAUSE
            self.pose_counts['blockedActive']+=1;return None
        if now<self.pause_until:
            self._clear_tracking();return None
        rate=tuple(x/1000.-b for x,b in zip(sample['scaledVectorB'],self.bias))
        if max(abs(x) for x in rate)>self.ABSOLUTE_RATE_LIMIT:
            self._clear_tracking();self.pose_counts['implausibleRates']+=1;return None
        q=compact_quaternion(sample['orientation3'])
        angles=pointing_angles(self.reference_inverse,q)
        if angles is None:
            self._clear_tracking();self.pose_counts['geometryRejected']+=1;return None
        self.agreement.feed(now,q,rate)
        if self.last_pose is None:
            self.unwrapped=list(angles)
            self.filtered_angles=list(angles);self.output_angles=list(angles)
            self.render_at=now;self.next_tick_at=now+self.PERIOD
        else:
            self.unwrapped[0]+=shortest_angle(angles[0]-self.last_pose[0])
            self.unwrapped[1]+=angles[1]-self.last_pose[1]
        self.last_pose=angles
        if self.pending is not None:self.pose_counts['coalescedSamples']+=1
        self.pending=(now,tuple(self.unwrapped))
        self.pose_counts['activeSamples']+=1
        return None

    def poll_timeout(self):
        now=self.clock()
        if self.next_tick_at is None or not isinstance(now,(int,float)) or not math.isfinite(now):return .01
        return min(.01,max(.001,self.next_tick_at-now))

    def tick(self):
        if self.bias is None:
            GyroPointer.tick(self);return None
        now=self._now()
        if now is None:return None
        if self.previous is None or now-self.previous>self.MAX_GAP:
            if self.last_pose is not None:
                self._clear_tracking();self.pose_counts['staleReset']+=1
            return None
        if self.pending is None or self.next_tick_at is None or now<self.next_tick_at-1e-9:return None
        stamp,target=self.pending;self.pending=None
        if now-stamp>self.MAX_GAP or now-self.render_at>self.MAX_GAP:
            self._clear_tracking();self.pose_counts['staleReset']+=1;return None
        elapsed=now-self.render_at
        self.render_at=now;self.next_tick_at=now+self.PERIOD
        alpha=-math.expm1(-min(elapsed,.04)/self.FILTER_TAU)
        self.filtered_angles=[old+alpha*(new-old) for old,new in zip(self.filtered_angles,target)]
        result=[]
        for axis in range(2):
            delta=self.filtered_angles[axis]-self.output_angles[axis]
            if abs(delta)<self.ANGLE_DEADBAND:
                n=0;self.pose_counts['deadbandAxes']+=1
            else:n=math.trunc(delta*self.gain)
            self.output_angles[axis]+=n/self.gain
            result.append(n)
        self.pose_counts['renderTicks']+=1
        index=next((i for i,t in enumerate((.005,.015,.025,.04,.06)) if elapsed<t),5)
        self.render_bins[index]+=1
        if result==[0,0]:return None
        self.pose_counts['renderFrames']+=1;self.counts['motionFrames']+=1
        return tuple(result)

    def summary(self):
        result=super().summary()
        result.update({'pose':dict(self.pose_counts),'poseRateAgreement':self.agreement.summary(),
            'conversionPolicy':'orientation pointing-ray angle displacement, not rate*arrival time',
            'spatialCapsEnabled':False,'tokenBudgetEnabled':False,'maxSpeedL1':None,'maxFrameTravelL1':None,
            'renderPeriodMs':20,'filterTauMs':15,'angleDeadbandRadians':self.ANGLE_DEADBAND,
            'renderMsBins':list(self.render_bins),'timingBinEdgesMs':[5,15,25,40,60],
            'pendingSamples':int(self.pending is not None),'backlogReplay':False,
            'rateUsedForCursor':False,'poseBodyForwardAxis':'+Y','reference':'stationary calibration quaternion',
            'bodyRollIsNotDirectCursorInput':True,'physicalMountAndScreenAxesValidated':False,
            'geometryPoleGuardHorizontalNorm':.05,'absoluteRatePlausibilityLimit':20,
            'motionTimeSeriesExported':False,'sensorTimestampsAvailable':False})
        return result
