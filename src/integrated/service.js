'use strict';
// The native client registers its own app name. Only it may mutate settings/run state.
const fs = require('fs'), path = require('path'), cp = require('child_process');
const APP = 'org.magicsirimote.app';
function createService({Handle = require('palmbus').Handle, timers = globalThis, processExit = () => process.exit(0)} = {}) {
  if (global.unified_service) throw Error('Service already initialized');
  global.unified_service = true;
  const handle = new Handle(APP + '.service');
  let tail = Promise.resolve(), controller = null;
  function trace(stage) {
    try { fs.writeFileSync(path.join(__dirname, 'state', 'control-status.json'),
      JSON.stringify({stage, pid: process.pid, epochMs: Date.now()}), {mode: 0o640}); } catch (_) {}
  }
  let lifetime;
  function keepAlive() {
    timers.clearTimeout(lifetime);
    lifetime = timers.setTimeout(() => {
      if (controller && controller.exitCode === null) { keepAlive(); return; }
      trace('idle-exit'); handle.unregister(); global.unified_service = false;
      processExit();
    }, 60000);
  }
  keepAlive();
  const respond = (message, value) => { try { message.respond(JSON.stringify(value)); } catch (_) {} };
  function helper(method, params) {
    trace('helper-' + method);
    return new Promise(resolve => {
      const child = cp.execFile('/usr/bin/python3', ['-I', '-B', path.join(__dirname, 'control.py'), method],
        {timeout: 5000, maxBuffer: 16384}, (error, stdout) => {
          trace(error ? 'helper-failed' : 'helper-finished');
          if (error) { resolve({returnValue: false, status: 'control-unavailable'}); return; }
          try { resolve(JSON.parse(stdout)); } catch (_) { resolve({returnValue: false, status: 'invalid-control-response'}); }
        });
      child.stdin.on('error', () => {});
      child.stdin.end(JSON.stringify(params));
    });
  }
  function launch() {
    return new Promise(resolve => {
      if (controller && controller.exitCode === null) { resolve({returnValue: true, status: 'already-running'}); return; }
      const file = path.join(__dirname, 'state', 'controller-output.log');
      const fd = fs.openSync(file, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_APPEND | fs.constants.O_NOFOLLOW, 0o640);
      let bytes = fs.fstatSync(fd).size;
      const child = cp.spawn('/usr/bin/python3', ['-I', '-B', path.join(__dirname, 'roles/controller/native_probe.py')],
        {stdio: ['ignore', 'pipe', 'pipe']});
      controller = child;
      let closed = false;
      function close() { if (!closed) { closed = true; fs.closeSync(fd); } }
      function log(data) { const n = Math.min(data.length, Math.max(0, 65536 - bytes)); if (n > 0) { fs.writeSync(fd, data, 0, n); bytes += n; } }
      child.stdout.on('data', log); child.stderr.on('data', log);
      child.once('spawn', () => resolve({returnValue: true, status: 'starting', pid: child.pid}));
      child.once('error', () => { close(); resolve({returnValue: false, status: 'spawn-failed'}); });
      child.once('close', () => { close(); if (controller === child) controller = null; });
    });
  }
  for (const method of ['status', 'configure', 'start', 'stop']) handle.registerMethod('/', method);
  handle.addListener('request', message => {
    trace('request-received');
    keepAlive();
    const work = async () => {
      try {
        const method = message.method(), raw = message.payload();
        if (!['status', 'configure', 'start', 'stop'].includes(method) || message.category() !== '/' || message.isSubscription() !== false || typeof raw !== 'string' || Buffer.byteLength(raw) > 8192) throw Error('Invalid request');
        if (method !== 'status' && message.senderServiceName() !== APP) throw Error('Open the native application to change runtime settings');
        const params = JSON.parse(raw);
        if (!params || typeof params !== 'object' || Array.isArray(params)) throw Error('Invalid request');
        let value = await helper(method, params);
        if (method === 'start' && value.returnValue === true && value.status === 'start-ready') value = await launch();
        respond(message, value); trace('responded');
      } catch (_) { respond(message, {returnValue: false, status: 'request-rejected'}); }
    };
    // palmbus delivers through GLib. Enter a Node callback before scheduling
    // promises, so requests do not wait for an unrelated Node timer to fire.
    setImmediate(() => { tail = tail.then(work, work); });
  });
  return {handle};
}
module.exports = {createService};
