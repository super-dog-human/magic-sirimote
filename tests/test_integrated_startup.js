'use strict';
const assert = require('assert');
const {createStartup, APP} = require('../src/integrated/startup');
const BOOT1 = '11111111-1111-1111-1111-111111111111', BOOT2 = '22222222-2222-2222-2222-222222222222';
function fixture(saved = null) {
  let state = saved, bootId = BOOT1, count = 0;
  const calls = [];
  const store = {read: () => state && JSON.parse(JSON.stringify(state)), write: value => { state = JSON.parse(JSON.stringify(value)); }};
  let failComplete = false, wrongCreator = false;
  const activity = async (method, params) => {
    calls.push([method, params]);
    if (method === 'getDetails') return {value: {returnValue: true, activity: {activityId: state.activityId, name: APP + '.startup', creator: {serviceId: wrongCreator ? 'other.app' : APP}, callback: {method: 'luna://' + APP + '.service/startupTick', params: {token: state.token}}, state: 'expired', adopters: [], subscribers: []}}};
    return {value: method === 'complete' && failComplete ? null : {returnValue: true, adopted: true}, request: {cancel() {}}};
  };
  const instance = () => createStartup({store, activity, boot: () => bootId, now: () => 100000, token: () => (++count).toString(16).padStart(48, '0')});
  return {instance, calls, state: () => store.read(), boot: value => { bootId = value; }, fail: () => { failComplete = true; }, wrongCreator: () => { wrongCreator = true; }};
}
function bind(s) { const prep = s.prepare(); s.bind({token: prep.token, activityId: 17}); }
const empty = () => ({returnValue: true, processes: {controller: [], receiver: [], ui: [], legacy: []}});
async function main() {
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
  await s.poll(deps); assert.equal(starts, 0, 'Require stable power');
  await s.poll(deps); assert.equal(starts, 1);
  await s.poll(deps); assert.equal(starts, 1, 'No loop after uncertain/failed runtime start');
  const reconstructed = f.instance(); await reconstructed.poll(deps); await reconstructed.poll(deps);
  assert.equal(starts, 1, 'A service restart does not reset the durable attempt');
  found.processes.controller = [{pid: 7}];
  power = {state: 'Screen Off'}; await s.poll(deps); await s.poll(deps);
  assert.equal(stops, 0, 'Screen-only off must preserve input');
  power = {state: 'Active Standby'}; await s.poll(deps); await s.poll(deps); await s.poll(deps);
  assert.equal(stops, 1, 'Only one cooperative stop per standby cycle');
  found = empty(); power = {state: 'Active', processing: 'Request Suspend'};
  await s.poll(deps); await s.poll(deps); assert.equal(starts, 1);
  power = {state: 'Active'}; await s.poll(deps); await s.poll(deps); assert.equal(starts, 2);
  s.disable(); f.boot(BOOT2); await s.poll(deps); await s.poll(deps); assert.equal(starts, 2, 'Explicit Stop persists across boot');
  s.prepare(); found.processes.ui = [{pid: 9}]; await s.poll(deps); await s.poll(deps); assert.equal(starts, 2);
  found = empty(); await s.poll(deps); assert.equal(starts, 3, 'New boot gets its own automatic attempt');
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
  assert.throws(() => t.prepare(), /needs attention/);
  const n = g.calls.length; await t.tick(message, current); assert.equal(g.calls.length, n, 'Never repeat uncertain completion');
  const repairFixture = fixture(), repaired = repairFixture.instance(); bind(repaired);
  assert.equal((await repaired.repair()).returnValue, true);
  assert.deepEqual(repairFixture.calls.map(x => x[0]), ['getDetails', 'adopt', 'complete']);
  const other = fixture(), refused = other.instance(); bind(refused); other.wrongCreator();
  assert.equal((await refused.repair()).returnValue, false);
  assert.deepEqual(other.calls.map(x => x[0]), ['getDetails'], 'Never adopt a different creator');
  const h = fixture(), early = h.instance(); const p = early.prepare();
  assert.equal((await early.tick(message, {token: p.token, $activity: {activityId: 19}})).returnValue, true, 'Genuine callback recovers lost create acknowledgement');
  assert.equal(early.summary().registered, true);
  console.log('Integrated startup: authenticated durable scheduling, stable power, manual stop and bounded resume passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
