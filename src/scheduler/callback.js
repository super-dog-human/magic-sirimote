'use strict';
const crypto=require('crypto');
const {store,TOKEN}=require('./rotation-store');
function createHandler(expected,deps,stateDir){
 const disk=(deps.storeFactory||store)(stateDir);let attention=false;
 function auth(m){try{if(m.senderServiceName()!=='com.webos.service.activitymanager'||m.applicationID()!==expected.creator||m.category()!=='/'||m.method()!=='tick'||m.isSubscription()!==false)return null;const raw=m.payload();if(typeof raw!=='string'||Buffer.byteLength(raw)>2048)return null;const p=deps.parse(raw);return p&&Object.keys(p).sort().join(',')==='$activity,nonce,run,token'&&p.$activity&&p.$activity.activityId===expected.activityId&&p.nonce===expected.nonce&&p.run===expected.run&&TOKEN.test(p.token)?p:null;}catch(_){return null;}}
 async function handle(m){const p=auth(m);if(!p)return {status:'rejected'};if(attention)return {status:'attention'};try{disk.lock();}catch(_){return {status:'busy-or-uncertain'};}

 try{
 const initial=disk.read('rotation-state.json');if(Object.keys(initial).sort().join(',')!=='activityId,nonce,phase,run,schema,token'||initial.schema!==2||initial.phase!=='ready'||!TOKEN.test(initial.token)||initial.activityId!==expected.activityId||initial.nonce!==expected.nonce||initial.run!==expected.run)throw Error('binding-mismatch-or-pending');
 const current=initial.token;
 if(p.token!==current){disk.unlock();return {status:'rejected-replay'};}
 const next=(deps.token||(()=>crypto.randomBytes(24).toString('hex')))();if(!TOKEN.test(next)||next===current)throw Error('token-invalid');
 const now=(deps.now||Date.now)();if(!Number.isSafeInteger(now)||now<0)throw Error('clock-invalid');
 const schedule={start:new Date(now+60000).toISOString().replace('T',' ').replace(/\.\d{3}Z$/,'Z')};
 disk.replace({...initial,phase:'pending',next,schedule});
 const a=await deps.adopt(expected.activityId);if(!a||a.returnValue!==true||a.adopted!==true)throw Error('adoption-unconfirmed');
 const c=await deps.complete({activityId:expected.activityId,restart:true,callback:{method:'luna://'+expected.callbackService+'/tick',params:{run:expected.run,nonce:expected.nonce,token:next}},schedule});
 if(!c||c.returnValue!==true||('activityId'in c&&c.activityId!==expected.activityId)||('callbackToken'in c&&c.callbackToken!==next))throw Error('completion-unconfirmed');
 disk.replace({...initial,token:next});disk.unlock();return {status:'complete-acknowledged'};
 }catch(_){attention=true;return {status:'rotation-unknown'};}
 }
 return {handle,snapshot:()=>({attention})};
}
module.exports={createHandler};
