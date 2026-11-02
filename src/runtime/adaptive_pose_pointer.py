"""Offline opt-in adaptive jitter-filter variant of DirectPosePointer.

The filter is a small per-axis 1-Euro-style low-pass. These fixed parameters
are a comparison candidate, not a validated tuning or the author's full
reference implementation. No device or native-input I/O is performed here.
"""
import math

from direct_pose_pointer import DirectPosePointer


class AdaptivePosePointer(DirectPosePointer):
    MIN_CUTOFF_HZ = 4.0
    BETA = 40.0
    DERIVATIVE_CUTOFF_HZ = 1.0

    def __init__(self, **kwargs):
        self._adaptive_previous_raw = None
        self._adaptive_filtered = None
        self._adaptive_derivative = None
        super().__init__(**kwargs)

    @staticmethod
    def _alpha(cutoff_hz, elapsed):
        return 1.0 / (1.0 + 1.0 / (2.0 * math.pi * cutoff_hz * elapsed))

    def _clear_tracking(self):
        super()._clear_tracking()
        self._adaptive_previous_raw = None
        self._adaptive_filtered = None
        self._adaptive_derivative = None

    def _render_target(self, target, elapsed):
        if not math.isfinite(elapsed) or elapsed <= 0:
            # A nonpositive interval is not a valid filter sample. Re-seed at
            # the current baseline; inherited freshness checks still govern
            # whether a render is reached at all.
            self._adaptive_previous_raw = list(target)
            self._adaptive_filtered = list(target)
            self._adaptive_derivative = [0.0, 0.0]
            return list(target)

        if self._adaptive_previous_raw is None:
            # PoseGyroPointer initializes output_angles at the tracking origin.
            # Seed there so movement accumulated before the first render is
            # filtered rather than discarded or carried across a reset.
            baseline = list(self.output_angles if self.output_angles is not None else target)
            self._adaptive_previous_raw = baseline
            self._adaptive_filtered = baseline
            self._adaptive_derivative = [0.0, 0.0]

        result = []
        derivative_alpha = self._alpha(self.DERIVATIVE_CUTOFF_HZ, elapsed)
        for axis, raw in enumerate(target):
            derivative = (raw - self._adaptive_previous_raw[axis]) / elapsed
            filtered_derivative = (derivative_alpha * derivative +
                                   (1.0 - derivative_alpha) * self._adaptive_derivative[axis])
            cutoff = self.MIN_CUTOFF_HZ + self.BETA * abs(filtered_derivative)
            alpha = self._alpha(cutoff, elapsed)
            filtered = alpha * raw + (1.0 - alpha) * self._adaptive_filtered[axis]
            result.append(filtered)
            self._adaptive_previous_raw[axis] = raw
            self._adaptive_derivative[axis] = filtered_derivative
            self._adaptive_filtered[axis] = filtered
        return result

    def summary(self):
        result = super().summary()
        result.update({
            'candidateNotHardwareAccepted': True,
            'axisGains': list(self.AXIS_GAINS),
            'gainScaleVsDirectBaseline': 1.0,
            'filterTauMs': None,
            'additionalOrientationLowPass': True,
            'adaptiveFilter': {
                'type': 'per-axis speed-adaptive first-order low-pass',
                'minCutoffHz': self.MIN_CUTOFF_HZ,
                'beta': self.BETA,
                'derivativeCutoffHz': self.DERIVATIVE_CUTOFF_HZ,
                'derivativeSource': 'successive raw render targets / elapsed seconds',
                'parametersValidated': False,
            },
            'predictionEnabled': False,
            'gainIsHorizontalOnly': False,
            'conversionPolicy': ('direct fused-pose ray, baseline gains4000/6000, '
                                 'per-axis speed-adaptive low-pass; no prediction or spatial caps'),
        })
        return result


class ResponsiveAdaptivePosePointer(AdaptivePosePointer):
    """Offline comparison variant with a faster derivative estimate.

    Only the derivative low-pass cutoff differs from AdaptivePosePointer.
    This remains a synthetic comparison candidate, not hardware acceptance.
    """
    DERIVATIVE_CUTOFF_HZ = 8.0
