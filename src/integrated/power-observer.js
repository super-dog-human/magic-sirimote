'use strict';
// Keep periodic fallback and notification checks on the same serialized queue.
function createPowerObserver({enqueue, poll, wake, timers = globalThis, onError = () => {}}) {
  let closed = false, scheduled = null, busy = false, pendingWake = false;
  function schedule(delay, hint = false) {
    if (closed) return;
    const item = {delay, handle: null};
    scheduled = item;
    item.handle = timers.setTimeout(() => {
      if (closed || scheduled !== item) return;
      scheduled = null; busy = true;
      Promise.resolve().then(() => enqueue(() => closed ? undefined : (hint ? wake() : poll())))
        .catch(() => { onError(); })
        .then(result => {
          busy = false;
          if (closed) return;
          const confirm = result && result.pollAfterMs === 150;
          const nextWake = pendingWake && !confirm;
          pendingWake = false;
          schedule(confirm ? 150 : nextWake ? 0 : 2000, nextWake);
        });
    }, delay);
  }
  function notifyActive() {
    if (closed) return;
    if (busy) { pendingWake = true; return; }
    // Never shorten the existing confirmation interval.
    if (scheduled && scheduled.delay === 150) return;
    if (scheduled) timers.clearTimeout(scheduled.handle);
    schedule(0, true);
  }
  function close() {
    closed = true; pendingWake = false;
    if (scheduled) timers.clearTimeout(scheduled.handle);
    scheduled = null;
  }
  schedule(0);
  return {notifyActive, close};
}
module.exports = {createPowerObserver};
