'use strict';
// The native client registers its own app name. Only it may mutate settings/run state.
const fs = require('fs'), path = require('path'), cp = require('child_process');
const APP = 'org.magicsirimote.app';
const startupModule = require('./startup');
const processModule = require('./process-read');
const {createPowerReader} = require('./power-client');
const {createControllerPreloader} = require('./controller-preload');
const {createPowerHints} = require('./power-hints');
const {createPowerObserver} = require('./power-observer');
// Keep current startup timings even after the bounded general log fills.
// Only fixed timing fields are retained; preparation tokens and input are excluded.
function createTimingRecorder(pid, write) {
  let pending = '', discard = false;
  const events = [];
  return data => {
    let text = data.toString('utf8');
    if (discard) {
      const end = text.indexOf('\n');
      if (end < 0) return;
      text = text.slice(end + 1); discard = false;
    }
    pending += text;
    let end;
    while ((end = pending.indexOf('\n')) >= 0) {
      const line = pending.slice(0, end); pending = pending.slice(end + 1);
      if (line.length > 4096 || events.length >= 32) continue;
      try {
        const event = JSON.parse(line);
        if (!Number.isSafeInteger(pid) || pid <= 0 || !event ||
            event.stage !== 'runtime-startup-timing' || event.role !== 'controller' || event.pid !== pid ||
            typeof event.step !== 'string' || !/^[a-z][a-z-]{0,63}$/.test(event.step) ||
            !Number.isSafeInteger(event.epochMs) || event.epochMs <= 0 ||
            !Number.isSafeInteger(event.elapsedMs) || event.elapsedMs < 0 || event.elapsedMs > 600000) continue;
        events.push({stage:event.stage, role:event.role, step:event.step, pid,
          epochMs:event.epochMs, elapsedMs:event.elapsedMs});
        write({schema:1, pid, events:events.map(value => ({...value}))});
      } catch (_) {} // Diagnostic output must never interrupt control or logging.
    }
    if (pending.length > 4096) { pending = ''; discard = true; }
  };
}

