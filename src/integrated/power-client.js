'use strict';
// One read-only helper; each reply must match the current request and process.
const cp = require('child_process'), path = require('path');
function createPowerReader({spawn = cp.spawn, timers = globalThis, directory = __dirname} = {}) {
  let current = null, sequence = 0, closed = false;
  function retire(session) {
    if (current === session) current = null;
    const pending = session.pending;
    session.pending = null;
    if (pending) { timers.clearTimeout(pending.timer); pending.resolve(null); }
    try { session.child.stdin.end(); } catch (_) {}
    try { session.child.kill(); } catch (_) {}
  }
  function open() {
    const child = spawn('/usr/bin/python3', ['-I', '-B', path.join(directory, 'power-read.py'), '--serve'],
      {stdio: ['pipe', 'pipe', 'ignore']});
    const session = {child, buffer: '', pending: null};
    current = session;
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', data => {
      if (current !== session) return;
      session.buffer += data;
      if (Buffer.byteLength(session.buffer) > 2048) { retire(session); return; }
      const end = session.buffer.indexOf('\n');
      if (end < 0) return;
      try {
        const value = JSON.parse(session.buffer.slice(0, end)), pending = session.pending;
        if (end !== session.buffer.length - 1 || !pending || !value || value.id !== pending.id
            || !value.power || typeof value.power !== 'object' || Array.isArray(value.power)
            || typeof value.power.state !== 'string') throw Error('Unexpected power reply');
        session.buffer = ''; session.pending = null;
        timers.clearTimeout(pending.timer); pending.resolve(value.power);
      } catch (_) { retire(session); }
    });
    child.once('error', () => retire(session));
    child.once('exit', () => retire(session));
    child.stdout.once('error', () => retire(session));
    child.stdout.once('end', () => retire(session));
    child.stdin.once('error', () => retire(session));
    return session;
  }
  function read() {
    if (closed || (current && current.pending)) return Promise.resolve(null);
    let session;
    try { session = current || open(); } catch (_) { return Promise.resolve(null); }
    const id = ++sequence;
    if (!Number.isSafeInteger(id)) { retire(session); return Promise.resolve(null); }
    return new Promise(resolve => {
      const timer = timers.setTimeout(() => retire(session), 5000);
      session.pending = {id, resolve, timer};
      try { session.child.stdin.write(JSON.stringify({id}) + '\n'); }
      catch (_) { retire(session); }
    });
  }
  function close() { closed = true; if (current) retire(current); }
  return {read, close};
}
module.exports = {createPowerReader};
