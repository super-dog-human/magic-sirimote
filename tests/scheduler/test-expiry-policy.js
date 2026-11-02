'use strict';
const assert=require('assert'),vm=require('vm'),fs=require('fs'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../../src/scheduler/expiry-policy.js'),'utf8');
(async()=>{
 for(const policy of ['disabled','check-only','extend']){
  let calls=[];const context={module:{exports:{}},require:()=>({run:async options=>{calls.push(options);return {status:'test'};}})};
  vm.runInNewContext(source.replace("'disabled'",JSON.stringify(policy)),context);
  const result=await context.module.exports.run({allowExtension:true});
  if(policy==='disabled'){assert.strictEqual(result.status,'maintenance-disabled');assert.strictEqual(calls.length,0);}
  else {assert.strictEqual(calls.length,1);assert.strictEqual(calls[0].allowExtension,policy==='extend');}
  if(policy==='extend'){await context.module.exports.run({allowExtension:false});assert.strictEqual(calls[1].allowExtension,false);}
 }
 console.log('PASS public expiry policy: disabled does not load/call maintenance; check-only never extends; explicit read-only override preserved');
})().catch(e=>{console.error(e);process.exitCode=1;});
