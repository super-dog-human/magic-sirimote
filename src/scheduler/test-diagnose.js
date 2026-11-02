'use strict';
const fs=require('fs'),os=require('os'),path=require('path'),assert=require('assert'),{run,hasRequest}=require('./diagnose');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'siri-scheduler-diag-')),app='org.codex.siriremote.v20scheduler20261031a',nonce='a'.repeat(32);
try{
 fs.mkdirSync(path.join(root,'creator-private'),{mode:0o700});let now=1700000000000;
 assert.equal(hasRequest(root),false);const q={schema:1,appId:app,nonce,expiresEpochMs:now+60000};const req=path.join(root,'diagnose-request.json');fs.writeFileSync(req,JSON.stringify(q),{mode:0o640});fs.chmodSync(req,0o640);
 let n=0;const out=run({state:root,now:()=>now,verify:()=>{n++},requestUid:process.getuid(),group:process.getgid()});assert.equal(n,1);assert.equal(out.pin,'ok');assert.equal(out.privateState,'readable');assert.equal(out.hasProvisionIntent,false);assert.equal(out.activityCalls,0);
 assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root,'diagnose-result-'+nonce+'.json'))),out);
 assert.throws(()=>run({state:root,now:()=>now,verify:()=>{},requestUid:process.getuid(),group:process.getgid()}),/EEXIST/);
 fs.unlinkSync(req);fs.symlinkSync(path.join(root,'creator-private'),req);assert.throws(()=>run({state:root,now:()=>now,verify:()=>{},requestUid:process.getuid(),group:process.getgid()}),/invalid/);
 console.log('diagnosis is explicit, bounded, same-app and makes no Activity call');
}finally{fs.rmSync(root,{recursive:true,force:true});}
