'use strict';
const assert = require('assert');
const {createStartup, APP} = require('../src/integrated/startup');
const flush = () => new Promise(resolve => setImmediate(resolve));
const message = {senderServiceName: () => 'com.webos.service.activitymanager', applicationID: () => APP};
const empty = () => ({returnValue: true, processes: {controller: [], receiver: [], ui: [], legacy: []}});
function fixture() {
  let state = null, clock = 1000, counter = 0, settle, reject, adoption = true, cancelled = 0;
  const calls = [], store = {read: () => state && JSON.parse(JSON.stringify(state)),
    write: value => { state = JSON.parse(JSON.stringify(value)); }};
  const options = {store, now: () => clock, boot: () => '11111111-1111-1111-1111-111111111111',
    token: () => (++counter).toString(16).padStart(48, '0'),
    activity: async method => {
      calls.push(method);
      if (method === 'adopt') return {value: {returnValue: adoption, adopted: adoption}, request: {cancel() { cancelled++; }}};
      assert.equal(method, 'complete');
      return new Promise((resolve, fail) => { settle = resolve; reject = fail; });
    }};
  const s = createStartup(options), prepared = s.prepare(); s.bind({token: prepared.token, activityId: 17});
  return {s, store, calls, reconstruct: () => createStartup(options),
    payload: () => ({token: store.read().token, $activity: {activityId: 17}}),
    advance: ms => { clock += ms; }, failAdoption: () => { adoption = false; },
    complete: (ok = true) => settle({value: {returnValue: ok}, receivedAfterMs: 4500}),
    reject: () => reject(Error('No reply')), cancelled: () => cancelled};
}
async function main() {
  for (const outcome of ['success', 'failure', 'rejection']) {
    const f = fixture(); let starts = 0, powerReads = 0, capability, done = false;
    const deps = {power: async () => { powerReads++; return {state: 'Active'}; }, status: async () => empty(),
      start: async () => { starts++; return {returnValue: true, status: 'starting'}; }, stop: async () => { throw Error('Unexpected stop'); }};
    const running = f.s.tick(message, f.payload(), async poll => {
      capability = poll;
      assert.deepEqual(await poll(deps), {pollAfterMs: 150});
      f.advance(150); await poll(deps);
    }).then(result => { done = true; return result; });
    await flush();
    assert.equal(done, false, 'Reservation completion is still pending');
    assert.equal(starts, 1, 'Input starts before the delayed reservation reply');
    assert.equal(f.store.read().phase, 'completing');
    const attempted = f.store.read().attempt, timing = f.s.summary().lastStartTiming;
    await f.s.poll(deps); await f.reconstruct().poll(deps);
    assert.equal(powerReads, 2, 'Persisted completing state never permits ordinary/reconstructed polling');
    f.advance(4500);
    if (outcome === 'rejection') f.reject(); else f.complete(outcome === 'success');
    const result = await running;
    assert.equal(result.returnValue, outcome === 'success');
    assert.equal(f.store.read().phase, outcome === 'success' ? 'ready' : 'attention');
    assert.equal(f.store.read().attempt, attempted, 'Completion must retain the input attempt');
    assert.deepEqual(f.s.summary().lastStartTiming, timing, 'Completion must retain input timing');
    await capability(deps);
    assert.equal(powerReads, 2, 'The temporary capability expires when its callback finishes');
    await f.s.poll(deps); await f.s.poll(deps);
    assert.equal(starts, 1, 'No duplicate input start after completion or failure');
    assert.equal(f.cancelled(), 1);
  }
  for (const mode of ['wrong-sender', 'adoption-failed', 'disabled', 'standby', 'busy']) {
    const f = fixture(); let checks = 0, starts = 0, stops = 0;
    if (mode === 'adoption-failed') f.failAdoption();
    if (mode === 'disabled') f.s.disable();
    const deps = {power: async () => ({state: mode === 'standby' ? 'Active Standby' : 'Active'}),
      status: async () => { const found = empty(); if (mode === 'busy' || mode === 'standby') found.processes.controller = [{pid: 5}]; return found; },
      start: async () => { starts++; }, stop: async () => { stops++; }};
    const running = f.s.tick(mode === 'wrong-sender' ? {...message, senderServiceName: () => APP} : message,
      f.payload(), async poll => { checks++; await poll(deps); f.advance(150); await poll(deps); });
    await flush();
    assert.equal(starts, 0); assert.equal(stops, 0, 'Completion must not shorten standby debounce');
    if (['wrong-sender', 'adoption-failed'].includes(mode)) {
      assert.equal(checks, 0); assert.equal(f.calls.includes('complete'), false);
    } else f.complete();
    await running;
    if (mode === 'disabled') assert.equal(f.store.read().enabled, false);
  }
  {
    const f = fixture();
    const running = f.s.tick(message, f.payload(), async () => { throw Error('Power helper failed'); });
    await flush(); f.complete();
    assert.equal((await running).returnValue, true, 'A power check error cannot abandon reservation completion');
    assert.equal(f.s.summary().lastTick.inputCheckFailed, true);
  }
  for (const success of [true, false]) {
    const f = fixture();
    const running = f.s.tick(message, f.payload(), async () => { f.s.disable(); });
    await flush(); f.complete(success); await running;
    assert.equal(f.store.read().enabled, false, 'Completion preserves the latest maintenance stop');
  }
  for (const success of [true, false]) {
    const f = fixture();
    const running = f.s.tick(message, f.payload(), async () => {});
    await flush();
    const replaced = {...f.store.read(), token: 'f'.repeat(48), phase: 'ready'};
    f.store.write(replaced); f.complete(success);
    assert.equal((await running).status, 'registration-state-changed');
    assert.deepEqual(f.store.read(), replaced, 'Neither success nor failure may overwrite a replaced registration');
  }
  console.log('Startup overlap: early input, durable single attempt, authorization, standby, failure and state preservation passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
