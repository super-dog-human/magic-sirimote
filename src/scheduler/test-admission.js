'use strict';
const assert=require('assert'),{createAdmission}=require('./callback-admission');
const prepared={creator:'app',callbackService:'app.service',activityName:'app.persistent',run:'a'.repeat(32),nonce:'b'.repeat(48),token:'c'.repeat(48)};
const q={activityId:165,activityName:prepared.activityName,run:prepared.run,nonce:prepared.nonce,token:prepared.token};
function message(overrides={}){return {senderServiceName:()=> 'com.webos.service.activitymanager',applicationID:()=>prepared.creator,category:()=> '/',method:()=> 'tick',isSubscription:()=>false,payload:()=>JSON.stringify({$activity:{activityId:165},run:prepared.run,nonce:prepared.nonce,token:prepared.token}),...overrides};}
function setup(){const writes=new Set(),forwarded=[],timer=[];const journal={write(n){assert(!writes.has(n));writes.add(n);}};const a=createAdmission({prepared,journal,timers:{setTimeout(fn){timer.push(fn);return timer.length;},clearTimeout(){}},makeBridge:expected=>({async handle(m){assert.equal(expected.activityId,165);forwarded.push(m);return {status:'existing-bridge-result'};}})});return {a,writes,forwarded,timer,journal};}
(async()=>{
 let s=setup();const early=s.a.handle(message());assert.equal(s.forwarded.length,0);assert.equal(s.a.bind(q).status,'bound');assert.equal((await early).status,'existing-bridge-result');assert.equal(s.forwarded.length,1);
 s=setup();assert.equal(s.a.bind(q).status,'bound');assert.equal((await s.a.handle(message())).status,'existing-bridge-result');
 s=setup();const pending=s.a.handle(message());assert.equal((await s.a.handle(message())).status,'pending-duplicate-rejected');s.a.bind(q);await pending;assert.equal(s.forwarded.length,1);
 s=setup();const mismatch=s.a.handle(message());assert.equal(s.a.bind({...q,activityId:166}).status,'binding-rejected');assert.equal((await mismatch).status,'attention');assert.equal(s.forwarded.length,0);
 s=setup();assert.equal((await s.a.handle(message({applicationID:()=> 'attacker'}))).status,'rejected');assert.equal(s.writes.size,1);
 s=setup();const timeout=s.a.handle(message());s.timer[0]();assert.equal((await timeout).status,'attention');assert.equal(s.a.bind(q).status,'attention');
 s=setup();const stop=s.a.handle(message());s.a.stop();assert.equal((await stop).status,'attention');assert.equal(s.forwarded.length,0);
 s=setup();assert.throws(()=>createAdmission({prepared,journal:s.journal,makeBridge:()=>null}));
 console.log('8 admission scenarios passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
