'use strict';
const assert=require('assert'),{parseStrict}=require('../../src/scheduler/strict-json'),pins=require('./fixture-pins');
const text=JSON.stringify(pins.receiver)+'\n';assert(Buffer.byteLength(text)>4096);assert(Buffer.byteLength(text)<32768);
assert.throws(()=>parseStrict(text),/invalid input/);assert.deepStrictEqual(parseStrict(text,{maxBytes:32768}),pins.receiver);
assert.throws(()=>parseStrict('{"x":1,"x":2}',{maxBytes:32768}),/duplicate/);
assert.throws(()=>parseStrict(' '.repeat(32769),{maxBytes:32768}),/invalid input/);
assert.throws(()=>parseStrict('{}',{maxBytes:32769}),/invalid input/);
console.log('representative large receiver pin accepted only at explicit bounded file limit');
