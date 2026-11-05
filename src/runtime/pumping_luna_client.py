"""Narrow, synchronous Luna client for an already-authorized cleanup executor.

This module performs no work on import. It accepts only target profile status
reads and one HID disconnect, and deliberately does not retry uncertain writes.
"""
import json
import math
import os
import selectors
import subprocess
import threading
import time
from contextlib import contextmanager
from functools import wraps

from lifecycle import REMOTE


BASE = "luna://com.webos.service.bluetooth2/"
COMMAND = "/usr/bin/luna-send-pub"
METHODS = {
    "hid/getStatus": (1.0, False),
    "gatt/getStatus": (1.0, False),
    "hid/disconnect": (8.0, True),
}
MAX_STDOUT = 65536
MAX_STDERR = 4096
PUMP_INTERVAL = 0.1
_native_scope = threading.local()


class NativeRequestScope:
    """One anonymous LS2 handle, lazily opened on this receiver thread."""
    def __init__(self, factory=None):
        self.factory = factory
        self.client = None
        self.owner = threading.get_ident()
        self.busy = False
        self.failed = False

    def request(self, method, params, *, timeout, guard, pump):
        if threading.get_ident() != self.owner or self.busy or self.failed:
            raise LunaCallError('Native transport unavailable')
        self.busy = True
        try:
            guard()
            if self.client is None:
                from persistent_status_client import PersistentStatusClient
                self.client = (self.factory or PersistentStatusClient)()
            return self.client._request(method, params, timeout=timeout, guard=guard, pump=pump)
        except BaseException:
            # Never fall back or repeat a request after an uncertain dispatch.
            self.failed = True
            raise
        finally:
            self.busy = False

    def renew_failed(self):
        # Only an explicit, closed idle-session boundary may use this. It does
        # not replay a failed request or grant input/sensor permission. The
        # caller must perform its independent mode-zero recovery afterwards.
        if threading.get_ident() != self.owner or self.busy:
            raise LunaCallError('Native transport renewal unavailable')
        if not self.failed:
            return False
        self.close()  # Unregister must succeed before a new handle can open.
        self.failed = False
        return True

    def close(self):
        if threading.get_ident() != self.owner or self.busy:
            raise LunaCallError('Native transport close unavailable')
        self.failed = True
        if self.client is not None:
            self.client.close()
            self.client = None


@contextmanager
def native_request_scope(*, enabled=True, factory=None):
    if not enabled:
        yield
        return
    if getattr(_native_scope, 'value', None) is not None:
        raise LunaCallError('Native transport scope already active')
    scope = NativeRequestScope(factory)
    _native_scope.value = scope
    try:
        yield scope
    finally:
        _native_scope.value = None
        scope.close()


def renew_failed_native_requests_after_idle():
    """Called after input/output closure and a newly observed live connection.

    Never retry the interrupted command. Only replace a poisoned handle after
    its exact callbacks/resources have been released, then use normal recovery.
    """
    scope=getattr(_native_scope,'value',None)
    return scope.renew_failed() if scope is not None else False


