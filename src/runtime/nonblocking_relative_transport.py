"""Offline, bounded transport prototype for grouped relative motion.

The caller owns all writers and semantic latches. This class owns only queued
immutable packets and the scheduled neutral cursor flush; it creates no I/O.
"""
from collections import deque
import math

from native_events import _KEYS
from relative_grouped_packets import (
    encode_grouped_relative_batch,
    encode_neutral_cursor_flush,
)


_ACTIONS = frozenset((*_KEYS, 'center'))
_FLUSH_DELAY = .020
_MAX_SECONDS = 30.
_MAX_ITEMS = 64
_MAX_BYTES = 128 * 1024
_MAX_AGE = .100


class NonblockingRelativeTransport:
    """Pump-driven FIFO; all writes happen synchronously inside API calls."""

    def __init__(self, writer, semantic_dispatch, *, clock, generation=1,
                 max_seconds=30., session_policy=None):
        if not callable(writer) or not callable(semantic_dispatch) or not callable(clock):
            raise ValueError('Caller-owned writer, semantic dispatcher and clock required')
        from input_session_policy import resolve_session_bounds
        max_seconds, _ = resolve_session_bounds(max_seconds, session_policy)
        if type(generation) is not int or generation < 0:
            raise ValueError('Valid generation and bounded session required')
        self.writer, self.semantic_dispatch, self.clock = writer, semantic_dispatch, clock
        self.generation = generation
        self.started = self.last_clock = clock()
        if type(self.started) not in (int, float) or not math.isfinite(self.started):
            raise ValueError('Finite monotonic clock required')
        self.max_seconds = float(max_seconds)
        self.queue = deque()
        self.queued_bytes = 0
        self.tail_due = None
        self.closed = self.failed = False
        self.reason = None
        self.body_writes = self.neutral_writes = self.semantic_dispatches = 0
        self.queued = self.dropped = 0
        self.discarded_motion = 0
        self._in_call = False

    def _now(self):
        if self.closed:
            return None
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < self.last_clock:
            self._close('clock-invalid', failed=True)
            return None
        self.last_clock = now
        if now - self.started >= self.max_seconds:
            self._close('deadline')
            return None
        return now

    def _close(self, reason, *, failed=False):
        if self.closed:
            return
        self.closed = True
        self.failed = failed
        self.reason = reason
        self.generation += 1
        self.dropped += len(self.queue)
        self.queue.clear()
        self.queued_bytes = 0
        self.tail_due = None

    def _write(self, packet, kind):
        try:
            count = self.writer(packet)
            if count != len(packet):
                raise OSError('Short write; no retry')
        except BaseException:
            self._close('write-uncertain', failed=True)
            return False
        if kind == 'body':
            self.body_writes += 1
        else:
            self.neutral_writes += 1
        return True

    def _enqueue(self, item, size, now):
        if (len(self.queue) >= _MAX_ITEMS or self.queued_bytes + size > _MAX_BYTES):
            self._close('queue-overflow', failed=True)
            return False
        self.queue.append((now, item, size))
        self.queued_bytes += size
        self.queued += 1
        return True

    def _fresh_queue(self, now):
        if self.queue and now - self.queue[0][0] > _MAX_AGE:
            self._close('queue-age-exceeded', failed=True)
            return False
        return True

    def _enter(self, token):
        if self.closed or type(token) is not int or isinstance(token, bool) or token != self.generation:
            return None
        if self._in_call:
            self._close('reentrant-call', failed=True)
            return None
        self._in_call = True
        now = self._now()
        if now is None or not self._fresh_queue(now):
            self._in_call = False
            return None
        return now

    def _leave(self):
        self._in_call = False

    def _post_callback_time(self):
        """Validate elapsed callback time against monotonicity and deadline."""
        return self._now()

    def motion(self, token, dx, dy):
        now = self._enter(token)
        if now is None:
            return False
        try:
            try:
                packet = bytes(encode_grouped_relative_batch(dx, dy))
            except BaseException:
                self._close('motion-encoding-rejected', failed=True)
                raise
            if self.queue:
                return self._enqueue(('motion', packet), len(packet), now)
            if not self._write(packet, 'body'):
                return False
            finished = self._post_callback_time()
            if finished is None:
                return False
            self.tail_due = finished + _FLUSH_DELAY
            return True
        finally:
            self._leave()

    def semantic(self, token, action, down):
        if action not in _ACTIONS or type(down) is not bool:
            raise ValueError('Supported native action and boolean transition required')
        now = self._enter(token)
        if now is None:
            return False
        try:
            if self.tail_due is not None or self.queue:
                return self._enqueue(('semantic', action, down), 0, now)
            return self._dispatch(action, down)
        finally:
            self._leave()

    def _dispatch(self, action, down):
        try:
            accepted = self.semantic_dispatch(action, down)
        except BaseException:
            self._close('semantic-dispatch-uncertain', failed=True)
            return False
        if accepted is True:
            self.semantic_dispatches += 1
        finished = self._post_callback_time()
        if finished is None:
            return False
        if accepted is not True:
            self._close('semantic-dispatch-rejected', failed=True)
            return False
        return True

    def pump(self, token):
        now = self._enter(token)
        if now is None:
            return False
        try:
            if self.tail_due is not None:
                if now < self.tail_due:
                    return False
                if not self._write(encode_neutral_cursor_flush(), 'neutral'):
                    return False
                now = self._post_callback_time()
                if now is None:
                    return False
                self.tail_due = None
            while self.queue and not self.closed:
                now = self._post_callback_time()
                if now is None or not self._fresh_queue(now):
                    return False
                queued_at, item, size = self.queue[0]
                if now - queued_at > _MAX_AGE:
                    self._close('queue-age-exceeded', failed=True)
                    return False
                self.queue.popleft()
                self.queued_bytes -= size
                if item[0] == 'semantic':
                    if not self._dispatch(item[1], item[2]):
                        return False
                    continue
                if not self._write(item[1], 'body'):
                    return False
                now = self._post_callback_time()
                if now is None:
                    return False
                self.tail_due = now + _FLUSH_DELAY
                # Drain adjacent motion frames in FIFO order. Stop at a
                # semantic barrier, whose dispatch must wait for this tail.
                while self.queue and self.queue[0][1][0] == 'motion':
                    now = self._post_callback_time()
                    if now is None or not self._fresh_queue(now):
                        return False
                    queued_at, next_item, next_size = self.queue[0]
                    if now - queued_at > _MAX_AGE:
                        self._close('queue-age-exceeded', failed=True)
                        return False
                    self.queue.popleft()
                    self.queued_bytes -= next_size
                    if not self._write(next_item[1], 'body'):
                        return False
                    now = self._post_callback_time()
                    if now is None:
                        return False
                    self.tail_due = now + _FLUSH_DELAY
                return True
            return True
        finally:
            self._leave()

    def next_timeout(self):
        if self.closed:
            return .02
        now = self._now()
        if now is None:
            return .02
        deadlines = [now + .02, self.started + self.max_seconds]
        if self.tail_due is not None:
            deadlines.append(self.tail_due)
        if self.queue:
            deadlines.append(self.queue[0][0] + _MAX_AGE)
        return max(0., min(.02, min(deadlines) - now))

    def discard_queued_motion(self, token):
        """Forget unsent movement after caller-observed tracking invalidation.

        Semantic transitions keep their FIFO order. The pending neutral tail
        belongs to a body already written and must not be delayed or replayed.
        This operation never writes or calls the semantic dispatcher.
        """
        now = self._enter(token)
        if now is None:
            return False
        try:
            retained = deque()
            removed = removed_bytes = 0
            for item in self.queue:
                if item[1][0] == 'motion':
                    removed += 1
                    removed_bytes += item[2]
                else:
                    retained.append(item)
            self.queue = retained
            self.queued_bytes -= removed_bytes
            self.dropped += removed
            self.discarded_motion += removed
            return True
        finally:
            self._leave()

    def stop(self, token):
        if (self.closed or type(token) is not int or isinstance(token, bool) or
                token != self.generation):
            return False
        self._close('stopped')
        return True

    def summary(self):
        return {
            'closed': self.closed, 'failed': self.failed, 'reason': self.reason,
            'generation': self.generation, 'bodyWrites': self.body_writes,
            'neutralWrites': self.neutral_writes,
            'semanticDispatches': self.semantic_dispatches,
            'queuedItems': len(self.queue), 'queuedBytes': self.queued_bytes,
            'queuedTotal': self.queued, 'droppedItems': self.dropped,
            'discardedMotionItems': self.discarded_motion,
            'pendingNeutralFlush': self.tail_due is not None,
            'automaticWriteRetries': 0,
        }
