'use strict';
// Offline integration module. No LS2 registration, create, complete, or launch.
// journal.write MUST exclusively create/fsync private owner-checked files.
const HEX=/^[a-f0-9]{48}$/, RUN=/^[a-f0-9]{32}$/;
function createAdmission({prepared,makeBridge,journal,commitBinding=()=>{},parse=JSON.parse,timers=globalThis,waitMs=6000}){
 if(!prepared||!RUN.test(prepared.run)||!HEX.test(prepared.nonce)||!HEX.test(prepared.token)||typeof prepared.creator!=='string'||typeof prepared.callbackService!=='string'||typeof prepared.activityName!=='string'||typeof makeBridge!=='function'||!journal||typeof journal.write!=='function'||!Number.isSafeInteger(waitMs)||waitMs<1||waitMs>10000)throw Error('invalid-preparation');
 const p=Object.freeze({...prepared});let binding=null,early=null,bridge=null,attention=false,stopped=false;
 // Exclusive durable preparation means reconstruction over an old instance
 // fails closed: no callback message is synthesized from disk after restart.
 journal.write('edge-admission-prepared.json',{schema:1,run:p.run,nonce:p.nonce,activityName:p.activityName});
 function auth(m){try{
  if(m.senderServiceName()!=='com.webos.service.activitymanager'||m.applicationID()!==p.creator||m.category()!=='/'||m.method()!=='tick'||m.isSubscription()!==false)return null;
  const raw=m.payload();if(typeof raw!=='string'||Buffer.byteLength(raw)>2048)return null;
  const x=parse(raw);
  if(!x||Object.keys(x).sort().join(',')!=='$activity,nonce,run,token'||!x.$activity||!Number.isSafeInteger(x.$activity.activityId)||x.$activity.activityId<1||x.run!==p.run||x.nonce!==p.nonce||x.token!==p.token)return null;
  return x;
 }catch(_){return null;}}
 function finishEarly(value){if(!early)return;const e=early;early=null;timers.clearTimeout(e.timer);e.resolve(value);}
 function fail(){attention=true;finishEarly({status:'attention',automaticRetry:false});}
 async function forward(m){
  if(attention||stopped)return {status:'attention',automaticRetry:false};
  // The unchanged existing bridge authenticates again, rotates tokens, claims
  // the boot and decides launch. This adapter grants no receiver admission.
  return bridge.handle(m);
 }
 function bind(q){
  if(attention||stopped)return {status:'attention'};
  if(!q||Object.keys(q).sort().join(',')!=='activityId,activityName,nonce,run,token'||q.run!==p.run||q.nonce!==p.nonce||q.token!==p.token||q.activityName!==p.activityName||!Number.isSafeInteger(q.activityId)||q.activityId<1||(early&&early.id!==q.activityId)||binding){fail();return {status:'binding-rejected'};}
  try{
   journal.write('edge-admission-bound.json',{schema:1,activityId:q.activityId,run:p.run,activityName:p.activityName});
   commitBinding(q);
   binding=Object.freeze({...q});
   bridge=makeBridge({creator:p.creator,activityId:q.activityId,nonce:p.nonce,run:p.run,callbackService:p.callbackService});
   if(early){const e=early;early=null;timers.clearTimeout(e.timer);forward(e.message).then(e.resolve,()=>{attention=true;e.resolve({status:'attention',automaticRetry:false});});}
   return {status:'bound',activityId:q.activityId};
  }catch(_){fail();return {status:'attention'};}
 }
 function handle(m){
  if(attention||stopped)return Promise.resolve({status:'attention'});
  if(binding)return forward(m); // Existing rotating-token authenticator owns it.
  const x=auth(m);if(!x)return Promise.resolve({status:'rejected'});
  if(early)return Promise.resolve({status:'pending-duplicate-rejected'});
  try{journal.write('edge-admission-early.json',{schema:1,activityId:x.$activity.activityId,run:p.run});}
  catch(_){fail();return Promise.resolve({status:'attention'});}
  return new Promise(resolve=>{
   early={id:x.$activity.activityId,message:m,resolve,timer:null};
   early.timer=timers.setTimeout(()=>{try{journal.write('edge-admission-timeout.json',{schema:1,run:p.run});}catch(_){}fail();},waitMs);
  });
 }
 function stop(){stopped=true;try{journal.write('edge-admission-stopped.json',{schema:1,run:p.run});}finally{fail();}}
 return {handle,bind,stop,snapshot:()=>({bound:!!binding,early:!!early,attention,stopped})};
}
module.exports={createAdmission};
