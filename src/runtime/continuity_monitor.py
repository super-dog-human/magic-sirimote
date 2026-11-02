"""Bounded, nonblocking reads of a separately sampled control condition."""
import threading
import time

class ContinuityMonitor:
    def __init__(self, sample, *, clock=time.monotonic, interval=1.0, max_age=5.0):
        if not callable(sample) or not callable(clock) or not 0 < interval <= max_age <= 30:
            raise ValueError('invalid continuity monitor')
        self._sample=sample;self._clock=clock;self._interval=interval;self._max_age=max_age
        self._lock=threading.Lock();self._stop=threading.Event();self._first=threading.Event()
        self._thread=None;self._valid=False;self._at=None
    def start(self):
        if self._thread is not None:raise RuntimeError('monitor already started')
        self._thread=threading.Thread(target=self._run,name='control-continuity',daemon=True)
        self._thread.start()
    def _run(self):
        while not self._stop.is_set():
            try:valid=self._sample() is True
            except Exception:valid=False
            with self._lock:
                self._valid=valid;self._at=self._clock()
            self._first.set()
            if self._stop.wait(self._interval):break
    def wait_first(self,timeout):
        if self._thread is None or type(timeout) not in (int,float) or not 0 < timeout <= 15:raise ValueError('invalid first-sample wait')
        return self._first.wait(timeout) and self.current()
    def current(self):
        with self._lock:
            at=self._at;valid=self._valid
        now=self._clock()
        return not self._stop.is_set() and valid and at is not None and 0 <= now-at <= self._max_age
    def stop(self,timeout=10.0):
        if self._thread is None:return True
        self._stop.set();self._thread.join(timeout)
        return not self._thread.is_alive()
