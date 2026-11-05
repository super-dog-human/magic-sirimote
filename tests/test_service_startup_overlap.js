'use strict';
const assert = require('assert'), cp = require('child_process'), EventEmitter = require('events');
const {createStartup, APP} = require('../src/integrated/startup');
const {createService} = require('../src/integrated/service');
const flush = () => new Promise(resolve => setImmediate(resolve));
async function main() {
  const original = cp.execFile, scheduled = [], helperCalls = [], launches = [];
  let state = {schema: 1, token: 'a'.repeat(48), enabled: true, phase: 'ready', activityId: 17}, complete, disabled = false;
  const store = {read: () => JSON.parse(JSON.stringify(state)), write: value => { state = JSON.parse(JSON.stringify(value)); }};
  class Handle extends EventEmitter { registerMethod() {} unregister() {} }
  cp.execFile = (_command, args, _options, callback) => {
    const power = args[2].endsWith('/power-read.py');
    if (!power) helperCalls.push(args[3]);
    const reply = power ? {state: 'Active'} : args[3] === 'status'
      ? {returnValue: true, processes: {controller: [], receiver: [], ui: [], legacy: []}}
      : {returnValue: true, status: 'already-running'};
    setImmediate(() => callback(null, JSON.stringify(reply)));
    return {stdin: {on() {}, end() {}}};
  };
  try {
    const {handle} = createService({Handle, controllerLauncher: async () => { launches.push('start'); return {returnValue:true,status:'starting'}; }, powerReader: {read: async () => ({state: 'Active'}), close() {}}, startupStore: store,
      processReader: () => ({controller: [], receiver: [], ui: [], legacy: []}),
      startupFactory: () => createStartup({store, boot: () => '11111111-1111-1111-1111-111111111111',
        token: () => 'b'.repeat(48), activity: async method => {
          if (method === 'adopt') return {value: {returnValue: true, adopted: true}, request: {cancel() {}}};
          assert.equal(method, 'complete'); return new Promise(resolve => { complete = resolve; });
        }}), timers: {setTimeout(callback, delay) { scheduled.push({callback, delay}); return {}; }, clearTimeout() {}}});
    const request = (method, params, sender) => new Promise(resolve => handle.emit('request', {
      method: () => method, payload: () => JSON.stringify(params), category: () => '/', isSubscription: () => false,
      senderServiceName: () => sender, applicationID: () => APP, respond: raw => resolve(JSON.parse(raw))}));
    const tick = request('startupTick', {token: state.token, $activity: {activityId: 17}}, 'com.webos.service.activitymanager');
    for (let i = 0; i < 10 && !scheduled.some(x => x.delay === 150); i++) await flush();
    assert.equal(typeof complete, 'function');
    const confirmation = scheduled.find(x => x.delay === 150);
    assert(confirmation, 'Confirm active power while the completion reply is pending');
    const stop = request('stop', {}, APP).then(result => { disabled = true; return result; });
    confirmation.callback();
    for (let i = 0; i < 10 && !launches.length; i++) await flush();
    assert.equal(launches.length, 1);
    assert.equal(disabled, false, 'External mutations remain queued behind the callback');
    assert.equal(state.enabled, true);
    complete({value: {returnValue: true}});
    assert.equal((await tick).returnValue, true);
    assert.equal((await stop).returnValue, true);
    assert.equal(state.enabled, false);
    assert.equal(state.phase, 'ready');
    assert(state.attempt, 'Reservation completion must retain the start attempt');
    assert.deepEqual(helperCalls, ['stop'], 'Automatic status and start must not spawn separate Python helpers');
    console.log('Service startup overlap: early power confirmation and input start; external mutations remain serialized');
  } finally { cp.execFile = original; global.unified_service = false; }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
