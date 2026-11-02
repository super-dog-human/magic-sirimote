'use strict';
const assert=require('assert'),fs=require('fs'),path=require('path'),os=require('os'),{EventEmitter}=require('events');
const e=require('./expiry');
async function scenario(kind){
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'expiry-test-')),root=path.join(tmp,'expiry');
 let time=Date.UTC(2026,10,2),queries=0,launches=0,gate;
 const low=10*86400,high=1000*3600;
 const query=async()=>{queries++;if(kind==='query-fails')return null;if(kind==='query-throws')throw Error('private');if(kind==='concurrent'&&queries===1)await new Promise(r=>gate=r);if(kind==='bad-time')return {remainingSeconds:high+1};return {remainingSeconds:kind==='expired'?0:kind==='ample'||kind==='concurrent'?high:kind==='uncertain'||kind==='pending-reconcile'&&queries<3||kind==='readonly'?low-Math.floor((time-Date.UTC(2026,10,2))/1000):queries===1?low:high};};
 const launch=async()=>{launches++;const state=JSON.parse(fs.readFileSync(path.join(root,'state.json')));assert(state.pending);assert.equal(state.lastAttemptMs,time);return kind==='rejected-but-renewed'?'rejected':'acknowledged';};
 const opts={root,query,launch,now:()=>time,wait:async()=>{}};
 try{
  if(kind==='symlink'){fs.symlinkSync(tmp,root);assert.equal((await e.run(opts)).status,'local-state-attention');assert.equal(queries,0);return;}
  if(kind==='concurrent'){const first=e.run(opts);await new Promise(r=>setImmediate(r));assert.equal((await e.run(opts)).status,'local-state-attention');gate();await first;assert.equal(queries,1);assert.equal(launches,0);return;}
  if(kind==='readonly')opts.allowExtension=false;
  let r=await e.run(opts);
  const expected={'ample':'time-sufficient','query-fails':'query-unconfirmed','query-throws':'query-unconfirmed','bad-time':'query-unconfirmed','expired':'expired','readonly':'due-read-only','uncertain':'extension-unconfirmed-no-retry','pending-reconcile':'extension-unconfirmed-no-retry'};
  assert.equal(r.status,expected[kind]||'renewal-verified');
  assert.equal(launches,['ample','query-fails','query-throws','bad-time','expired','readonly'].includes(kind)?0:1);
  const n=queries;assert.equal((await e.run(opts)).status,'not-due');assert.equal(queries,n);
  time-=1000;assert.equal((await e.run({...opts,forceRead:true})).status,'clock-untrusted');assert.equal(queries,n);time+=1000;
  if(kind==='uncertain'||kind==='pending-reconcile'){
   time+=e.DAY;const oldLaunch=launches;r=await e.run(opts);
   assert.equal(r.status,kind==='pending-reconcile'?'renewal-verified':'extension-unconfirmed-no-retry');assert.equal(launches,oldLaunch);
  }
  const saved=fs.readFileSync(path.join(root,'state.json'),'utf8');assert(!saved.includes('private'));assert.equal(fs.statSync(path.join(root,'state.json')).mode&0o777,0o600);
 }finally{fs.rmSync(tmp,{recursive:true,force:true});}
}
async function transport(){
 for(const kind of ['okay','wrong-app','malformed','rejected','timeout']){
  let canceled=0,calls=0;
  const handle={call(uri,payload){calls++;assert.equal(uri,'luna://com.webos.applicationManager/launch');assert.deepEqual(JSON.parse(payload),{id:'com.palmdts.devmode',params:{extend:true},subscribe:false});const req=new EventEmitter();req.cancel=()=>canceled++;
   if(kind!=='timeout')queueMicrotask(()=>req.emit('response',{payload:()=>kind==='malformed'?'private':JSON.stringify(kind==='rejected'?{returnValue:false}:{returnValue:true,id:kind==='wrong-app'?'wrong':'com.palmdts.devmode'})}));return req;}};
  const timers={setTimeout:fn=>setTimeout(fn,5),clearTimeout};
  assert.equal(await e.launchOfficial(handle,timers),kind==='okay'?'acknowledged':kind==='rejected'?'rejected':'unconfirmed');assert.equal(calls,1);assert.equal(canceled,1);
 }
}
(async()=>{for(const k of ['ample','renew','rejected-but-renewed','query-fails','query-throws','bad-time','expired','readonly','uncertain','pending-reconcile','concurrent','symlink'])await scenario(k);await transport();console.log('PASS 12 expiry state scenarios + 5 fixed official transport scenarios');})().catch(x=>{console.error(x);process.exitCode=1;});
