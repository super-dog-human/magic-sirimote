'use strict';
const assert = require('assert');
const EventEmitter = require('events');
const cp = require('child_process');
const {createService} = require('../src/integrated/service');

async function main() {
  let timer, exited = false, helpers = 0, disabled = 0;
  class Handle extends EventEmitter {
    registerMethod() {}
    unregister() { this.unregistered = true; }
  }
  const original = cp.execFile;
  cp.execFile = (_command, _args, _options, callback) => {
    helpers++;
    return {stdin: {on() {}, end() { setImmediate(() => callback(null, '{"returnValue":true}')); }}};
  };
  const {handle} = createService({Handle, startupStore: {}, startupFactory: () => ({summary: () => ({enabled: false, registered: false}), poll: async () => {}, disable: () => { disabled++; }}), timers: {
    setTimeout(callback, delay) { if (delay === 60000) timer = callback; return delay; }, clearTimeout() {}
  }, processExit() { exited = true; }});
  function request(method, sender) {
    return new Promise(resolve => {
      handle.emit('request', {method: () => method, payload: () => '{}', category: () => '/',
        isSubscription: () => false, senderServiceName: () => sender,
        respond: raw => resolve(JSON.parse(raw))});
    });
  }
  try {
    assert.equal((await request('status', '')).returnValue, true);
    assert.equal((await request('status', '')).returnValue, true);
    assert.equal(helpers, 2);
    assert.equal((await request('start', 'another.app')).returnValue, false);
    assert.equal(helpers, 2, 'Unauthorized start must not invoke Python');
    await request('drain', 'org.magicsirimote.app');
    assert.equal(disabled, 0, 'Lifecycle drain must preserve automatic startup');
    await request('stop', 'org.magicsirimote.app');
    assert.equal(disabled, 1, 'Explicit Stop must disable automatic startup');
    timer();
    assert.equal(handle.unregistered, true);
    assert.equal(exited, true, 'Unregister alone leaves an unresponsive service process');
    assert.equal(global.unified_service, false);
  } finally { cp.execFile = original; global.unified_service = false; }
  console.log('Integrated service lifecycle and sender checks passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
