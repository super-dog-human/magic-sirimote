'use strict';
const assert=require('assert'),fs=require('fs'),path=require('path'),os=require('os');
const checker=require('./native-checker'),wake=require('./wake-checker'),standby=require('./standby-resume');
const evidence={eligible:true,run:'a'.repeat(32),fingerprint:'b'.repeat(64)};
(async()=>{
 let requests=0,closed=0,verify=0;class H{constructor(id){assert.equal(id,'org.codex.siriremote.v20scheduler20261031a');}unregister(){closed++;}}
 const opts={Handle:H,state:'/unused',verify:()=>{verify++;},evidence:async()=>evidence,request:async(h,q)=>{requests++;assert.deepEqual(q,evidence);return {status:'launch-accepted'};},write:(_,r)=>r};
 assert.equal((await checker.run(opts)).status,'launch-accepted');assert.equal(requests,1);assert.equal(closed,1);assert.equal(verify,1);
 assert.equal((await checker.run({...opts,evidence:async()=>({eligible:false,reason:'manual-stop-retained'})})).reason,'manual-stop-retained');assert.equal(requests,1);
 await checker.run({...opts,verify:()=>{throw Error('pins');}});assert.equal(requests,1);
 let n=0;await checker.run({...opts,evidence:async()=>({...evidence,fingerprint:++n===1?'b'.repeat(64):'c'.repeat(64)})});assert.equal(requests,1);
 let wakes=0;const launch=async id=>{assert.equal(id,'org.codex.siriremote.v20scheduler20261031a');wakes++;return 'accepted';};
 assert.equal((await wake.run({power:async()=>({state:'Screen Off'}),launch})).reason,'power-not-active');assert.equal(wakes,0);
 await wake.run({power:async()=>({state:'Active',processing:'Request Suspend'}),launch});assert.equal(wakes,0);
 assert.equal((await wake.run({power:async()=>({state:'Active'}),launch})).reason,'native-check-requested');assert.equal(wakes,1);
 // Actual service sender gate; no runtime or Activity operation is dispatched.
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'native-resume-gate-'));fs.chmodSync(temp,0o700);let listener;class Bus{registerMethod(){}addListener(_,fn){listener=fn;}unregister(){}}
 const original=standby.run;let launches=0;standby.run=async()=>{launches++;return {status:'launch-accepted'};};
 const service=require('./service').createService({Handle:Bus,root:temp,processExit:()=>{}});
 const send=(sender,body)=>new Promise(resolve=>listener({method:()=> 'resumeVerified',category:()=> '/',senderServiceName:()=>sender,isSubscription:()=>false,payload:()=>JSON.stringify(body),respond:s=>resolve(JSON.parse(s))}));
 assert.equal((await send('untrusted.app',evidence)).returnValue,false);assert.equal(launches,0);
 assert.equal((await send('org.codex.siriremote.v20scheduler20261031a',{...evidence,extra:true})).returnValue,false);assert.equal(launches,0);
 assert.equal((await send('org.codex.siriremote.v20scheduler20261031a',evidence)).returnValue,true);assert.equal(launches,1);
 service.close();standby.run=original;fs.rmSync(temp,{recursive:true,force:true});
 console.log('PASS native restart: exact native identity, authenticated service gate, active-power gate, manual-stop exclusion, changed evidence exclusion, pin verification, handle cleanup');
})().catch(e=>{console.error(e);process.exitCode=1;});
