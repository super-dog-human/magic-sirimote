'use strict';
const assert = require('assert');
const {createTimingRecorder} = require('../src/integrated/service');
const event = (extra = {}) => ({stage:'runtime-startup-timing',role:'controller',pid:123,step:'connection-watch-started',epochMs:100000,elapsedMs:50,...extra});
const line = value => JSON.stringify(value) + '\n';
{
  const saved = [], record = createTimingRecorder(123, value => saved.push(value));
  const raw = line(event({secret:'never copy',token:'never copy'}));
  record(Buffer.from(raw.slice(0,13))); assert.equal(saved.length,0);
  record(Buffer.from(raw.slice(13))); assert.equal(saved.length,1);
  assert.deepStrictEqual(saved[0],{schema:1,pid:123,events:[event()]});
  record(line(event({step:'runtime-imported'})));
  assert.equal(saved[0].events.length,1); assert.equal(saved[1].events.length,2);
}
{
  const saved=[],record=createTimingRecorder(123,value=>saved.push(value));
  for (const bad of [{pid:124},{role:'receiver'},{stage:'controller-preloaded'},{epochMs:NaN},{elapsedMs:-1},{step:'arbitrary value'}]) record(line(event(bad)));
  record('not json\n'); record('null\n'); assert.equal(saved.length,0);
  record(line(event())); assert.equal(saved.length,1);
}
{
  const saved=[],record=createTimingRecorder(123,value=>saved.push(value));
  record('x'.repeat(5000)); record('still oversized'+line(event()));
  assert.equal(saved.length,0); record(line(event())); assert.equal(saved.length,1);
  record('x'.repeat(5000)+'\n'+line(event())); assert.equal(saved.length,2);
}
{
  const saved=[],record=createTimingRecorder(123,value=>saved.push(value));
  for(let i=0;i<100;i++)record(line(event({elapsedMs:i})));
  assert.equal(saved.length,32);assert.equal(saved.at(-1).events.length,32);
  assert.ok(JSON.stringify(saved.at(-1)).length<8192);
}
{
  let calls=0; const record=createTimingRecorder(123,()=>{calls++;throw Error('disk unavailable');});
  assert.doesNotThrow(()=>record(line(event())+line(event())));assert.equal(calls,2);
}
{
  let calls=0;const record=createTimingRecorder(undefined,()=>calls++);
  record(line(event()));assert.equal(calls,0);
}
console.log('Controller timing window: 6 checks passed');
