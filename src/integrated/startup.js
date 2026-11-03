'use strict';
// One persistent Activity owned by the native app; one input start per boot/power cycle.
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const APP = 'org.magicsirimote.app', NAME = APP + '.startup';
const HEX = /^[a-f0-9]{48}$/;
function disk(directory) {
  try { fs.mkdirSync(directory, {mode: 0o700}); } catch (error) { if (error.code !== 'EEXIST') throw error; }
  // webOS restores developer-app paths to 0775 at cold boot. Only our own
  // exact directory/file may be tightened again; links/other owners fail closed.
  const dirfd = fs.openSync(directory, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW);
  try {
    const info = fs.fstatSync(dirfd);
    if (!info.isDirectory() || info.uid !== process.getuid() || ![0o700, 0o775].includes(info.mode & 0o777)) throw Error('Startup directory unavailable');
    if ((info.mode & 0o777) === 0o775) fs.fchmodSync(dirfd, 0o700);
  } finally { fs.closeSync(dirfd); }
  return {
    read() {
      let fd;
      try { fd = fs.openSync(path.join(directory, 'startup.json'), fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW); }
      catch (error) { if (error.code === 'ENOENT') return null; throw error; }
      try {
        const s = fs.fstatSync(fd);
        if (!s.isFile() || s.uid !== process.getuid() || s.nlink !== 1 || ![0o600, 0o775].includes(s.mode & 0o777) || s.size > 4096) throw Error('Startup state unavailable');
        if ((s.mode & 0o777) === 0o775) fs.fchmodSync(fd, 0o600);
        const value = JSON.parse(fs.readFileSync(fd, 'utf8'));
        if (value.schema !== 1 || !HEX.test(value.token) || typeof value.enabled !== 'boolean' || !['prepared', 'ready', 'completing', 'attention'].includes(value.phase)) throw Error('Startup state invalid');
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
    let request, ended = false;
    const timer = timers.setTimeout(() => finish({returnValue: false, errorCode: -9003}), 6000);
    function finish(value) {
      if (ended) return; ended = true; timers.clearTimeout(timer);
      resolve({value, request});
    }
    try {
      request = (subscribe ? handle.subscribe : handle.call).call(handle,
        'luna://com.webos.service.activitymanager/' + method, JSON.stringify(params));
      request.addListener('response', message => setImmediate(() => {
        if (ended) return;
        try {
          const raw = message.payload(); if (typeof raw !== 'string' || Buffer.byteLength(raw) > 8192) throw Error();
          const value = JSON.parse(raw);
          if (!value || typeof value.returnValue !== 'boolean') throw Error();
          if (subscribe && value.returnValue && value.adopted !== true) return;
          finish(value);
        } catch (_) { finish({returnValue: false, errorCode: -9002}); }
      }));
    } catch (_) { finish({returnValue: false, errorCode: -9001}); }
  });
}
function createStartup({store, activity, boot = () => fs.readFileSync('/proc/sys/kernel/random/boot_id', 'utf8').trim(), now = Date.now, token = () => crypto.randomBytes(24).toString('hex')}) {
  let sample = null, repeated = 0;
  const load = () => store.read();
  function summary() {
    const s = load();
    return {enabled: !!(s && s.enabled), registered: !!(s && s.phase === 'ready'), phase: s ? s.phase : 'not-registered', lastOutcome: s ? s.lastOutcome || null : null};
  }
  function prepare() {
    let s = load();
    if (s) {
      // A new explicit Start may retry a rejected create. The native creator
      // always uses the same unique name with replace:false, so an uncertain
      // prior create cannot be overwritten or create a second Activity.
      if (s.phase === 'prepared') return {returnValue: true, status: 'create-required', token: s.token, activityName: NAME};
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
  async function tick(message, params) {
    let s = load();
    if (!s || !['prepared', 'ready'].includes(s.phase) || message.senderServiceName() !== 'com.webos.service.activitymanager' || message.applicationID() !== APP
        || Object.keys(params).sort().join(',') !== '$activity,token' || params.token !== s.token
        || !params.$activity || !Number.isSafeInteger(params.$activity.activityId) || params.$activity.activityId < 1
        || (s.activityId !== null && params.$activity.activityId !== s.activityId)) return {returnValue: false, status: 'callback-rejected'};
    // A genuine callback can finish binding a create whose acknowledgement was lost.
    s.activityId = params.$activity.activityId;
    const next = token(); s.phase = 'completing'; s.nextToken = next; store.write(s);
    let lease;
    try {
      const adopted = await activity('adopt', {activityId: s.activityId, subscribe: true, wait: false}, true);
      lease = adopted.request;
      if (!adopted.value || adopted.value.returnValue !== true || adopted.value.adopted !== true) throw Error('Adoption unconfirmed');
      const schedule = {start: new Date(now() + 60000).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, 'Z')};
      const complete = await activity('complete', {activityId: s.activityId, restart: true, schedule,
        callback: {method: 'luna://' + APP + '.service/startupTick', params: {token: next}}});
      if (!complete.value || complete.value.returnValue !== true) throw Error('Completion unconfirmed');
      s.token = next; delete s.nextToken; s.phase = 'ready'; store.write(s);
      return {returnValue: true, status: 'scheduled'};
    } catch (_) {
      s.phase = 'attention'; store.write(s);
      return {returnValue: false, status: 'registration-needs-attention'};
    } finally { if (lease) { try { lease.cancel(); } catch (_) {} } }
  }
  async function repair() {
    const s = load();
    if (!s || s.phase !== 'ready') throw Error('Startup is not ready');
    const read = await activity('getDetails', {activityId: s.activityId, internal: false, current: false});
    const a = read.value && read.value.activity;
    if (!read.value || read.value.returnValue !== true || !a) return {returnValue: false, status: 'startup-query-' + (read.value ? String(read.value.errorCode || 'invalid-response') : 'no-response'), errorText: read.value && typeof read.value.errorText === 'string' ? read.value.errorText.slice(0, 160) : undefined};
    const checks = {id: a.activityId === s.activityId, name: a.name === NAME,
      creator: !!a.creator && a.creator.serviceId === APP,
      method: !!a.callback && a.callback.method === 'luna://' + APP + '.service/startupTick',
      token: !!a.callback && !!a.callback.params && a.callback.params.token === s.token};
    const mismatch = Object.keys(checks).filter(k => !checks[k]);
    if (mismatch.length) return {returnValue: false, status: 'startup-mismatch-' + mismatch.join('-')};
    if (a.state !== 'expired') return {returnValue: true, status: 'registered'};
    if (!Array.isArray(a.adopters) || a.adopters.length || !Array.isArray(a.subscribers) || a.subscribers.length) throw Error('Startup activity is in use');
    return tick({senderServiceName: () => 'com.webos.service.activitymanager', applicationID: () => APP},
      {token: s.token, $activity: {activityId: s.activityId}});
  }
  async function poll({power, status, start, stop}) {
    let s = load(); if (!s || !s.enabled || s.phase !== 'ready') return;
    const p = await power();
    if (!p || (p.processing !== undefined && p.processing !== '')) { sample = null; repeated = 0; return; }
    // Screen Off keeps playback/input alive, so the microphone can restore it.
    const kind = p.state === 'Active' ? 'active' : ['Active Standby', 'Suspend'].includes(p.state) ? 'standby' : null;
    if (!kind) { sample = null; repeated = 0; return; }
    if (sample === kind) repeated++; else { sample = kind; repeated = 1; }
    if (repeated < 2) return;
    const bootId = boot();
    if (typeof bootId !== 'string' || !/^[a-f0-9-]{36}$/.test(bootId)) throw Error('Boot identity unavailable');
    let changed = false;
    if (!s.power || s.power.boot !== bootId) { s.power = {boot: bootId, state: kind, cycle: 0}; changed = true; }
    else if (s.power.state !== kind) { if (kind === 'active') s.power.cycle++; s.power.state = kind; changed = true; }
    if (changed) store.write(s);
    const found = await status();
    if (!found || found.returnValue !== true || !found.processes) return;
    if (kind === 'standby') {
      if (found.processes.controller.length && s.stopCycle !== key(s, bootId)) {
        s.stopCycle = key(s, bootId); store.write(s); await stop();
      }
      return;
    }
    if (found.processes.controller.length || found.processes.receiver.length || found.processes.ui.length || found.processes.legacy.length) return;
    const attempt = key(s, bootId);
    if (s.attempt === attempt) return;
    s.attempt = attempt; s.lastOutcome = 'starting'; store.write(s);
    const result = await start();
    s.lastOutcome = result && result.returnValue === true ? result.status : 'start-needs-attention'; store.write(s);
  }
  return {summary, prepare, bind, disable, manualStart, tick, repair, poll};
}
module.exports = {APP, NAME, disk, activityCall, createStartup};
