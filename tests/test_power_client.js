'use strict';
const assert = require('assert'), EventEmitter = require('events');
const {createPowerReader} = require('../src/integrated/power-client');
function fixture() {
  const children = [], timers = new Set();
  const reader = createPowerReader({spawn(command, args, options) {
    assert.equal(command, '/usr/bin/python3'); assert.equal(args[args.length - 1], '--serve');
    assert.deepEqual(options.stdio, ['pipe', 'pipe', 'ignore']);
    const child = new EventEmitter(); child.stdout = new EventEmitter(); child.stdin = new EventEmitter();
    child.stdout.setEncoding = () => {}; child.writes = [];
    child.stdin.write = value => child.writes.push(JSON.parse(value));
    child.stdin.end = () => {}; child.kill = () => {child.killed = true;};
    children.push(child); return child;
  }, timers: {setTimeout(callback) {timers.add(callback); return callback;}, clearTimeout(timer) {timers.delete(timer);}}});
  const reply = (child, value) => child.stdout.emit('data', JSON.stringify(value) + '\n');
  return {reader, children, timers, reply};
}
async function main() {
  {
    const f = fixture(); let result = f.reader.read(), c = f.children[0];
    assert.equal(await f.reader.read(), null, 'Do not overlap reads');
    c.stdout.emit('data', '{"id":1,"power":'); c.stdout.emit('data', '{"state":"Active"}}\n');
    assert.deepEqual(await result, {state:'Active'});
    result = f.reader.read(); f.reply(c, {id:2,power:{state:'Suspend'}});
    assert.deepEqual(await result,{state:'Suspend'}); assert.equal(f.children.length,1);
    assert.equal(f.timers.size,0); f.reader.close(); assert(c.killed); assert.equal(await f.reader.read(),null);
  }
  for (const fault of ['timeout','exit','error','end','wrong-id','invalid-json','too-large','extra-reply']) {
    const f = fixture(); const first = f.reader.read(), old = f.children[0];
    if (fault === 'timeout') [...f.timers][0]();
    else if (fault === 'exit' || fault === 'error') old.emit(fault, Error('failure'));
    else if (fault === 'end') old.stdout.emit('end');
    else if (fault === 'wrong-id') f.reply(old,{id:8,power:{state:'Active'}});
    else old.stdout.emit('data', fault === 'invalid-json' ? '!\n' : fault === 'too-large' ? 'x'.repeat(2049) : '{"id":1,"power":{"state":"Active"}}\n{}\n');
    assert.equal(await first,null,fault); assert(old.killed);
    const next = f.reader.read(); assert.equal(f.children.length,2);
    f.reply(old,{id:2,power:{state:'Active'}}); old.emit('exit');
    f.reply(f.children[1],{id:2,power:{state:'Suspend'}});
    assert.deepEqual(await next,{state:'Suspend'},'An old process cannot satisfy or cancel a new read');
    f.reader.close();
  }
  const f = fixture(); const pending = f.reader.read(); f.reader.close();
  assert.equal(await pending,null); assert.equal(f.timers.size,0);
  console.log('Power client: process reuse, fresh replies, bounded failures and stale-process isolation passed');
}
main().catch(error => {console.error(error);process.exitCode=1;});
