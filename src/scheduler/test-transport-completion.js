'use strict';
const assert=require('assert'),{EventEmitter}=require('events'),fs=require('fs'),os=require('os'),path=require('path');
const {createTransport}=require('./transport'),{createHandler}=require('./callback'),{initialize}=require('./rotation-store');
(async()=>{
 for(const mode of ['ok','cancel-false','cancel-throws','completion-denied','timeout']){
  let sends=0;const stages=[];
  const h={subscribe(){const r=new EventEmitter();r.cancel=()=>{if(mode==='cancel-throws')throw Error('gone');return mode!=='cancel-false';};queueMicrotask(()=>r.emit('response',{payload:()=>JSON.stringify({returnValue:true,adopted:true})}));return r;},call(){sends++;const r=new EventEmitter();r.cancel=()=>true;if(mode!=='timeout')queueMicrotask(()=>r.emit('response',{payload:()=>JSON.stringify({returnValue:mode!=='completion-denied'})}));return r;}};
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'siri-transport-'));fs.chmodSync(temp,0o700);
  const expected={activityId:42,creator:'test.app',callbackService:'test.service',run:'a'.repeat(32),nonce:'b'.repeat(48)};
  initialize(temp,{...expected,token:'c'.repeat(48)});
  const t=createTransport(h,JSON.parse,globalThis,20,x=>stages.push(x));
  const cb=createHandler(expected,{parse:JSON.parse,...t},temp);
  const r=await cb.handle({senderServiceName:()=> 'com.webos.service.activitymanager',applicationID:()=> 'test.app',category:()=> '/',method:()=> 'tick',isSubscription:()=>false,payload:()=>JSON.stringify({$activity:{activityId:42},run:expected.run,nonce:expected.nonce,token:'c'.repeat(48)})});
  const state=JSON.parse(fs.readFileSync(path.join(temp,'rotation-state.json')));
  if(['ok','cancel-false','cancel-throws'].includes(mode)){
   assert.equal(r.status,'complete-acknowledged');assert.equal(state.phase,'ready');assert.notEqual(state.token,'c'.repeat(48));assert(!fs.existsSync(path.join(temp,'rotation.lock')));assert.equal(t.snapshot().uncertain,false);assert.equal(t.snapshot().cleanupUnconfirmed,mode!=='ok');
  }else{assert.equal(r.status,'rotation-unknown');assert.equal(state.phase,'pending');assert(fs.existsSync(path.join(temp,'rotation.lock')));}
  assert.equal(sends,1);fs.rmSync(temp,{recursive:true,force:true});
 }
 console.log('PASS: acknowledged completion survives already-closed/throwing subscription cleanup; denied and timed-out completion retain pending state; no duplicate dispatch');
})().catch(e=>{console.error(e);process.exitCode=1;});
