'use strict';
const fs=require('fs'),os=require('os'),path=require('path'),assert=require('assert');
const {createBootClaimStore,APP_ID}=require('./boot-claim-store');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'siri-epoch-interrupted-')),state=path.join(root,'state'),shm=path.join(root,'shm');
fs.mkdirSync(state,0o700);fs.mkdirSync(shm,0o700);
let sample={bootId:'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',btime:1000,uptimeMs:20000};
const store=()=>createBootClaimStore(state,()=>sample,{volatileRoot:shm});
try{
 store().initialize();sample={...sample,uptimeMs:22000};
 const rename=fs.renameSync;
 try{fs.renameSync=()=>{throw Error('simulated-interruption');};assert.throws(()=>store().claim(APP_ID),/simulated-interruption/);}finally{fs.renameSync=rename;}
 assert(fs.readdirSync(state).some(n=>n.startsWith('epoch-next-')));
 assert.throws(()=>store().claim(APP_ID),/uncertain-state-transition/);
 assert(!fs.readdirSync(state).some(n=>n.startsWith('epoch-launch-intent-')));
 console.log('interrupted state update blocks later launches');
}finally{fs.rmSync(root,{recursive:true,force:true});}
