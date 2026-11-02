'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto'),{parseStrict}=require('./strict-json');
const APP='org.codex.siriremote.v20scheduler20261031a',SERVICE=APP+'.service';
const ROOT='/media/developer/apps/usr/palm/applications';
const NAME=APP+'.persistent';
function verifyPins(root=ROOT,pins=require('./pins')){
 for(const pin of Object.values(pins)){
  for(const [name,digest] of Object.entries(pin.files)){
   if(name.includes('..')||path.isAbsolute(name))throw Error('pin-path');
   const file=path.join(root,pin.appId,name),s=fs.lstatSync(file);
   if(!s.isFile()||s.isSymbolicLink()||crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')!==digest)throw Error('installed-package-pin-mismatch');
  }
  const packagePath=path.join(path.dirname(root),'packages',pin.appId,'packageinfo.json');
  if(crypto.createHash('sha256').update(fs.readFileSync(packagePath)).digest('hex')!==pin.packageInfoSha256)throw Error('installed-package-info-mismatch');
 }
 // The controller in this candidate obtains the receiver pin from the
 // scheduler, not the developer-owned state file. Exact installed A/B and
 // package hashes were already checked above before any Activity operation.
 return true;
}
function call(handle,uri,payload,timers=globalThis){return new Promise(resolve=>{
 let done=false;const finish=v=>{if(done)return;done=true;timers.clearTimeout(t);resolve(v);};
 const t=timers.setTimeout(()=>finish(null),6000);
 try{const req=handle.call(uri,JSON.stringify(payload));req.addListener('response',m=>{try{const raw=m.payload();if(typeof raw!=='string'||Buffer.byteLength(raw)>8192)throw Error();const v=parseStrict(raw);if(!v||typeof v.returnValue!=='boolean')throw Error();finish(v);}catch(_){finish(null);}});}catch(_){finish(null);}
});}
function journal(dir){
 const s=fs.lstatSync(dir);if(!s.isDirectory()||s.isSymbolicLink()||s.uid!==process.getuid()||(s.mode&0o777)!==0o700)throw Error('private-state-required');
 return {write(name,value){const fd=fs.openSync(path.join(dir,name),'wx',0o600);try{fs.writeFileSync(fd,JSON.stringify(value)+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}const d=fs.openSync(dir,'r');try{fs.fsyncSync(d);}finally{fs.closeSync(d);}},read(name){const f=path.join(dir,name),s=fs.lstatSync(f);if(!s.isFile()||s.isSymbolicLink()||s.uid!==process.getuid()||(s.mode&0o777)!==0o600||s.size>8192)throw Error('bad-journal');return parseStrict(fs.readFileSync(f,'utf8'));}};
}
async function provisionUnlocked({handle,stateDir,intent=false,verify=verifyPins,now=Date.now,timers=globalThis,random=n=>crypto.randomBytes(n).toString('hex'),report=()=>{}}){
 if(intent!==true)return {status:'disabled'};verify();const disk=journal(stateDir);
 if(fs.existsSync(path.join(stateDir,'cancel-request.json'))){report({stage:'finished',status:'provision-cancelled-before-create'});return {status:'provision-cancelled-before-create',automaticRetry:false};}
 const run=random(16),nonce=random(24),token=random(24);
 const binding={schema:1,appId:APP,activityName:NAME,run,nonce,token};
 // Claim precedes prepare/create: no retry after any ambiguous dispatch.
 disk.write('provision-intent.json',binding);report({stage:'intent-reserved',status:'provision-dispatch-pending'});
 const prep=await call(handle,'luna://'+SERVICE+'/prepare',{run,nonce,token,intent:'enable-experimental-tv-local-startup'},timers);
 if(!prep||prep.returnValue!==true||prep.status!=='prepared'){disk.write('provision-result.json',{...binding,status:'prepare-unconfirmed'});report({stage:'finished',status:'prepare-unconfirmed'});return {status:'prepare-unconfirmed',automaticRetry:false};}
 if(fs.existsSync(path.join(stateDir,'cancel-request.json'))){disk.write('provision-result.json',{...binding,status:'provision-cancelled-before-create'});report({stage:'finished',status:'provision-cancelled-before-create'});return {status:'provision-cancelled-before-create',automaticRetry:false};}
 const start=new Date(now()+120000).toISOString().replace('T',' ').replace(/\.\d{3}Z$/,'Z');
 const created=await call(handle,'luna://com.webos.service.activitymanager/create',{activity:{name:NAME,description:'Experimental Siri Remote v20 TV-local startup',type:{foreground:true,persist:true,explicit:false,continuous:false},schedule:{start},callback:{method:'luna://'+SERVICE+'/tick',params:{run,nonce,token}}},start:true,subscribe:false,replace:false},timers);
 if(!created||created.returnValue!==true||!Number.isSafeInteger(created.activityId)||created.activityId<1){disk.write('provision-result.json',{...binding,status:'create-unconfirmed'});report({stage:'finished',status:'create-unconfirmed'});return {status:'create-unconfirmed',automaticRetry:false};}
 const receipt={...binding,activityId:created.activityId,status:'created'};disk.write('created.json',receipt);report({stage:'created',status:'created-bind-pending',activityId:created.activityId});
 const bound=await call(handle,'luna://'+SERVICE+'/bind',{run,nonce,token,activityId:created.activityId,activityName:NAME},timers);
 const status=bound&&bound.returnValue===true&&bound.status==='bound'&&bound.activityId===created.activityId?'armed-unverified-on-hardware':'bind-unconfirmed';
 disk.write('provision-result.json',{...receipt,status});report({stage:'finished',status,activityId:created.activityId});return {status,activityId:created.activityId,automaticRetry:false,productionReady:false};
}
async function cancelUnlocked({handle,stateDir,intent=false,timers=globalThis,report=()=>{}}){
 if(intent!==true)return {status:'disabled'};
 const disk=journal(stateDir);
 if(!fs.existsSync(path.join(stateDir,'provision-intent.json'))){report({stage:'finished',status:'cancelled-before-provision'});return {status:'cancelled-before-provision',automaticRetry:false};}
 const b=disk.read('provision-intent.json');
 if(b.appId!==APP||b.activityName!==NAME||!/^[a-f0-9]{32}$/.test(b.run))throw Error('cancel-binding-mismatch');
 disk.write('cancel-intent.json',{appId:APP,activityName:NAME,run:b.run});report({stage:'intent-reserved',status:'cancel-dispatch-pending'});
 const disabled=await call(handle,'luna://'+SERVICE+'/disarm',{run:b.run,nonce:b.nonce,activityName:NAME},timers);
 if(!disabled||disabled.returnValue!==true||disabled.status!=='disarmed'){disk.write('cancel-result.json',{appId:APP,run:b.run,status:'disarm-unconfirmed'});report({stage:'finished',status:'disarm-unconfirmed'});return {status:'disarm-unconfirmed',automaticRetry:false};}
 if(!fs.existsSync(path.join(stateDir,'created.json'))&&fs.existsSync(path.join(stateDir,'provision-result.json'))&&disk.read('provision-result.json').status==='provision-cancelled-before-create'){disk.write('cancel-result.json',{appId:APP,run:b.run,status:'cancelled-before-create'});report({stage:'finished',status:'cancelled-before-create'});return {status:'cancelled-before-create',automaticRetry:false};}
 // Exact name under original creator identity; no numeric ID reuse assumption.
 const r=await call(handle,'luna://com.webos.service.activitymanager/cancel',{activityName:NAME},timers);
 const status=r&&r.returnValue===true?'cancel-acknowledged-absence-unverified':'cancel-unconfirmed';
 disk.write('cancel-result.json',{appId:APP,activityName:NAME,run:b.run,status});report({stage:'finished',status});return {status,automaticRetry:false};
}
// Cross-process lock: stale/uncertain owners are retained, never stolen.
async function serialized(options,operation){
 journal(options.stateDir);
 const lock=path.join(options.stateDir,'operation-lock');const deadline=Date.now()+25000;
 while(true){try{fs.mkdirSync(lock,0o700);break;}catch(e){if(e.code!=='EEXIST')throw e;if(Date.now()>=deadline)throw Error('operation-busy-retain-state');await new Promise(r=>setTimeout(r,25));}}
 try{return await operation(options);}finally{fs.rmdirSync(lock);}
}
function provision(options){if(options.intent!==true)return Promise.resolve({status:'disabled'});return serialized(options,provisionUnlocked);}
async function cancel(options){
 if(options.intent!==true)return Promise.resolve({status:'disabled'});
 // Durable veto is published before waiting, including cancellation before prepare.
 journal(options.stateDir).write('cancel-request.json',{schema:1,requested:true});
 return serialized(options,cancelUnlocked);
}
module.exports={APP,SERVICE,NAME,verifyPins,provision,cancel,call,journal};
