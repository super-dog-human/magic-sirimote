'use strict';
const assert = require('assert');
const {createStartup, APP} = require('../src/integrated/startup');
const BOOT1 = '11111111-1111-1111-1111-111111111111', BOOT2 = '22222222-2222-2222-2222-222222222222';
function fixture(saved = null, now = () => 100000) {
  let state = saved, bootId = BOOT1, count = 0;
  const calls = [];
  const store = {read: () => state && JSON.parse(JSON.stringify(state)), write: value => { state = JSON.parse(JSON.stringify(value)); }};
  let failComplete = false, wrongCreator = false, detailsState = 'expired', committed = false, inUse = false, activityType = {immediate: true, priority: 'highest'};
  const activity = async (method, params) => {
    calls.push([method, params]);
    if (method === 'getDetails') return {value: {returnValue: true, activity: {activityId: state.activityId, type: activityType, name: APP + '.startup', creator: {serviceId: wrongCreator ? 'other.app' : APP}, callback: {method: 'luna://' + APP + '.service/startupTick', params: {token: committed ? state.nextToken : state.token}}, state: detailsState, adopters: inUse ? [{}] : [], subscribers: []}}};
    return {value: method === 'complete' && failComplete ? null : {returnValue: true, adopted: true}, request: {cancel() {}}};
  };
  const instance = () => createStartup({store, activity, boot: () => bootId, now, token: () => (++count).toString(16).padStart(48, '0')});
  return {instance, calls, type: value => { activityType = value; }, state: () => store.read(), boot: value => { bootId = value; }, fail: () => { failComplete = true; }, wrongCreator: () => { wrongCreator = true; }, repairable: (kind = 'failed', next = false, busy = false) => { failComplete = false; detailsState = kind; committed = next; inUse = busy; }};
}
function bind(s) { const prep = s.prepare(); s.bind({token: prep.token, activityId: 17}); }
const empty = () => ({returnValue: true, processes: {controller: [], receiver: [], ui: [], legacy: []}});
async function main() {
  // A persistent Activity completion may reply after the original six-second
  // cutoff during boot. It must remain pending until the completion deadline.
  const {activityCall} = require('../src/integrated/startup');
  const {EventEmitter} = require('events');
  const pending = new Map(); let timerId = 0;
  const timers = {setTimeout(fn, ms) { const id = ++timerId; pending.set(id, {fn, ms}); return id; }, clearTimeout(id) { pending.delete(id); }};
  const reply = new EventEmitter(); let settled = false;
  const completion = activityCall({call: () => reply}, 'complete', {activityId: 17}, false, timers).then(v => { settled = true; return v; });
  assert.equal([...pending.values()][0].ms, 30000);
  for (const timer of [...pending.values()]) if (timer.ms <= 6500) timer.fn();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(settled, false, 'A delayed boot response must not be failed at six seconds');
  reply.emit('response', {payload: () => JSON.stringify({returnValue: true})});
  assert.equal((await completion).value.returnValue, true);
  assert.equal(pending.size, 0);
  const absent = activityCall({call: () => new EventEmitter()}, 'complete', {activityId: 17}, false, timers);
  [...pending.values()][0].fn();
  assert.equal((await absent).value.errorCode, -9003, 'An absent reply must still have a bounded deadline');
  const fs = require('fs'), os = require('os'), path = require('path');
  const {disk} = require('../src/integrated/startup');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sirimote-boot-'));
  try {
    const saved = {schema: 1, token: 'a'.repeat(48), enabled: true, phase: 'ready'};
    fs.chmodSync(dir, 0o775);
    fs.writeFileSync(path.join(dir, 'startup.json'), JSON.stringify(saved), {mode: 0o775});
    fs.chmodSync(path.join(dir, 'startup.json'), 0o775);
    assert.deepEqual(disk(dir).read(), saved);
    assert.equal(fs.statSync(dir).mode & 0o777, 0o700);
    assert.equal(fs.statSync(path.join(dir, 'startup.json')).mode & 0o777, 0o600);
    fs.chmodSync(path.join(dir, 'startup.json'), 0o666);
    assert.throws(() => disk(dir).read(), /unavailable/);
    fs.unlinkSync(path.join(dir, 'startup.json'));
    fs.symlinkSync('/dev/null', path.join(dir, 'startup.json'));
    assert.throws(() => disk(dir).read());
  } finally { fs.rmSync(dir, {recursive: true, force: true}); }
  const f = fixture(), s = f.instance(); bind(s);
  let power = {state: 'Active'}, found = empty(), starts = 0, stops = 0;
  const deps = {power: async () => power, status: async () => found,
    start: async () => { starts++; return {returnValue: true, status: 'starting'}; }, stop: async () => { stops++; }};
  assert.deepEqual(await s.poll(deps), {pollAfterMs: 150});
  assert.equal(starts, 0, 'Require a second power observation even on the fast path');
  await s.poll(deps); assert.equal(starts, 1);
  await s.poll(deps); assert.equal(starts, 1, 'No loop after uncertain/failed runtime start');
  const reconstructed = f.instance(); await reconstructed.poll(deps); await reconstructed.poll(deps);
  assert.equal(starts, 1, 'A service restart does not reset the durable attempt');
  found.processes.controller = [{pid: 7}];
  power = {state: 'Screen Off'}; await s.poll(deps); await s.poll(deps);
  assert.equal(stops, 0, 'Screen-only off must preserve input');
  power = {state: 'Active Standby'};
  assert.equal(await s.poll(deps), undefined, 'Standby keeps the ordinary debounce interval');
  assert.equal(stops, 0);
  await s.poll(deps); await s.poll(deps);
  assert.equal(stops, 1, 'Only one cooperative stop per standby cycle');
  found = empty(); power = {state: 'Active', processing: 'Request Suspend'};
  await s.poll(deps); await s.poll(deps); assert.equal(starts, 1);
  power = {state: 'Active'}; await s.poll(deps); await s.poll(deps); assert.equal(starts, 2);
  s.disable(); f.boot(BOOT2); await s.poll(deps); await s.poll(deps); assert.equal(starts, 2, 'Explicit Stop persists across boot');
  s.prepare(); found.processes.ui = [{pid: 9}]; await s.poll(deps); await s.poll(deps); assert.equal(starts, 2);
  found = empty(); await s.poll(deps); assert.equal(starts, 3, 'New boot gets its own automatic attempt');
  s.resume(); found.processes.ui = [{pid: 9}];
  await s.poll(deps); assert.equal(starts, 3, 'Resume waits for the settings window to exit');
  found = empty(); await s.poll(deps); assert.equal(starts, 4);
  await s.poll(deps); assert.equal(starts, 4, 'Resume allows only one replacement');
  s.resume(); power = {state: 'Active Standby'};
  await s.poll(deps); await s.poll(deps); assert.equal(starts, 4, 'Settings resume never powers on input in standby');
  s.disable(); assert.equal(s.resume().status, 'unchanged');
  power = {state: 'Active'}; await s.poll(deps); await s.poll(deps);
  assert.equal(starts, 4, 'Closing a window cannot cancel installer maintenance');
  {
    const f = fixture(), s = f.instance(); bind(s);
    let starts = 0, recoveries = 0, retired = false, power = {state:'Active'};
    const deps = {power:async()=>power, status:async()=>empty(),
      start:async()=>{starts++;return {returnValue:true,status:'starting'};}, stop:async()=>{},
      recoverUnstarted:async()=>{recoveries++;return retired;}};
    await s.poll(deps);await s.poll(deps);
    await s.poll(deps);assert.equal(starts,1,'An unknown exit still cannot reset the attempt');
    retired=true;await s.poll(deps);
    assert.equal(starts,1,'Retirement alone cannot authorize input');
    await s.poll(deps);assert.equal(starts,1,'Fresh Active confirmation is required');
    await s.poll(deps);assert.equal(starts,2);
    s.disable();const before=recoveries;await s.poll(deps);
    assert.equal(recoveries,before,'Maintenance prevents automatic retirement');
    s.prepare();power={state:'Active Standby'};
    await s.poll(deps);await s.poll(deps);
    assert.equal(starts,2,'Retirement cannot wake a standby TV');
  }
  const g = fixture(), t = g.instance(); bind(t);
  const message = {senderServiceName: () => 'com.webos.service.activitymanager', applicationID: () => APP};
  const payload = {token: g.state().token, $activity: {activityId: 17}};
  assert.equal((await t.tick({...message, applicationID: () => 'other'}, payload)).returnValue, false);
  assert.equal((await t.tick({...message, senderServiceName: () => APP}, payload)).returnValue, false);
  assert.equal(g.calls.length, 0);
  assert.equal((await t.tick(message, payload)).returnValue, true);
  assert.equal(g.calls[0][0], 'adopt'); assert.equal(g.calls[1][0], 'complete');
  assert.equal(g.calls[1][1].restart, true);
  assert.equal((await t.tick(message, payload)).returnValue, false, 'Callback token cannot be replayed');
  g.fail(); const current = {token: g.state().token, $activity: {activityId: 17}};
  assert.equal((await t.tick(message, current)).returnValue, false);
  assert.equal(g.state().phase, 'attention');
  assert.equal(t.summary().lastFailure.stage, 'complete');
  assert.equal(t.summary().lastFailure.errorCode, null);
  assert.equal(t.summary().lastFailure.epochMs, 100000);
  assert.equal(JSON.stringify(t.summary()).includes(g.state().token), false);
  assert.equal(t.prepare().status, 'repair-required');
  const n = g.calls.length; await t.tick(message, current); assert.equal(g.calls.length, n, 'Never repeat uncertain completion');
  const repairFixture = fixture(), repaired = repairFixture.instance(); bind(repaired);
  assert.equal((await repaired.repair()).returnValue, true);
  assert.deepEqual(repairFixture.calls.map(x => x[0]), ['getDetails', 'adopt', 'complete']);
  const other = fixture(), refused = other.instance(); bind(refused); other.wrongCreator();
  assert.equal((await refused.repair()).returnValue, false);
  assert.deepEqual(other.calls.map(x => x[0]), ['getDetails'], 'Never adopt a different creator');
  for (const mode of ['failed', 'committed', 'uncertain', 'in-use']) {
    const f = fixture(), r = f.instance(); bind(r); f.fail();
    const m = {senderServiceName: () => 'com.webos.service.activitymanager', applicationID: () => APP};
    await r.tick(m, {token: f.state().token, $activity: {activityId: 17}});
    assert.equal(f.state().phase, 'attention');
    const next = f.state().nextToken;
    f.repairable(mode === 'committed' || mode === 'uncertain' ? 'waiting' : 'failed', mode === 'committed', mode === 'in-use');
    const before = f.calls.length;
    if (mode === 'uncertain' || mode === 'in-use') {
      await assert.rejects(r.repair());
      assert.equal(f.state().phase, 'attention');
      assert.equal(f.calls.length, before + 1, 'Uncertain/in-use activity is read only');
    } else {
      const repaired = await r.repair();
      assert.equal(repaired.returnValue, true);
      assert.deepEqual(f.calls.slice(before).map(x => x[0]), ['getDetails']);
      if (mode === 'committed') {
        assert.equal(f.state().phase, 'ready'); assert.equal(f.state().token, next);
      } else {
        assert.equal(repaired.status, 'cancel-required');
        assert.equal(f.state().phase, 'cancel-pending');
        assert.throws(() => r.cancelled({activityId: 99, resetToken: repaired.resetToken}));
        assert.throws(() => r.cancelled({activityId: 17, resetToken: 'wrong'}));
        assert.throws(() => r.prepare(), /needs attention/);
        r.cancelled({activityId: 17, resetToken: repaired.resetToken});
        assert.throws(() => r.cancelled({activityId: 17, resetToken: repaired.resetToken}));
        const fresh = r.prepare(); assert.equal(fresh.status, 'create-required');
        r.bind({token: fresh.token, activityId: 18});
        assert.equal(f.state().phase, 'ready'); assert.equal(f.state().previousActivityId, 17);
      }
    }
  }
  for (const mode of ['idle', 'running', 'in-use', 'highest', 'wrong-creator']) {
    const f = fixture(), upgrade = f.instance(); bind(upgrade);
    f.type(mode === 'highest' ? {immediate: true, priority: 'highest'} : {foreground: true});
    f.repairable(mode === 'running' ? 'running' : 'unsatisfied', false, mode === 'in-use');
    if (mode === 'wrong-creator') f.wrongCreator();
    if (mode === 'in-use') {
      await assert.rejects(upgrade.repair(), /in use/);
      assert.equal(f.state().phase, 'ready');
    } else {
      const result = await upgrade.repair();
      assert.equal(result.status, mode === 'idle' ? 'cancel-required' : mode === 'wrong-creator' ? 'startup-mismatch-creator' : 'registered');
      assert.equal(f.state().phase, mode === 'idle' ? 'cancel-pending' : 'ready');
      if (mode === 'idle') {
        upgrade.cancelled({activityId: 17, resetToken: result.resetToken});
        const next = upgrade.prepare(); assert.equal(next.status, 'create-required');
        upgrade.bind({token: next.token, activityId: 18});
      }
    }
    assert.deepEqual(f.calls.map(x => x[0]), ['getDetails'], 'Priority replacement requires native creator acknowledgement');
  }
  const h = fixture(), early = h.instance(); const p = early.prepare();
  assert.equal((await early.tick(message, {token: p.token, $activity: {activityId: 19}})).returnValue, true, 'Genuine callback recovers lost create acknowledgement');
  assert.equal(early.summary().registered, true);
  let observedClock = 1000;
  const timedFixture = fixture(null, () => observedClock), timed = timedFixture.instance(); bind(timed);
  let timedStarts = 0;
  const timedDeps = {power: async () => { observedClock += 20; return {state: 'Active'}; },
    status: async () => { observedClock += 30; return empty(); },
    start: async () => { timedStarts++; observedClock += 40; return {returnValue: true, status: 'starting'}; }, stop: async () => { throw Error('Unexpected stop'); }};
  await timed.poll(timedDeps); observedClock += 150; await timed.poll(timedDeps);
  const expectedTiming = {serviceCreatedAt: 1000, firstActiveReadStartedAt: 1000,
    firstActiveSampleAt: 1020, activeConfirmedAt: 1190, statusReadStartedAt: 1190,
    statusReadFinishedAt: 1220, startRequestedAt: 1220, startReturnedAt: 1260};
  assert.deepEqual(timed.summary().lastStartTiming, expectedTiming);
  observedClock += 2000; await timed.poll(timedDeps);
  assert.equal(timedStarts, 1);
  assert.deepEqual(timed.summary().lastStartTiming, expectedTiming, 'Later polling must preserve the measured start');
  console.log('Integrated startup: authenticated durable scheduling, stable power, manual stop and bounded resume passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
