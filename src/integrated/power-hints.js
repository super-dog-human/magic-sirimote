'use strict';
// Notifications only request a fresh power check; they never authorize input.
function createPowerHints(handle, {onActive, timers = globalThis, defer = setImmediate}) {
  let closed = false, current = null, retry = null;
  function retire(session) {
    if (current !== session) return;
    current = null;
    timers.clearTimeout(session.timer);
    try { session.request.cancel(); } catch (_) { return; }
    if (!closed) retry = timers.setTimeout(open, 30000);
  }
  function open() {
    retry = null;
    if (closed || current || typeof handle.subscribe !== 'function') return;
    const session = {request: null, timer: null, ready: false, acknowledged: false};
    current = session;
    try {
      session.request = handle.subscribe('luna://com.webos.service.tvpower/power/getPowerState', '{"subscribe":true}');
      session.timer = timers.setTimeout(() => retire(session), 6000);
      session.request.addListener('response', message => {
        // palmbus callbacks need a Node turn before promises run promptly.
        defer(() => {
          if (closed || current !== session) return;
          try {
            const raw = message.payload();
            if (typeof raw !== 'string' || Buffer.byteLength(raw) > 4096) throw Error('Invalid power notification');
            const value = JSON.parse(raw);
            if (!value || Array.isArray(value) || typeof value.state !== 'string'
                || (!session.acknowledged && (value.returnValue !== true || value.subscribed !== true))
                || (value.returnValue !== undefined && value.returnValue !== true)
                || (value.subscribed !== undefined && value.subscribed !== true)
                || (value.processing !== undefined && typeof value.processing !== 'string')) throw Error('Power subscription unavailable');
            // After the acknowledgement, a state-change event may omit the
            // acknowledgement fields. The fresh power reader still decides.
            session.acknowledged = true;
            timers.clearTimeout(session.timer);
            const ready = value.state === 'Active' && !value.processing;
            const changed = ready && !session.ready;
            session.ready = ready;
            if (changed) onActive();
          } catch (_) { retire(session); }
        });
      });
      session.request.addListener('error', () => retire(session));
    } catch (_) {
      if (session.request) retire(session);
      else { current = null; if (!closed) retry = timers.setTimeout(open, 30000); }
    }
  }
  function close() {
    closed = true;
    timers.clearTimeout(retry);
    if (current) retire(current);
  }
  open();
  return {close};
}
module.exports = {createPowerHints};
