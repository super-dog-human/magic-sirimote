'use strict';
const assert=require('assert'),fs=require('fs'),path=require('path'),os=require('os');
const service=require('../../src/scheduler/service'),expiry=require('../../src/scheduler/expiry'),request=require('../../src/scheduler/expiry-request');
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'expiry-service-'));let listener,queries=0,extensions=0;
class Handle{constructor(){}registerMethod(){}addListener(_,f){listener=f;}unregister(){}}
const runtime=service.createService({Handle,root:path.join(tmp,'service'),processExit:()=>{},expiryRun:opts=>expiry.run({...opts,query:async()=>{queries++;return {remainingSeconds:3600};},launch:async()=>{extensions++;return 'acknowledged';}})});
const call=(sender,payload='{}',subscription=false)=>new Promise(resolve=>listener({senderServiceName:()=>sender,category:()=> '/',method:()=> 'expiryCheck',isSubscription:()=>subscription,payload:()=>payload,respond:raw=>resolve(JSON.parse(raw))}));
(async()=>{try{
 assert.equal((await call('other.app')).status,'rejected');assert.equal(queries,0);
 assert.equal((await call(service.APP,'{"extend":true}')).status,'rejected');assert.equal(queries,0);
 assert.equal((await call(service.APP,'{}',true)).status,'rejected');assert.equal(queries,0);
 const r=await call(service.APP);assert.equal(r.returnValue,true);assert.equal(r.status,'due-read-only');assert.equal(r.remainingSeconds,3600);assert.equal(queries,1);assert.equal(extensions,0);
 const state=path.join(tmp,'app');fs.mkdirSync(state,{mode:0o770});
 fs.writeFileSync(path.join(state,'expiry-request.json'),JSON.stringify({schema:1,appId:service.APP,action:'check-only',nonce:'a'.repeat(32),expiresEpochMs:1}),{mode:0o640});
 await assert.rejects(()=>request.run({state,Handle,requestUid:process.getuid(),group:process.getgid()}));assert.equal(queries,1);
 console.log('PASS service identity/payload/subscription rejection; native check is read-only even when due; expired request inert');
 }finally{runtime.close();fs.rmSync(tmp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
