'use strict';
// Explicit, single-attempt replacement by the original Activity creator.
// No getActivityInfo permission, replace:true, disabled-record deletion, or retry.
const fs=require('fs'),path=require('path'),creator=require('./creator');
function validPrior(b){
 return b&&b.schema===1&&b.appId===creator.APP&&b.activityName===creator.NAME&&
  Number.isSafeInteger(b.activityId)&&b.activityId>0&&b.status==='created'&&
  /^[a-f0-9]{32}$/.test(b.run||'')&&/^[a-f0-9]{48}$/.test(b.nonce||'')&&/^[a-f0-9]{48}$/.test(b.token||'');
}
async function rearm({handle,stateDir,prior,intent=false,verify=creator.verifyPins,now=Date.now,timers=globalThis,random,report=()=>{}}){
 if(intent!==true)return {status:'disabled'};
 if(!validPrior(prior))throw Error('rearm-prior-invalid');
 verify();const disk=creator.journal(stateDir);
 // This directory is exclusively reserved for this operation by rearm-request.
 disk.write('rearm-intent.json',{schema:1,priorRun:prior.run,priorActivityId:prior.activityId});
 const finish=status=>{const result={schema:1,status,priorActivityId:prior.activityId,automaticRetry:false};disk.write('rearm-result.json',result);report({stage:'finished',...result});return result;};
 const disabled=await creator.call(handle,'luna://'+creator.SERVICE+'/disarm',{run:prior.run,nonce:prior.nonce,activityName:creator.NAME},timers);
 if(!disabled||disabled.returnValue!==true||disabled.status!=='disarmed')return finish('rearm-disarm-unconfirmed');
 disk.write('rearm-disarmed.json',{schema:1,priorRun:prior.run,disabled:true});
 disk.write('rearm-cancel-intent.json',{schema:1,activityName:creator.NAME,priorActivityId:prior.activityId});
 const canceled=await creator.call(handle,'luna://com.webos.service.activitymanager/cancel',{activityName:creator.NAME},timers);
 if(!canceled||canceled.returnValue!==true)return finish('rearm-cancel-unconfirmed');
 disk.write('rearm-cancel-ack.json',{schema:1,activityName:creator.NAME,cancelAcknowledged:true});
 // create(replace:false), inside provision(), is the authoritative collision
 // check. A successful new create establishes the new name/binding; cancel
 // acknowledgement alone is never described as verified absence.
 const result=await creator.provision({handle,stateDir,intent:true,verify,now,timers,random,report});
 const record={schema:1,priorActivityId:prior.activityId,...result,absenceCheckedBy:'create-replace-false'};
 disk.write('rearm-result.json',record);return record;
}
module.exports={rearm,validPrior};
