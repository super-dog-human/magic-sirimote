'use strict';
const fs=require('fs'),os=require('os'),path=require('path'),assert=require('assert');
const {createBootClaimStore,APP_ID}=require('./boot-claim-store');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'siri-epoch-store-')),durable=path.join(root,'state'),volatile=path.join(root,'shm');fs.mkdirSync(durable,0o700);fs.mkdirSync(volatile,0o700);
let sample={bootId:'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',btime:1000,uptimeMs:20000};
const store=()=>createBootClaimStore(durable,()=>sample,{volatileRoot:volatile});
try{
 assert.throws(()=>store().claim(APP_ID),/ENOENT/);
 assert.equal(store().initialize(),true);
 const one=store();assert.equal(one.claim(APP_ID),true);
 sample={...sample,btime:63000000,uptimeMs:40000};assert.equal(one.finish('accepted'),true);
 assert.equal(store().claim(APP_ID),false); // corrected wall clock, same volatile marker
 assert.equal(store().claim(APP_ID),false); // service reconstruction
 assert.throws(()=>store().claim('other'),/launch-target/);
 const state=JSON.parse(fs.readFileSync(path.join(durable,'epoch-state.json')));
 fs.rmSync(path.join(volatile,'codex-siri-epoch-'+state.marker.token),{recursive:true});
 sample={...sample,btime:63001000,uptimeMs:50000};assert.throws(()=>store().claim(APP_ID),/ambiguous/); // deleted marker alone is not reboot
 sample={...sample,uptimeMs:1000};const reboot=store();assert.equal(reboot.claim(APP_ID),true);assert.equal(reboot.finish('accepted'),true);
 assert.equal(store().claim(APP_ID),false);
 const active=JSON.parse(fs.readFileSync(path.join(durable,'epoch-state.json')));
 sample={...sample,uptimeMs:30000};assert.equal(store().claim(APP_ID),false); // advance checkpoint
 sample={...sample,uptimeMs:100};assert.throws(()=>store().claim(APP_ID),/contradictory/); // marker survives, uptime reverses
 fs.mkdirSync(path.join(durable,'epoch-transition.lock'),0o700);assert.throws(()=>store().claim(APP_ID),/EEXIST/);
 fs.rmdirSync(path.join(durable,'epoch-transition.lock'));
 fs.writeFileSync(path.join(durable,'epoch-next-interrupted.json'),'partial',{mode:0o600});
 assert.throws(()=>store().claim(APP_ID),/uncertain-state-transition/);
 assert.throws(()=>store().initialize(),/uncertain-state-transition/);
 console.log('epoch store checks passed');
}finally{fs.rmSync(root,{recursive:true,force:true});}
