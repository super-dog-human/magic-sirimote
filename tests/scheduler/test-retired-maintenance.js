'use strict';
const assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path');
const {main}=require('../../src/scheduler/main');
(async()=>{
 const state=fs.mkdtempSync(path.join(os.tmpdir(),'retired-scheduler-'));let handles=0,verifies=0;
 class Handle{constructor(){handles++;throw Error('must not open service bus');}}
 const file=path.join(state,'maintenance-request.json');
 try{
  fs.writeFileSync(file,'old request');
  await assert.rejects(()=>main({state,Handle,verify:()=>{verifies++;},automaticResume:true}),/retired-maintenance-request-retained/);
  assert.strictEqual(fs.readFileSync(file,'utf8'),'old request');assert.strictEqual(handles,0);assert.strictEqual(verifies,0);
  assert.deepStrictEqual(fs.readdirSync(state),['maintenance-request.json']);
  fs.unlinkSync(file);fs.symlinkSync(path.join(state,'missing'),file);
  await assert.rejects(()=>main({state,Handle}),/retired-maintenance-request-retained/);
  assert.strictEqual(handles,0);
 }finally{fs.rmSync(state,{recursive:true,force:true});}
 console.log('PASS retired scheduler request: retained, no bus/launch/write, symlinks also blocked');
})().catch(e=>{console.error(e);process.exitCode=1;});
