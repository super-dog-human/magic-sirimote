'use strict';
const assert=require('assert'),fs=require('fs'),path=require('path'),os=require('os');
const resume=require('../../src/scheduler/standby-resume');
const evidence={eligible:true,run:'a'.repeat(32),fingerprint:'b'.repeat(64)};
(async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'resume-test-'));fs.chmodSync(root,0o700);
 try{
  let launches=0,powers=0,verifies=0;
  const options={root,evidence:async()=>({...evidence}),power:async()=>{powers++;return {state:'Active'};},verify:()=>{verifies++;},launch:async app=>{assert.strictEqual(app,'org.codex.siriremote.autocoord20261029v');launches++;return 'accepted';},report:()=>{}};
  assert.strictEqual((await resume.run(options)).status,'launch-accepted');assert.strictEqual(launches,1);
  assert.strictEqual((await resume.run(options)).reason,'resume-already-attempted');assert.strictEqual(launches,1);
  for(const p of [null,{state:'Screen Off'},{state:'Active Standby'},{state:'Active',processing:'Request Active Standby'}]){
   let claimed=0;const r=await resume.run({...options,power:async()=>p,reserve:()=>{claimed++;return true;}});assert.strictEqual(r.status,'already-claimed');assert.strictEqual(claimed,0);
  }
  let queried=0;assert.strictEqual((await resume.run({...options,evidence:async()=>({eligible:false,reason:'manual-stop-retained'}),power:async()=>{queried++;return {state:'Active'};}})).reason,'manual-stop-retained');assert.strictEqual(queried,0);
  let reads=0,claimed=0;assert.strictEqual((await resume.run({...options,evidence:async()=>++reads===1?evidence:{...evidence,fingerprint:'c'.repeat(64)},reserve:()=>{claimed++;return true;}})).reason,'evidence-changed');assert.strictEqual(claimed,0);
  for(const outcome of ['unknown','rejected']){
   const e={...evidence,run:(outcome==='unknown'?'c':'d').repeat(32)};let n=0;
   const args={...options,evidence:async()=>e,launch:async()=>{n++;return outcome;}};
   assert.strictEqual((await resume.run(args)).status,'launch-uncertain');assert.strictEqual((await resume.run(args)).reason,'resume-already-attempted');assert.strictEqual(n,1);
  }
  let reserved=0;await resume.run({...options,verify:()=>{throw Error('pins changed');},reserve:()=>{reserved++;return true;}});assert.strictEqual(reserved,0);
  console.log('PASS standby resume: Active-only, pending transition denied, manual stop respected, changed evidence denied, exact target, durable single attempt including rejection/unknown, pins verified');
 }finally{fs.rmSync(root,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
