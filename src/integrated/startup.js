'use strict';
// One persistent Activity owned by the native app; one input start per boot/power cycle.
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const APP = 'org.magicsirimote.app', NAME = APP + '.startup';
const HEX = /^[a-f0-9]{48}$/;
function disk(directory) {
  try { fs.mkdirSync(directory, {mode: 0o700}); } catch (error) { if (error.code !== 'EEXIST') throw error; }
  // Observed webOS boot/install permissions include 0775 and 0777. Only our own
  // exact directory/file may be tightened again; links/other owners fail closed.
  const dirfd = fs.openSync(directory, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW);
  try {
    const info = fs.fstatSync(dirfd);
    if (!info.isDirectory() || info.uid !== process.getuid() || ![0o700, 0o775, 0o777].includes(info.mode & 0o777)) throw Error('Startup directory unavailable');
    if ((info.mode & 0o777) !== 0o700) fs.fchmodSync(dirfd, 0o700);
  } finally { fs.closeSync(dirfd); }
  return {
    read() {
      let fd;
      try { fd = fs.openSync(path.join(directory, 'startup.json'), fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW); }
      catch (error) { if (error.code === 'ENOENT') return null; throw error; }
      try {
        const s = fs.fstatSync(fd);
        if (!s.isFile() || s.uid !== process.getuid() || s.nlink !== 1 || ![0o600, 0o775, 0o777].includes(s.mode & 0o777) || s.size > 4096) throw Error('Startup state unavailable');
        if ((s.mode & 0o777) !== 0o600) fs.fchmodSync(fd, 0o600);
        const value = JSON.parse(fs.readFileSync(fd, 'utf8'));
        if (value.schema !== 1 || !HEX.test(value.token) || typeof value.enabled !== 'boolean' || !['prepared', 'ready', 'completing', 'attention', 'cancel-pending'].includes(value.phase)) throw Error('Startup state invalid');
        return value;
      } finally { fs.closeSync(fd); }
    },
    write(value) {
      const temp = path.join(directory, '.' + crypto.randomBytes(12).toString('hex'));
      const fd = fs.openSync(temp, 'wx', 0o600);
      try { fs.writeFileSync(fd, JSON.stringify(value) + '\n'); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
      fs.renameSync(temp, path.join(directory, 'startup.json'));
      const dir = fs.openSync(directory, 'r'); try { fs.fsyncSync(dir); } finally { fs.closeSync(dir); }
    }
  };
}
function activityCall(handle, method, params, subscribe = false, timers = globalThis) {
  return new Promise(resolve => {
    let request, ended = false, receivedAfterMs = null;
    const began = Date.now();
    const timer = timers.setTimeout(() => finish({returnValue: false, errorCode: -9003}), method === 'complete' ? 30000 : 6000);
    function finish(value) {
      if (ended) return; ended = true; timers.clearTimeout(timer);
      resolve({value, request, receivedAfterMs, elapsedMs: Date.now() - began});
    }
    try {
      request = (subscribe ? handle.subscribe : handle.call).call(handle,
        'luna://com.webos.service.activitymanager/' + method, JSON.stringify(params));
      request.addListener('response', message => {
        receivedAfterMs = Date.now() - began;
        setImmediate(() => {
        if (ended) return;
        try {
          const raw = message.payload(); if (typeof raw !== 'string' || Buffer.byteLength(raw) > 8192) throw Error();
          const value = JSON.parse(raw);
          if (!value || typeof value.returnValue !== 'boolean') throw Error();
          if (subscribe && value.returnValue && value.adopted !== true) return;
          finish(value);
        } catch (_) { finish({returnValue: false, errorCode: -9002}); }
        });
      });
    } catch (_) { finish({returnValue: false, errorCode: -9001}); }
  });
}
function createStartup({store, activity, boot = () => fs.readFileSync('/proc/sys/kernel/random/boot_id', 'utf8').trim(), now = Date.now, token = () => crypto.randomBytes(24).toString('hex')}) {
  const serviceCreatedAt = now();
  let sample = null, repeated = 0, sampleAt = null, sampleReadStartedAt = null;
  const load = () => store.read();
  function summary() {
    const s = load();
    return {enabled: !!(s && s.enabled), registered: !!(s && s.phase === 'ready'), phase: s ? s.phase : 'not-registered', lastOutcome: s ? s.lastOutcome || null : null, lastFailure: s ? s.lastFailure || null : null, lastTick: s ? s.lastTick || null : null, lastStartTiming: s ? s.lastStartTiming || null : null};
  }
  function prepare() {
    let s = load();
    if (s) {
      // A new explicit Start may retry a rejected create. The native creator
      // always uses the same unique name with replace:false, so an uncertain
      // prior create cannot be overwritten or create a second Activity.
      if (s.phase === 'prepared') return {returnValue: true, status: 'create-required', token: s.token, activityName: NAME};
      if (['attention', 'completing'].includes(s.phase)) return {returnValue: true, status: 'repair-required'};
      if (s.phase !== 'ready') throw Error('Automatic startup registration needs attention');
      s.enabled = true; store.write(s);
      return {returnValue: true, status: 'registered', activityId: s.activityId};
    }
    s = {schema: 1, token: token(), phase: 'prepared', enabled: true, activityId: null, power: null, attempt: null};
    store.write(s);
    return {returnValue: true, status: 'create-required', token: s.token, activityName: NAME};
  }
  function bind(params) {
    const s = load();
    if (!s || s.phase !== 'prepared' || params.token !== s.token || !Number.isSafeInteger(params.activityId) || params.activityId < 1) throw Error('Startup binding differs');
    s.activityId = params.activityId; s.phase = 'ready'; store.write(s);
    return {returnValue: true, status: 'registered'};
  }
  function disable() {
    const s = load(); if (s) { s.enabled = false; store.write(s); }
    return {returnValue: true, status: 'disabled'};
  }
  function key(s, bootId) { return bootId + ':' + (s.power && s.power.boot === bootId ? s.power.cycle : 0); }
  function manualStart() {
    const s = load();
    if (s) { s.enabled = true; s.attempt = key(s, boot()); s.lastOutcome = 'manual-start'; store.write(s); }
  }
  function resume() {
    const s = load();
    // Only the native app can finish a settings pause. Never undo an installer
    // maintenance stop, and leave uncertain registration outcomes untouched.
    if (!s || !s.enabled || s.phase !== 'ready') return {returnValue: true, status: 'unchanged'};
    s.attempt = null; s.lastOutcome = 'waiting-for-window-close'; store.write(s);
    return {returnValue: true, status: 'resume-pending'};
  }
  function cancelled(params) {
    const s = load();
    if (!s || s.phase !== 'cancel-pending' || params.activityId !== s.activityId || params.resetToken !== s.resetToken) throw Error('Cancellation acknowledgement differs');
    store.write({schema: 1, token: token(), phase: 'prepared', enabled: true, activityId: null,
      previousActivityId: s.activityId, power: s.power, attempt: s.attempt});
    return {returnValue: true, status: 'cancelled'};
  }
  async function tick(message, params, duringCompletion) {
    let s = load();
    if (!s || !['prepared', 'ready'].includes(s.phase) || message.senderServiceName() !== 'com.webos.service.activitymanager' || message.applicationID() !== APP
        || Object.keys(params).sort().join(',') !== '$activity,token' || params.token !== s.token
        || !params.$activity || !Number.isSafeInteger(params.$activity.activityId) || params.$activity.activityId < 1
        || (s.activityId !== null && params.$activity.activityId !== s.activityId)) return {returnValue: false, status: 'callback-rejected'};
    // A genuine callback can finish binding a create whose acknowledgement was lost.
    s.activityId = params.$activity.activityId;
    const next = token(); s.phase = 'completing'; s.nextToken = next; store.write(s);
    const completing = {active: false, token: s.token, nextToken: next, activityId: s.activityId};
    const current = () => {
      const value = load();
      return value && value.phase === 'completing' && value.token === completing.token
        && value.nextToken === next && value.activityId === completing.activityId ? value : null;
    };
    let lease, failedStage = 'adopt', errorCode = null, lastCall, inputCheckFailed = false;
    const startedAt = now();
    try {
      const adopted = await activity('adopt', {activityId: s.activityId, subscribe: true, wait: false}, true);
      lease = adopted.request; lastCall = adopted;
      errorCode = adopted.value && adopted.value.errorCode;
      if (!adopted.value || adopted.value.returnValue !== true || adopted.value.adopted !== true) throw Error('Adoption unconfirmed');
      failedStage = 'complete'; errorCode = null;
      const schedule = {start: new Date(now() + 60000).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, 'Z')};
      // Keep external mutations serialized, but allow power/input preparation
      // while ActivityManager persists the next callback. The capability exists
      // only after adoption; a saved "completing" record cannot authorize a start.
      const pending = activity('complete', {activityId: s.activityId, restart: true, schedule,
        callback: {method: 'luna://' + APP + '.service/startupTick', params: {token: next}}})
        .then(value => ({value}), error => ({error}));
      completing.active = true;
      if (duringCompletion) {
        try { await duringCompletion(deps => completing.active ? poll(deps, completing) : Promise.resolve()); }
        catch (_) { inputCheckFailed = true; }
      }
      completing.active = false;
      const settled = await pending;
      if (settled.error) throw settled.error;
      const complete = settled.value;
      lastCall = complete;
      errorCode = complete.value && complete.value.errorCode;
      if (!complete.value || complete.value.returnValue !== true) throw Error('Completion unconfirmed');
      s = current();
      if (!s) return {returnValue: false, status: 'registration-state-changed'};
      s.token = next; delete s.nextToken; s.phase = 'ready';
      s.lastTick = {epochMs: now(), elapsedMs: now() - startedAt,
        receivedAfterMs: Number.isFinite(lastCall.receivedAfterMs) ? lastCall.receivedAfterMs : null};
      if (inputCheckFailed) s.lastTick.inputCheckFailed = true;
      store.write(s);
      return {returnValue: true, status: 'scheduled'};
    } catch (_) {
      s = current();
      if (!s) return {returnValue: false, status: 'registration-state-changed'};
      s.phase = 'attention';
      s.lastFailure = {stage: failedStage, errorCode: Number.isSafeInteger(errorCode) ? errorCode : null,
        receivedAfterMs: lastCall && Number.isFinite(lastCall.receivedAfterMs) ? lastCall.receivedAfterMs : null,
        epochMs: now(), elapsedMs: now() - startedAt, uptimeSeconds: Math.floor(process.uptime())};
      store.write(s);
      return {returnValue: false, status: 'registration-needs-attention-' + failedStage,
        errorText: failedStage + ' unconfirmed (' + (Number.isSafeInteger(errorCode) ? errorCode : 'no reply') + ')'};
    } finally { completing.active = false; if (lease) { try { lease.cancel(); } catch (_) {} } }
  }
  async function repair() {
    const s = load();
    if (s && s.phase === 'prepared') {
      // Reinstallation can remove our local record but leave a terminal OS
      // reservation. Read details in the service; only the native creator cancels.
      const read = await activity('getDetails', {activityName: NAME, internal: false, current: false});
      const a = read.value && read.value.returnValue === true && read.value.activity;
      const callback = a && a.callback, params = callback && callback.params;
      if (!a || a.name !== NAME || !Number.isSafeInteger(a.activityId) || a.activityId < 1
          || !a.creator || a.creator.serviceId !== APP
          || !callback || callback.method !== 'luna://' + APP + '.service/startupTick'
          || !params || Object.keys(params).join(',') !== 'token' || !HEX.test(params.token || '')
          || !['failed', 'expired'].includes(a.state)
          || !Array.isArray(a.adopters) || a.adopters.length
          || !Array.isArray(a.subscribers) || a.subscribers.length) {
        return {returnValue: false, errorText: 'Existing startup reservation cannot be safely replaced'};
      }
      const fresh = load();
      if (!fresh || fresh.phase !== 'prepared' || fresh.token !== s.token) throw Error('Startup registration changed');
      s.activityId = a.activityId; s.phase = 'cancel-pending'; s.resetToken = token(); store.write(s);
      return {returnValue: true, status: 'cancel-required', activityId: s.activityId, resetToken: s.resetToken};
    }
    if (!s || !['ready', 'attention', 'completing'].includes(s.phase)) throw Error('Startup is not ready');
    const read = await activity('getDetails', {activityId: s.activityId, internal: false, current: false});
    const a = read.value && read.value.activity;
    if (!read.value || read.value.returnValue !== true || !a) return {returnValue: false, status: 'startup-query-' + (read.value ? String(read.value.errorCode || 'invalid-response') : 'no-response'), errorText: read.value && typeof read.value.errorText === 'string' ? read.value.errorText.slice(0, 160) : undefined};
    const observedToken = a.callback && a.callback.params && a.callback.params.token;
    const committed = HEX.test(s.nextToken || '') && observedToken === s.nextToken;
    const checks = {id: a.activityId === s.activityId, name: a.name === NAME,
      creator: !!a.creator && a.creator.serviceId === APP,
      method: !!a.callback && a.callback.method === 'luna://' + APP + '.service/startupTick',
      token: observedToken === s.token || committed};
    const mismatch = Object.keys(checks).filter(k => !checks[k]);
    if (mismatch.length) return {returnValue: false, status: 'startup-mismatch-' + mismatch.join('-')};
    const terminal = ['expired', 'failed'].includes(a.state);
    if (s.phase !== 'ready' && !committed && !terminal) throw Error('Startup outcome is still uncertain');
    // Priority is fixed at creation. Replace only our verified, idle legacy
    // reservation; an active callback or uncertain completion stays untouched.
    const priorityUpgrade = s.phase === 'ready' && a.state === 'unsatisfied'
      && a.type && a.type.foreground === true;
    if (!terminal && !priorityUpgrade) {
      if (committed) { s.token = s.nextToken; delete s.nextToken; s.phase = 'ready'; store.write(s); }
      return {returnValue: true, status: 'registered'};
    }
    if (!Array.isArray(a.adopters) || a.adopters.length || !Array.isArray(a.subscribers) || a.subscribers.length) throw Error('Startup activity is in use');
    if (a.state === 'failed' || priorityUpgrade) {
      // Only the native creator cancels the exact verified reservation, with
      // durable acknowledgement before a new registration can be made.
      s.phase = 'cancel-pending'; s.resetToken = token(); store.write(s);
      return {returnValue: true, status: 'cancel-required', activityId: s.activityId, resetToken: s.resetToken};
    }
    if (committed) s.token = s.nextToken;
    delete s.nextToken; s.phase = 'ready'; store.write(s);
    return tick({senderServiceName: () => 'com.webos.service.activitymanager', applicationID: () => APP},
      {token: s.token, $activity: {activityId: s.activityId}});
  }
  async function poll({power, status, start, stop, recoverUnstarted}, completing, wakeOnly = false) {
    let s = load();
    const adoptedCompletion = s && completing && completing.active
      && s.phase === 'completing' && s.token === completing.token
      && s.nextToken === completing.nextToken && s.activityId === completing.activityId;
    if (!s || !s.enabled || (s.phase !== 'ready' && !adoptedCompletion)) return;
    const powerReadStartedAt = now();
    const p = await power();
    const powerReadFinishedAt = now();
    if (!p || (p.processing !== undefined && p.processing !== '')) { sample = null; repeated = 0; sampleAt = null; sampleReadStartedAt = null; return; }
    // Screen Off keeps playback/input alive, so the microphone can restore it.
    const kind = p.state === 'Active' ? 'active' : ['Active Standby', 'Suspend'].includes(p.state) ? 'standby' : null;
    if (!kind) { sample = null; repeated = 0; sampleAt = null; sampleReadStartedAt = null; return; }
    // Extra checks during completion may accelerate wake, never the normal
    // standby debounce or a cooperative stop.
    if ((completing || wakeOnly) && kind !== 'active') { sample = null; repeated = 0; sampleAt = null; sampleReadStartedAt = null; return; }
    if (sample === kind) repeated++; else { sample = kind; repeated = 1; sampleAt = powerReadFinishedAt; sampleReadStartedAt = powerReadStartedAt; }
    // Confirm wake promptly; keep the longer standby debounce for transient TV states.
    if (repeated < 2) return kind === 'active' ? {pollAfterMs: 150} : undefined;
    const bootId = boot();
    if (typeof bootId !== 'string' || !/^[a-f0-9-]{36}$/.test(bootId)) throw Error('Boot identity unavailable');
    let changed = false;
    if (!s.power || s.power.boot !== bootId) { s.power = {boot: bootId, state: kind, cycle: 0}; changed = true; }
    else if (s.power.state !== kind) { if (kind === 'active') s.power.cycle++; s.power.state = kind; changed = true; }
    if (changed) store.write(s);
    const statusReadStartedAt = now();
    const found = await status();
    const statusReadFinishedAt = now();
    if (!found || found.returnValue !== true || !found.processes) return;
    if (kind === 'standby') {
      if (found.processes.controller.length && s.stopCycle !== key(s, bootId)) {
        s.stopCycle = key(s, bootId); store.write(s); await stop();
      }
      return;
    }
    if (found.processes.controller.length || found.processes.receiver.length || found.processes.ui.length || found.processes.legacy.length) return;
    const attempt = key(s, bootId);
    if (s.attempt === attempt) {
      if (typeof recoverUnstarted !== 'function' || await recoverUnstarted() !== true) return;
      // Retirement proves no receiver ever started. It does not establish
      // current power; take fresh observations before authorizing replacement.
      s.attempt = null; s.lastOutcome = 'unstarted-request-retired'; store.write(s);
      sample = null; repeated = 0; sampleAt = null; sampleReadStartedAt = null;
      return {pollAfterMs: 150};
    }
    s.lastStartTiming = {serviceCreatedAt, firstActiveReadStartedAt: sampleReadStartedAt,
      firstActiveSampleAt: sampleAt, activeConfirmedAt: powerReadFinishedAt,
      statusReadStartedAt, statusReadFinishedAt, startRequestedAt: now(), startReturnedAt: null};
    s.attempt = attempt; s.lastOutcome = 'starting'; store.write(s);
    const result = await start();
    s.lastStartTiming.startReturnedAt = now();
    s.lastOutcome = result && result.returnValue === true ? result.status : 'start-needs-attention'; store.write(s);
  }
  return {summary, prepare, bind, disable, manualStart, resume, cancelled, tick, repair, poll: deps => poll(deps), wake: deps => poll(deps, null, true)};
}
module.exports = {APP, NAME, disk, activityCall, createStartup};
