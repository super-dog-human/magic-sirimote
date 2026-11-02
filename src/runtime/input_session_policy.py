"""Explicit, immutable bounds for an opt-in sustained input session.

This is configuration, not a security capability. Owners must still enforce
their own deadlines and action budgets.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class InputSessionPolicy:
    seconds: float

    def __post_init__(self):
        if type(self.seconds) not in (int, float):
            raise ValueError('Session duration must be an exact int or float')
        try:
            finite = math.isfinite(self.seconds)
        except (OverflowError, TypeError):
            finite = False
        if not finite or not 30 < self.seconds <= 7200:
            raise ValueError('Sustained session duration must be over 30 and at most 7200 seconds')

    @property
    def max_actions(self):
        return math.ceil(self.seconds) * 4

    @property
    def runtime_seconds(self):
        """Allow session time plus the existing 180-second cleanup margin."""
        return math.ceil(self.seconds) + 180

    @property
    def max_rpc_sequence(self):
        """Bound the private channel at 20 RPCs/second plus fixed overhead."""
        return math.ceil(self.runtime_seconds) * 20 + 100

    @classmethod
    def sustained(cls, seconds):
        """Create the explicit long-session setting; no default opts in."""
        return cls(seconds)


def resolve_session_bounds(max_seconds, session_policy=None, *, default_seconds=30,
                           default_actions=16, legacy_max_seconds=None):
    """Resolve a constructor's exact session duration and action allowance.

    Legacy callers may specify a larger cap through ``legacy_max_seconds``;
    this preserves TouchClick's historical 300-second standalone ceiling.
    """
    if type(max_seconds) not in (int, float):
        raise ValueError('Session duration must be an exact int or float')
    try:
        finite = math.isfinite(max_seconds)
    except (OverflowError, TypeError):
        finite = False
    if not finite or max_seconds <= 0:
        raise ValueError('Session duration must be finite and positive')
    if session_policy is None:
        cap = legacy_max_seconds if legacy_max_seconds is not None else default_seconds
        if max_seconds > cap:
            raise ValueError('Session duration exceeds the default bounded session')
        return max_seconds, default_actions
    if type(session_policy) is not InputSessionPolicy:
        raise ValueError('Exact InputSessionPolicy required')
    if max_seconds != session_policy.seconds:
        raise ValueError('max_seconds must exactly match the sustained policy')
    return session_policy.seconds, session_policy.max_actions
