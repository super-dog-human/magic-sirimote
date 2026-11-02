'use strict';
const fs=require('fs'),os=require('os'),path=require('path'),assert=require('assert'),{spawn}=require('child_process');
const {createBootClaimStore,APP_ID}=require('../../src/scheduler/boot-claim-store');
const sample={bootId:'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',btime:1000,uptimeMs:20000};
if(process.argv[2]==='worker'){
 try{let s=createBootClaimStore(process.argv[3],()=>sample,{volatileRoot:process.argv[4]});console.log(s.claim(APP_ID)?'LAUNCHED':'EXISTING');}
 catch(e){if(e.code==='EEXIST')console.log('BUSY');else{console.error(e.stack);process.exitCode=1;}}
}else{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'siri-epoch-race-')),state=path.join(root,'state'),shm=path.join(root,'shm');fs.mkdirSync(state,0o700);fs.mkdirSync(shm,0o700);
 createBootClaimStore(state,()=>sample,{volatileRoot:shm}).initialize();
 Promise.all(Array.from({length:16},()=>new Promise((resolve,reject)=>{const p=spawn(process.execPath,[__filename,'worker',state,shm]);let out='',err='';p.stdout.on('data',x=>out+=x);p.stderr.on('data',x=>err+=x);p.on('error',reject);p.on('close',code=>code?reject(Error(err)):resolve(out.trim()));}))).then(out=>{assert.equal(out.filter(x=>x==='LAUNCHED').length,1);assert(out.every(x=>['LAUNCHED','EXISTING','BUSY'].includes(x)));assert.equal(fs.readdirSync(state).filter(x=>x.startsWith('epoch-launch-intent-')).length,1);console.log('16 parallel claims: exactly one launch intent');}).catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>fs.rmSync(root,{recursive:true,force:true}));
}
