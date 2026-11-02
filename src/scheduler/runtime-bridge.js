"use strict";
const {createHandler}=require('./callback');
const {createBootClaimStore}=require('./boot-claim-store');
const APP='org.codex.siriremote.autocoord20261029v';
function createRuntimeBridge({expected,callbackDeps,stateDir,getBootIdentity,launchOverride,resume,volatileRoot='/dev/shm'}){
 const cb=createHandler(expected,callbackDeps,stateDir);
 // Shared parent root prevents separate bindings opening multiple launch windows.
 const claims=createBootClaimStore(require('path').dirname(stateDir),getBootIdentity,{volatileRoot});
 let tail=Promise.resolve();
 async function one(m){
  const r=await cb.handle(m);if(r.status!=='complete-acknowledged')return {status:'callback-not-confirmed',callback:r.status};
  try{if(!claims.claim(APP))return resume?await resume():{status:'already-claimed',healthy:false};}
  catch(_){return {status:'claim-uncertain',automaticRetry:false};}
  const outcome=await launchOverride.launch(APP);
  try{claims.finish(outcome);}catch(_){return {status:'launch-outcome-save-uncertain',automaticRetry:false};}
  return {status:outcome==='accepted'?'launch-accepted':'launch-uncertain',healthy:false,automaticRetry:false};
 }
 return {handle(m){const next=tail.then(()=>one(m));tail=next.catch(()=>{});return next;}};
}
module.exports={createRuntimeBridge};
