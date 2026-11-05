'use strict';
const assert = require('assert');
const EventEmitter = require('events');
const cp = require('child_process');
const {createService} = require('../src/integrated/service');

async function main() {
  const scheduled = []; let polls = 0, finishPoll;
  let timer, exited = false, helpers = 0, disabled = 0, enabled = false;
  class Handle extends EventEmitter {
    registerMethod() {}
    unregister() { this.unregistered = true; }
  }
  const original = cp.execFile;
  cp.execFile = (_command, _args, _options, callback) => {
    helpers++;
    return {stdin: {on() {}, end() { setImmediate(() => callback(null, '{"returnValue":true}')); }}};
  };
  const {handle} = createService({Handle, startupStore: {}, startupFactory: () => ({summary: () => ({enabled, registered: false}), poll: () => { polls++; return new Promise(resolve => { finishPoll = resolve; }); }, disable: () => { disabled++; }}), timers: {
    setTimeout(callback, delay) { if (delay === 60000) timer = callback; else scheduled.push({callback, delay}); return delay; }, clearTimeout() {}
  }, processExit() { exited = true; }});
  function request(method, sender) {
    return new Promise(resolve => {
      handle.emit('request', {method: () => method, payload: () => '{}', category: () => '/',
        isSubscription: () => false, senderServiceName: () => sender,
        respond: raw => resolve(JSON.parse(raw))});
    });
  }
  try {
    const flush = () => new Promise(resolve => setImmediate(resolve));
    assert.equal(scheduled[0].delay, 0, 'First power observation is immediate');
    scheduled.shift().callback(); await flush();
    assert.equal(polls, 1);
    assert.equal(scheduled.length, 0, 'Do not overlap a pending power observation');
    finishPoll({pollAfterMs: 150}); await flush();
    assert.equal(scheduled[0].delay, 150, 'Confirm a transition promptly');
    scheduled.shift().callback(); await flush();
    assert.equal(polls, 2);
    finishPoll(); await flush();
    assert.equal(scheduled[0].delay, 2000, 'Keep the ordinary interval after confirmation');
    assert.equal((await request('status', '')).returnValue, true);
    assert.equal((await request('status', '')).returnValue, true);
    assert.equal(helpers, 2);
    assert.equal((await request('start', 'another.app')).returnValue, false);
    assert.equal(helpers, 2, 'Unauthorized start must not invoke Python');
    assert.equal((await request('resume', 'another.app')).returnValue, false);
    assert.equal((await request('reset', 'another.app')).returnValue, false);
    assert.equal(helpers, 2, 'Unauthorized reset must not invoke Python');
    enabled = true;
    assert.equal((await request('reset', 'org.magicsirimote.app')).returnValue, false);
    assert.equal(helpers, 2, 'Reset must not run while automatic startup is enabled');
    enabled = false;
    await request('drain', 'org.magicsirimote.app');
    assert.equal(disabled, 0, 'Lifecycle drain must preserve automatic startup');
    await request('stop', 'org.magicsirimote.app');
    assert.equal(disabled, 1, 'Installer stop must suspend automatic startup');
    timer();
    assert.equal(handle.unregistered, true);
    assert.equal(exited, true, 'Unregister alone leaves an unresponsive service process');
    assert.equal(global.unified_service, false);
  } finally { cp.execFile = original; global.unified_service = false; }
  console.log('Integrated service lifecycle and sender checks passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
