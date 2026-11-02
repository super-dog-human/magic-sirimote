'use strict';
const assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path');
const rearm=require('./rearm-request'),{main}=require('./main');
(async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'rearm-public-'));const original=rearm.run;
 try{
  fs.writeFileSync(path.join(dir,'rearm-request.json'),'{}');
  const op='a'.repeat(32);
  for(const status of ['armed-unverified-on-hardware','rearm-cancel-unconfirmed','create-unconfirmed']){
   rearm.run=async options=>{options.report({stage:'finished',status,operationId:op,activityId:245,token:'must-not-leak',nonce:'must-not-leak'});return {status};};
   assert.strictEqual((await main({state:dir})).status,status);
   const raw=fs.readFileSync(path.join(dir,'public-status.json'),'utf8'),result=JSON.parse(raw);
   assert.strictEqual(result.action,'rearm');assert.strictEqual(result.operationId,op);assert.strictEqual(result.status,status);assert.strictEqual(result.activityAbsent,false);
   assert(!raw.includes('must-not-leak'));assert.strictEqual(fs.statSync(path.join(dir,'public-status.json')).mode&0o777,0o640);
  }
  assert.throws(()=>require('./public-status').publish(dir,{action:'unexpected',operationId:op,stage:'finished',status:'created'}));
  console.log('PASS: main exposes scoped rearm outcomes; secret fields excluded; publication mode 0640; invalid action rejected');
 }finally{rearm.run=original;fs.rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
