"""Comparison candidate using one adaptive alpha for both angle axes.

This preserves the responsive candidate's gains and derivative updates, but
uses the Euclidean magnitude of the filtered derivative vector to select one
shared cutoff/alpha. It is synthetic-only and not hardware accepted.
"""
import math

from adaptive_pose_pointer import ResponsiveAdaptivePosePointer


class VectorAdaptivePosePointer(ResponsiveAdaptivePosePointer):
    """Rotationally symmetric per-frame low-pass over the 2D angle target."""

    def _render_target(self, target, elapsed):
        if not math.isfinite(elapsed) or elapsed <= 0:
            self._adaptive_previous_raw = list(target)
            self._adaptive_filtered = list(target)
            self._adaptive_derivative = [0.0, 0.0]
            return list(target)

        if self._adaptive_previous_raw is None:
            baseline = list(self.output_angles if self.output_angles is not None else target)
            # Keep raw-target history distinct from the low-pass state.
            self._adaptive_previous_raw = list(baseline)
            self._adaptive_filtered = list(baseline)
            self._adaptive_derivative = [0.0, 0.0]

        derivative_alpha = self._alpha(self.DERIVATIVE_CUTOFF_HZ, elapsed)
        derivatives = []
        for axis, raw in enumerate(target):
            derivative = (raw - self._adaptive_previous_raw[axis]) / elapsed
            filtered = (derivative_alpha * derivative +
                        (1.0 - derivative_alpha) * self._adaptive_derivative[axis])
            derivatives.append(filtered)
            self._adaptive_previous_raw[axis] = raw
            self._adaptive_derivative[axis] = filtered

        speed = math.hypot(*derivatives)
        cutoff = self.MIN_CUTOFF_HZ + self.BETA * speed
        alpha = self._alpha(cutoff, elapsed)
        result = []
        for axis, raw in enumerate(target):
            filtered = alpha * raw + (1.0 - alpha) * self._adaptive_filtered[axis]
            result.append(filtered)
            self._adaptive_filtered[axis] = filtered
        return result

    def summary(self):
        result = super().summary()
        result['adaptiveFilter'] = {
            'type': 'per-axis first-order low-pass with shared vector-speed cutoff',
            'minCutoffHz': self.MIN_CUTOFF_HZ,
            'beta': self.BETA,
            'derivativeCutoffHz': self.DERIVATIVE_CUTOFF_HZ,
            'derivativeSource': 'successive raw render targets / elapsed seconds, independently filtered per axis',
            'cutoffSpeed': 'Euclidean magnitude of the two filtered derivatives',
            'sharedAlphaForBothAxes': True,
            'parametersValidated': False,
        }
        result['conversionPolicy'] = (
            'direct fused-pose ray, baseline gains4000/6000, shared vector-speed '
            'adaptive low-pass; no prediction or spatial caps')
        result['candidateNotHardwareAccepted'] = True
        result['gainScaleVsDirectBaseline'] = 1.0
        return result


class ReducedGainVectorAdaptivePosePointer(VectorAdaptivePosePointer):
    """User-requested 15% movement reduction; identical filtering and timing.

    This is a separate fixed profile: the previously tested gains stay intact.
    Integer quantization and downstream TV acceleration mean cursor pixels need
    not decrease by exactly 15% for every individual physical movement.
    """
    AXIS_GAINS = (3400., 5100.)

    def summary(self):
        result = super().summary()
        result['conversionPolicy'] = (
            'direct fused-pose ray, gains3400/5100 (85% baseline), shared '
            'vector-speed adaptive low-pass; no prediction or spatial caps')
        result['gainScaleVsDirectBaseline'] = .85
        return result