function createService({Handle = require('palmbus').Handle, timers = globalThis, processExit = () => process.exit(0), startupFactory = startupModule.createStartup, startupStore, processReader = () => processModule.processes(__dirname), powerReader = createPowerReader({timers}), controllerLauncher = null, preloaderFactory = createControllerPreloader} = {}) {
  if (global.unified_service) throw Error('Service already initialized');
  global.unified_service = true;
  const handle = new Handle(APP + '.service');
  let tail = Promise.resolve(), controller = null;
  const startup = startupFactory({store: startupStore || startupModule.disk(path.join(__dirname, 'state/startup-private')),
    activity: (method, params, subscribe) => method === 'getDetails' ? new Promise(resolve => {
      cp.execFile('/usr/bin/python3', ['-I', '-B', path.join(__dirname, 'activity-read.py')],
        {timeout: 5000, maxBuffer: 8192}, (error, stdout) => {
          try { resolve({value: error ? null : JSON.parse(stdout)}); } catch (_) { resolve({value: null}); }
        });
    }) : startupModule.activityCall(handle, method, params, subscribe, timers)});
  const preloader = preloaderFactory({spawn: spawnController, timers});
  function trace(stage, filename = 'control-status.json') {
    try { fs.writeFileSync(path.join(__dirname, 'state', filename),
      JSON.stringify({stage, pid: process.pid, epochMs: Date.now()}), {mode: 0o640}); } catch (_) {}
  }
  let lifetime;
  function keepAlive() {
    timers.clearTimeout(lifetime);
    lifetime = timers.setTimeout(() => {
      if ((controller && controller.exitCode === null) || startup.summary().enabled) { keepAlive(); return; }
      powerHints.close(); powerObserver.close(); powerReader.close(); trace('idle-exit'); handle.unregister(); global.unified_service = false;
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
  function spawnController(preparation = null) {
    const file = path.join(__dirname, 'state', 'controller-output.log');
    const fd = fs.openSync(file, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_APPEND | fs.constants.O_NOFOLLOW, 0o640);
    let bytes = fs.fstatSync(fd).size, child, closed = false;
    function close() { if (!closed) { closed = true; fs.closeSync(fd); } }
    try {
      child = cp.spawn('/usr/bin/python3', ['-I', '-B', path.join(__dirname, 'roles/controller/native_probe.py')],
        {stdio: [preparation ? 'pipe' : 'ignore', 'pipe', 'pipe'],
         env: preparation ? {...process.env, MAGIC_SIRIMOTE_PRELOAD: preparation} : process.env});
    } catch (error) { close(); throw error; }
    controller = child;
    function log(data) { if (closed) return; const n = Math.min(data.length, Math.max(0, 65536 - bytes)); if (n > 0) { fs.writeSync(fd, data, 0, n); bytes += n; } }
    const recordTiming = createTimingRecorder(child.pid, value => {
      const target = path.join(__dirname, 'state/controller-startup-timing.json');
      const temporary = target + '.tmp-' + process.pid;
      let timingFd;
      try {
        timingFd = fs.openSync(temporary, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_TRUNC | fs.constants.O_NOFOLLOW, 0o640);
        fs.fchmodSync(timingFd, 0o640);
        fs.writeFileSync(timingFd, JSON.stringify(value));
        fs.closeSync(timingFd); timingFd = undefined;
        fs.renameSync(temporary, target);
      } finally {
        if (timingFd !== undefined) fs.closeSync(timingFd);
      }
    });
    child.stdout.on('data', data => { recordTiming(data); log(data); }); child.stderr.on('data', log);
    child.once('error', close);
    child.once('close', () => { close(); if (controller === child) controller = null; });
    return child;
  }
  function launch() {
    return new Promise(resolve => {
      if (controller && controller.exitCode === null) { resolve({returnValue: true, status: 'already-running'}); return; }
      const child = spawnController();
      child.once('spawn', () => resolve({returnValue: true, status: 'starting', pid: child.pid}));
      child.once('error', () => resolve({returnValue: false, status: 'spawn-failed'}));
    });
  }
  async function cancelPreparation() {
    if (await preloader.cancel() !== true) throw Error('Prepared controller has not exited');
  }
  async function startInput() {
    await cancelPreparation();
    let value = await helper('start', {});
    if (value.returnValue === true && value.status === 'start-ready') value = await launch();
    return value;
  }
  async function startAutomaticInput() {
    // Power/maintenance authorization belongs to startup.poll. Recheck live
    // processes immediately before launch; the controller validates both code
    // pins and saved settings before publishing its session or using Bluetooth.
    const actual = processReader(), found = preloader.filter(actual);
    if (['controller', 'receiver', 'legacy', 'ui'].some(role => !Array.isArray(found[role]) || found[role].length))
      return {returnValue: false, status: 'input-process-changed'};
    const prepared = await preloader.activate(actual);
    if (prepared !== null) return prepared;
    return controllerLauncher ? controllerLauncher() : launch();
  }
  function power() { return powerReader.read(); }
  let retiredCandidate = null;
  async function recoverUnstarted() {
    // These files are hints only. The helper independently checks ownership,
    // expiry, the exclusive lease, code pins and absence of all receiver I/O.
    try {
      const directory = path.join(__dirname, 'roles/receiver/state');
      const file = path.join(directory, 'request.json');
      let q, fd;
      try {
        fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
        const info = fs.fstatSync(fd);
        if (!info.isFile() || info.nlink !== 1 || info.size <= 0 || info.size > 2048) return false;
        const raw = Buffer.alloc(2049), count = fs.readSync(fd, raw, 0, 2049, 0);
        if (count !== info.size) return false;
        q = JSON.parse(raw.subarray(0, count).toString('utf8'));
      } finally { if (fd !== undefined) fs.closeSync(fd); }
      if (!q || !/^[a-f0-9]{32}$/.test(q.run) || !Number.isSafeInteger(q.expiresEpochMs)
          || q.expiresEpochMs >= Date.now() || retiredCandidate === q.run) return false;
      if (['borrowed-active','recovery-request.json', ...['start','result','ready','progress'].map(k => 'receiver-'+k+'-'+q.run+'.json')]
          .some(name => fs.existsSync(path.join(directory, name)))) return false;
      retiredCandidate = q.run;
      const reply = await helper('retireUnstarted', {});
      return reply.returnValue === true && reply.status === 'retired-unstarted';
    } catch (_) { return false; }
  }
  function powerDependencies() {
    return {power, recoverUnstarted, status: async () => ({returnValue: true, processes: preloader.filter(processReader())}), start: startAutomaticInput, stop: async () => { await cancelPreparation(); return helper('stop', {}); }};
  }
  async function checkDuringCompletion(poll) {
    const result = await poll(powerDependencies());
    if (result && result.pollAfterMs === 150) {
      await new Promise(resolve => timers.setTimeout(resolve, 150));
      await poll(powerDependencies());
    }
  }
  const powerObserver = createPowerObserver({timers,
    enqueue(work) { tail = tail.then(work, work); return tail; },
    poll: () => startup.poll(powerDependencies()),
    wake: () => startup.wake(powerDependencies()),
    onError: () => trace('startup-attention')});
  const powerHints = createPowerHints(handle, {timers, onActive: powerObserver.notifyActive});
  // Preparation has no Bluetooth or state writes. Only powerDependencies.start
  // can release its private pipe after the ordinary durable power/start gate.
  try {
    const state = startup.summary(), found = processReader();
    if (state.enabled && state.registered && ['controller','receiver','legacy','ui'].every(role => Array.isArray(found[role]) && found[role].length === 0))
      preloader.prepare();
  } catch (_) { trace('controller-preload-unavailable'); }

  const methods = ['status', 'preview', 'configure', 'reset', 'start', 'stop', 'drain', 'resume', 'startupPrepare', 'startupBind', 'startupDisable', 'startupRepair', 'startupCancelled', 'startupTick'];
  for (const method of methods) handle.registerMethod('/', method);
  handle.addListener('request', message => {
    trace('request-received');
    keepAlive();
    const work = async () => {
      try {
        const method = message.method(), raw = message.payload();
        if (!methods.includes(method) || message.category() !== '/' || message.isSubscription() !== false || typeof raw !== 'string' || Buffer.byteLength(raw) > 8192) throw Error('Invalid request');
        if (method === 'preview' && message.senderServiceName() !== 'com.webos.service.contentminer') throw Error('Unexpected preview caller');
        if (!['status', 'startupTick', 'preview'].includes(method) && message.senderServiceName() !== APP) throw Error('Open the native application to change runtime settings');
        const params = JSON.parse(raw);
        if (!params || typeof params !== 'object' || Array.isArray(params)) throw Error('Invalid request');
        let value;
        // Loading the service starts its existing serialized power observer.
        // A preview must not enable input, reset an attempt or alter the Activity.
        if (method === 'preview') { trace('preview-accepted', 'preview-status.json'); value = {returnValue: true}; }
        else if (method === 'startupTick') value = await startup.tick(message, params, checkDuringCompletion);
        else if (method === 'startupPrepare' && Object.keys(params).length === 0) value = startup.prepare();
        else if (method === 'startupBind' && Object.keys(params).sort().join(',') === 'activityId,token') value = startup.bind(params);
        else if (method === 'startupRepair' && Object.keys(params).length === 0) value = await startup.repair();
        else if (method === 'startupCancelled' && Object.keys(params).sort().join(',') === 'activityId,resetToken') value = startup.cancelled(params);
        else if (method === 'startupDisable' && Object.keys(params).length === 0) { value = startup.disable(); await cancelPreparation(); }
        else if (method === 'start' && Object.keys(params).length === 0) { startup.manualStart(); value = await startInput(); }
        else if (method === 'stop' && Object.keys(params).length === 0) { startup.disable(); await cancelPreparation(); value = await helper('stop', params); }
        else if (method === 'drain' && Object.keys(params).length === 0) { await cancelPreparation(); value = await helper('stop', params); }
        else if (method === 'resume' && Object.keys(params).length === 0) value = startup.resume();
        else if (method === 'reset') {
          if (startup.summary().enabled) throw Error('Stop automatic startup before resetting');
          value = await helper(method, params);
        }
        else if (['status', 'configure'].includes(method)) value = await helper(method, params);
        else throw Error('Invalid request');
        if (method === 'status') { value.startup = startup.summary(); value.automaticStartupRegistered = value.startup.registered; }
        respond(message, value); trace('responded');
      } catch (_) { respond(message, {returnValue: false, status: 'request-rejected'}); }
    };
    // palmbus delivers through GLib. Enter a Node callback before scheduling
    // promises, so requests do not wait for an unrelated Node timer to fire.
    setImmediate(() => { tail = tail.then(work, work); });
  });
  return {handle};
}
module.exports = {createService, createTimingRecorder};
