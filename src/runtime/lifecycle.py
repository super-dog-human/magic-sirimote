"""Pure offline lifecycle contract. handle(event, now) emits symbolic Actions only.

One wake allows at most three link requests: initial plus two retries (5s,
then 15s); link/connect failures are
reported as connection_failed or connection_timeout. Confirmations require
ok=True. A transport must provide unique generations and monotonically finite
timestamps. Sensor baseline is read only after one F0/AF init per generation.
No state is inferred from a new Controller after process restart.
"""
from runtime_device import identity as device_identity
from dataclasses import dataclass, field
import math

REMOTE = device_identity().remote
ADAPTER = device_identity().adapter


@dataclass(frozen=True)
class Action:
    name: str
    generation: object = None
    value: object = None


@dataclass
class Controller:
    phase: str = "IDLE"
    authorized: bool = False
    context_valid: bool = False
    generation: object = None
    attempt: int = 0
    retry_at: float | None = None
    retry_used: int = 0
    init_done: bool = False
    output_enabled: bool = False
    owned_link: bool = False
    cccd_attempted: bool = False
    sensor_attempted: bool = False
    cleanup_stage: str | None = None
    attention: str | None = None
    recovery_required: set = field(default_factory=set)
    _seen: set = field(default_factory=set, repr=False)
    _last_generation: int = field(default=0, repr=False)
    _last_now: float = field(default=-math.inf, repr=False)

    def _attention(self, why, recovery=None):
        self.output_enabled = False
        self.phase, self.attention, self.retry_at = "ATTENTION", why, None
        if self.sensor_attempted:
            self.recovery_required.add("sensor_state")
        if self.cccd_attempted:
            self.recovery_required.add("cccd_state")
        if recovery:
            self.recovery_required.add(recovery)
        return [Action("stop_output"), Action("attention", value=why)]

    def _time(self, now):
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now) or now < self._last_now:
            return False
        self._last_now = now
        return True

    def wake(self, *, authorized, context_valid, now):
        if not self._time(now):
            return self._attention("invalid or non-monotonic time")
        if type(authorized) is not bool or type(context_valid) is not bool:
            return self._attention("authorization/context must be booleans")
        if self.phase not in ("IDLE", "BACKOFF") or self.generation is not None:
            self.output_enabled = False
            if self.phase == "ACTIVE":
                self.phase, self.attention = "ATTENTION", "wake refused while active"
            return [Action("stop_output"), Action("wake_refused", value="live lifecycle requires cleanup")]
        self.authorized, self.context_valid = authorized, context_valid
        self.retry_used, self.attempt, self.retry_at = 0, 0, None
        self._seen.clear()
        if not self.authorized or not self.context_valid:
            self.phase = "IDLE"
            return [Action("stop_output")]
        self.phase, self.attempt = "CONNECTING", 1
        return [Action("request_link", value={"remote": REMOTE, "adapter": ADAPTER, "owned_only": True, "attempt": self.attempt})]

    def stop(self, *, context_lost=False):
        if context_lost:
            self.context_valid = False
        else:
            self.authorized = False
        self.output_enabled = False
        self.retry_at = None
        if self.phase == "ATTENTION":
            return [Action("stop_output")]
        if self.phase == "CLEANUP":
            return [Action("stop_output")]
        if self.generation is None or not self.owned_link:
            self.phase = "IDLE"
            return [Action("stop_output")]
        self.phase, self.cleanup_stage = "CLEANUP", "sensor_disable"
        actions = [Action("stop_output")]
        if self.sensor_attempted:
            actions.append(Action("disable_sensor", self.generation))
        else:
            if self.cccd_attempted:
                self.cleanup_stage = "cccd_restore"
                actions.append(Action("restore_cccd", self.generation, 0))
            else:
                self.cleanup_stage = "release"
                actions.append(Action("release_link", self.generation))
        return actions

    def handle(self, event, now):
        if not self._time(now):
            return self._attention("invalid or non-monotonic time")
        if not isinstance(event, dict):
            return self._attention("event must be a dictionary")
        kind = event.get("type")
        if type(kind) is not str:
            return self._attention("event type must be a string")
        if kind in ("stop", "context_lost"):
            return self.stop(context_lost=kind == "context_lost")
        if kind == "tick":
            if self.phase == "BACKOFF" and now >= self.retry_at:
                if not self.authorized or not self.context_valid:
                    return self._attention("retry context invalid")
                self.phase, self.attempt, self.retry_at = "CONNECTING", self.attempt + 1, None
                return [Action("request_link", value={"remote": REMOTE, "adapter": ADAPTER, "owned_only": True, "attempt": self.attempt})]
            return []
        if kind in ("connection_failed", "connection_timeout"):
            if self.phase != "CONNECTING" or event.get("ok") is not True or type(event.get("attempt")) is not int or event.get("attempt") != self.attempt:
                return self._attention("unexpected or unconfirmed connection failure")
            return self._retry(now)
        if kind == "link_lost":
            if self.generation is None or event.get("ok") is not True or type(event.get("generation")) is not int or event.get("generation") != self.generation:
                return self._attention("link loss generation mismatch")
            if self.phase == "ATTENTION" or self.recovery_required:
                return self._attention(self.attention or "link lost with recovery required")
            if self.phase == "CLEANUP":
                return self._attention("link lost during cleanup", self.cleanup_stage or "cleanup")
            if self.sensor_attempted or self.cccd_attempted:
                return self._attention("link lost after a setting change; restoration unverified", "link_restoration")
            self.output_enabled = False
            self.generation = None
            self.owned_link = False
            self._seen.clear()
            actions = [Action("stop_output"), Action("clear_pending_frames")]
            actions += self._retry(now, return_actions=True)
            return actions
        if kind == "link":
            if self.phase != "CONNECTING" or not self.authorized or not self.context_valid:
                return self._attention("unexpected link")
            gen = event.get("generation")
            if event.get("ok") is not True or type(event.get("attempt")) is not int or event.get("attempt") != self.attempt:
                return self._attention("link establishment not confirmed")
            if event.get("remote") != REMOTE or event.get("adapter") != ADAPTER:
                return self._attention("link identity mismatch")
            if event.get("owned") is not True or event.get("adopted") is not False or type(gen) is not int or gen <= 0 or gen <= self._last_generation:
                return self._attention("pre-existing, unowned, or non-increasing link generation")
            self._last_generation = gen
            self.generation, self.owned_link = gen, True
            self.init_done = self.cccd_attempted = self.sensor_attempted = False
            self.phase = "READ_CCCD_BASELINE"
            return [Action("read_cccd", gen)]
        gen = event.get("generation")
        if type(gen) is not int or gen != self.generation:
            return self._attention("stale or mismatched generation")
        if event.get("ok") is not True:
            return self._attention("missing or failed confirmation", kind if kind in ("cccd_enabled", "sensor_enabled", "restore_cccd", "released") else None)
        key = (kind, gen)
        if key in self._seen:
            return self._attention("duplicate confirmation")
        expected = {
            "cccd_baseline": "READ_CCCD_BASELINE", "cccd_enabled": "ENABLE_CCCD",
            "cccd_verified": "VERIFY_CCCD", "init_write_ok": "INIT_WRITE",
            "sensor_baseline": "READ_SENSOR_BASELINE", "sensor_enabled": "ENABLE_SENSOR",
            "sensor_verified": "VERIFY_SENSOR", "sensor_disabled": "CLEANUP",
            "sensor_cleanup_verified": "CLEANUP", "cccd_restored": "CLEANUP",
            "cccd_restore_verified": "CLEANUP", "released": "CLEANUP",
        }.get(kind)
        if expected is None or self.phase != expected:
            return self._attention("out-of-order or unknown confirmation")
        stages = {"sensor_disabled": "sensor_disable", "sensor_cleanup_verified": "sensor_readback",
                  "cccd_restored": "cccd_restore", "cccd_restore_verified": "cccd_readback",
                  "released": "release"}
        if kind in stages and self.cleanup_stage != stages[kind]:
            return self._attention("cleanup stage mismatch")
        self._seen.add(key)
        if event.get("uncertain"):
            return self._attention("uncertain state change", kind)
        if kind == "cccd_baseline":
            if type(event.get("value")) is not int or event.get("value") != 0: return self._attention("CCCD baseline not confirmed disabled")
            self.cccd_attempted, self.phase = True, "ENABLE_CCCD"
            return [Action("write_cccd", gen, 1)]
        if kind == "cccd_enabled":
            self.phase = "VERIFY_CCCD"; return [Action("read_cccd", gen)]
        if kind == "cccd_verified":
            if type(event.get("value")) is not int or event.get("value") != 1: return self._attention("CCCD enable not verified", "cccd_enabled")
            self.phase = "INIT_WRITE"; return [Action("initialize", gen, "F0/AF once")]
        if kind == "init_write_ok":
            if self.init_done: return self._attention("duplicate initialization")
            self.init_done, self.phase = True, "READ_SENSOR_BASELINE"
            return [Action("read_sensor_mode", gen)]
        if kind == "sensor_baseline":
            if type(event.get("value")) is not int or event.get("value") != 0: return self._attention("sensor baseline not confirmed disabled")
            self.phase, self.sensor_attempted = "ENABLE_SENSOR", True
            return [Action("enable_sensor", gen)]
        if kind == "sensor_enabled":
            self.phase = "VERIFY_SENSOR"; return [Action("verify_sensor", gen)]
        if kind == "sensor_verified":
            if event.get("enabled") is not True or not self.authorized or not self.context_valid:
                return self._attention("sensor not verified or context invalid")
            self.phase, self.output_enabled = "ACTIVE", True
            return [Action("start_output", gen)]
        if kind == "sensor_disabled":
            self.cleanup_stage = "sensor_readback"
            return [Action("read_sensor_mode", gen)]
        if kind == "sensor_cleanup_verified":
            if type(event.get("value")) is not int or event.get("value") != 0: return self._attention("sensor disable not verified", "sensor_disable")
            if self.cccd_attempted:
                self.cleanup_stage = "cccd_restore"; return [Action("restore_cccd", gen, 0)]
            self.cleanup_stage = "release"; return [Action("release_link", gen)]
        if kind == "cccd_restored":
            self.cleanup_stage = "cccd_readback"; return [Action("read_cccd", gen)]
        if kind == "cccd_restore_verified":
            if type(event.get("value")) is not int or event.get("value") != 0: return self._attention("CCCD restore not verified", "cccd_enabled")
            self.cleanup_stage = "release"; return [Action("release_link", gen)]
        if kind == "released":
            if event.get("both_profiles_clear") is not True: return self._attention("profile release not verified", "release")
            self.phase, self.generation, self.owned_link = "IDLE", None, False
            self.cleanup_stage = None
            self.cccd_attempted = self.sensor_attempted = False
            return [Action("cleanup_complete")]
        return self._attention("invalid cleanup event")

    def _retry(self, now, return_actions=False):
        if self.authorized and self.context_valid and self.retry_used < 2:
            delay = (5, 15)[self.retry_used]
            self.retry_at, self.retry_used, self.phase = now + delay, self.retry_used + 1, "BACKOFF"
            actions = [Action("retry_at", value=self.retry_at)]
        else:
            self.phase, self.retry_at = ("ATTENTION", None) if self.authorized else ("IDLE", None)
            actions = [Action("attention", value="retry budget exhausted")] if self.phase == "ATTENTION" else []
        return actions if return_actions else actions
