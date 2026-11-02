"""Direct fused-pose comparison: no added orientation LP; vertical gain6000."""
import math
from gyro_pointer import GyroPointer
from pose_gyro_pointer import PoseGyroPointer


class DirectPosePointer(PoseGyroPointer):
    FILTER_TAU=0.
    AXIS_GAINS=(4000.,6000.)

    def _render_target(self, target, elapsed):
        # Baseline is deliberately unfiltered. Offline comparison subclasses
        # may change only this target projection, never gains or ownership.
        return list(target)

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
        # Device's fused pose is used directly: no host low-pass or extrapolation.
        self.filtered_angles=self._render_target(target,elapsed)
        result=[]
        for axis,gain in enumerate(self.AXIS_GAINS):
            delta=self.filtered_angles[axis]-self.output_angles[axis]
            if abs(delta)<self.ANGLE_DEADBAND:
                n=0;self.pose_counts['deadbandAxes']+=1
            else:n=math.trunc(delta*gain)
            self.output_angles[axis]+=n/gain;result.append(n)
        self.pose_counts['renderTicks']+=1
        index=next((i for i,t in enumerate((.005,.015,.025,.04,.06)) if elapsed<t),5)
        self.render_bins[index]+=1
        if result==[0,0]:return None
        self.pose_counts['renderFrames']+=1;self.counts['motionFrames']+=1
        return tuple(result)

    def summary(self):
        result=super().summary()
        result.update({'axisGains':list(self.AXIS_GAINS),'filterTauMs':0,'additionalOrientationLowPass':False,
            'predictionEnabled':False,'gainIsHorizontalOnly':False,
            'conversionPolicy':'direct fused-pose ray, gains4000/6000, no host LP or spatial caps'})
        return result