def with_native_requests(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        import runtime_bundle as bundle
        with native_request_scope(enabled=bundle.active()):
            return function(*args, **kwargs)
    return wrapped


class LunaCallError(RuntimeError):
    """A bounded call failed; intentionally excludes response/error contents."""


class LunaChildStopError(LunaCallError):
    """The exact subprocess has not been confirmed stopped."""


class PumpingLunaClient:
    """Caller guard verifies the live owned cleanup lease; euid is checked here."""

    _shared_native_transport = True

    def __init__(self, *, pump, guard, clock=time.monotonic, spawn=subprocess.Popen,
                 get_euid=os.geteuid, native_app=False):
        if (not callable(pump) or not callable(guard) or not callable(clock)
                or not callable(spawn) or not callable(get_euid)):
            raise ValueError("Injected pump, guard, clock, spawn and euid getter are required")
        self.pump = pump
        self.guard = guard
        self.clock = clock
        self.spawn = spawn
        if type(native_app) is not bool:
            raise ValueError("native_app must be a boolean")
        self.get_euid = get_euid
        self.native_app = native_app
        self._disconnect_consumed = False
        self._call_lock = threading.Lock()

    def __call__(self, method, params, timeout=None):
        if not self._call_lock.acquire(blocking=False):
            raise LunaCallError("Another Luna call is active")
        try:
            return self._call_serialized(method, params, timeout)
        finally:
            self._call_lock.release()

    def _call_serialized(self, method, params, timeout=None):
        method, allowed_timeout, is_write = self._validate_request(method, params, timeout)
        # Detach validated parameters before any injected guard/pump executes.
        # A shared mutable dictionary must not change the dispatched target or
        # stop-only value after policy validation.
        params = json.loads(json.dumps(params, separators=(",", ":")))
        timeout = allowed_timeout
        return self._dispatch(method, params, timeout, is_write)

    def _validate_request(self, method, params, timeout):
        if method not in METHODS:
            raise ValueError("Luna method is not allowed")
        allowed_timeout, is_write = METHODS[method]
        if (type(params) is not dict or set(params)!={"address"}
                or type(params["address"]) is not str or params["address"]!=REMOTE
                or (timeout is not None and (type(timeout) not in (int, float)
                                             or not math.isfinite(timeout)
                                             or timeout != allowed_timeout))):
            raise ValueError("Exact target parameters and bounded method timeout required")
        return method, allowed_timeout, is_write

    def _dispatch(self, method, params, timeout, is_write):
        if is_write:
            if self._disconnect_consumed:
                raise LunaCallError("One-shot disconnect already consumed")
            # Consume before UID/ownership guard and before Popen: even a spawn
            # error is an uncertain attempt and must never be retried.
            self._disconnect_consumed = True

        scope = getattr(_native_scope, 'value', None)
        if self.native_app and self._shared_native_transport and scope is not None:
            # Method/parameter budgets were consumed before this point. Both
            # paths use the current process's ordinary identity and same guard.
            return scope.request(method, params, timeout=timeout,
                                 guard=self._guard, pump=self.pump)

        started = self._now()
        last_time = started

        def now():
            nonlocal last_time
            value = self._now()
            if value < last_time:
                raise LunaCallError("Monotonic clock moved backwards")
            last_time = value
            return value

        deadline = started + timeout
        child = None
        selector = None
        stdout = bytearray()
        stderr_size = 0
        streams = {}
        try:
            self._guard()
            if now() >= deadline:
                raise LunaCallError("Call deadline expired before dispatch")
            encoded = json.dumps(params, separators=(",", ":"))
            argv = [COMMAND, "-i", "-f", BASE + method, encoded]
            child = self.spawn(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, close_fds=True)
            if child.stdout is None or child.stderr is None:
                raise LunaCallError("Subprocess pipes unavailable")
            selector = selectors.DefaultSelector()
            for stream, label in ((child.stdout, "stdout"), (child.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, label)
                streams[label] = stream

            exit_seen = False
            while True:
                current = now()
                if current >= deadline:
                    raise LunaCallError("Luna call timed out")
                events = selector.select(min(PUMP_INTERVAL, deadline - current))
                for key, _mask in events:
                    label = key.data
                    try:
                        chunk = os.read(key.fileobj.fileno(), 8192)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        streams.pop(label, None)
                        continue
                    if label == "stdout":
                        if len(stdout) + len(chunk) > MAX_STDOUT:
                            raise LunaCallError("Luna stdout exceeded bound")
                        stdout.extend(chunk)
                    else:
                        stderr_size += len(chunk)
                        if stderr_size > MAX_STDERR:
                            raise LunaCallError("Luna stderr exceeded bound")

                # Trusted monitor service is kept alive while Luna blocks.
                self.pump()
                self._guard()
                if now() >= deadline:
                    raise LunaCallError("Luna call timed out during monitor pump")
                # Interactive mode may stay open after a complete reply. Do
                # not wait for EOF: parse one object, then stop and reap the
                # exact child before returning it to the caller.
                if stdout:
                    try:
                        text = stdout.decode("utf-8").lstrip()
                        value, end = json.JSONDecoder().raw_decode(text)
                        if type(value) is not dict or text[end:].strip():
                            raise LunaCallError("Luna response was not a single object")
                        if not self._stop_child(child):
                            raise LunaChildStopError("Luna child stop unconfirmed")
                        self._guard()
                        return value
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        pass
                code = child.poll()
                if code is not None:
                    exit_seen = True
                if exit_seen and not streams:
                    break

            raise LunaCallError("Luna response was not valid JSON")
        except BaseException as error:
            if child is not None and not self._stop_child(child):
                raise LunaChildStopError("Luna child stop unconfirmed") from None
            if not isinstance(error, Exception):
                raise
            if isinstance(error, (ValueError, LunaCallError)):
                raise
            # Avoid embedding raw stdout/stderr or potentially sensitive
            # exception text in an executor's failure report.
            raise LunaCallError(type(error).__name__) from None
        finally:
            if selector is not None:
                selector.close()
            if child is not None:
                for stream in (child.stdout, child.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass

    def _now(self):
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise LunaCallError("Invalid monotonic clock")
        return value

    def _guard(self):
        # Check the OS credential first, before any possible Popen dispatch.
        uid = self.get_euid()
        if type(uid) is not int or uid <= 0:
            raise LunaCallError("Normal-UID execution required")
        if self.native_app:
            from native_app_identity import verify_self
            if verify_self() is not True:
                raise LunaCallError("Native application identity unverified")
        elif uid != 5415:
            raise LunaCallError("Normal-UID execution required")
        if self.guard() is not True:
            raise LunaCallError("Call guard rejected dispatch")

    @staticmethod
    def _stop_child(child):
        """Stop and reap only the exact Popen object created by this call."""
        try:
            if child.poll() is None:
                child.kill()
        except Exception:
            pass
        try:
            child.wait(timeout=1)
        except Exception:
            return False
        return child.poll() is not None
