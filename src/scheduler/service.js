'use strict';
// Offline candidate service: service-owned binding plus authenticated repeat callback
// and durable per-kernel-boot one-shot coordinator launch.
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const { createRuntimeBridge } = require('./runtime-bridge');
const {createAdmission}=require('./callback-admission');
const { readBootIdentity, createBootClaimStore } = require('./boot-claim-store');
const { parseStrict } = require('./strict-json');
const { createTransport } = require('./transport');
const {ensurePrivateDirectory}=require('./private-directory');
const APP='org.codex.siriremote.v20scheduler20261031a', SERVICE=APP+'.service';
const ROOT='/media/internal/.codex-v20-scheduler-v1';
const RUN=/^[a-f0-9]{32}$/, NONCE=/^[a-f0-9]{48}$/;
function safePayload(m){const s=m.payload();if(typeof s!=='string'||Buffer.byteLength(s,'utf8')>2048)throw Error('payload-invalid');return parseStrict(s);}
function exactSender(m,expected,method){if(m.senderServiceName()!==expected||m.category()!=='/'||m.method()!==method||m.isSubscription()!==false)throw Error('identity-rejected');}
function canonical(v){return JSON.stringify(v)+'\n';}
function writeExclusive(file,value){const fd=fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);try{fs.writeFileSync(fd,canonical(value));fs.fsyncSync(fd);}finally{fs.closeSync(fd);}const d=fs.openSync(path.dirname(file),fs.constants.O_RDONLY|fs.constants.O_DIRECTORY);try{fs.fsyncSync(d);}finally{fs.closeSync(d);}}
function readSafe(file){const s=fs.lstatSync(file);if(!s.isFile()||s.isSymbolicLink()||s.nlink!==1||s.size>2048||s.uid!==process.getuid()||(s.mode&0o777)!==0o600)throw Error('binding-invalid');const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);try{const f=fs.fstatSync(fd);if(f.dev!==s.dev||f.ino!==s.ino||f.size!==s.size||f.uid!==process.getuid()||(f.mode&0o777)!==0o600)throw Error('binding-raced');const b=fs.readFileSync(fd,'utf8'),v=JSON.parse(b);if(canonical(v)!==b)throw Error('binding-not-canonical');return v;}finally{fs.closeSync(fd);}}
function createService({Handle=require('palmbus').Handle,fsys=fs,root=ROOT,appId=APP,serviceId=SERVICE,getBootIdentity=readBootIdentity,volatileRoot='/dev/shm',timers=globalThis,processExit=()=>process.exit(0),expiryRun=require('./expiry-policy').run}={}){
 if(appId!==APP||serviceId!==SERVICE)throw Error('fixed-identity-required');
 if(global.unified_service)throw Error('already-running');global.unified_service=true;
 const handle=new Handle(serviceId), active=new Map(), admissions=new Map();let stopped=false, callbackTail=Promise.resolve();
 let lifetime;const resetLifetime=(ms=20000)=>{if(lifetime)timers.clearTimeout(lifetime);lifetime=timers.setTimeout(close,ms);};
 const respond=(m,v)=>{resetLifetime();try{m.respond(JSON.stringify(v));}catch(_){}};
 function dirFor(run){return path.join(root,run);}
 function ensureRoot(){return ensurePrivateDirectory(root,fsys);}
 function prepare(m){try{exactSender(m,appId,'prepare');const q=safePayload(m);if(q.intent!=='enable-experimental-tv-local-startup')throw Error('intent-required');if(Object.keys(q).sort().join(',')!=='intent,nonce,run,token'||!RUN.test(q.run||'')||(!NONCE.test(q.nonce||'')||!NONCE.test(q.token||'')))throw Error('request-invalid');ensureRoot();createBootClaimStore(root,getBootIdentity,{volatileRoot}).initialize();const d=dirFor(q.run);ensurePrivateDirectory(d,fsys,true);const ds=fsys.lstatSync(d);if(!ds.isDirectory()||ds.isSymbolicLink()||ds.uid!==process.getuid()||(ds.mode&0o777)!==0o700)throw Error('run-dir-invalid');const rec={schema:1,appId,run:q.run,nonce:q.nonce,token:q.token,state:'prepared'};writeExclusive(path.join(d,'binding.json'),rec);
const admission=createAdmission({prepared:{creator:appId,callbackService:serviceId,activityName:appId+'.persistent',run:q.run,nonce:q.nonce,token:q.token},parse:parseStrict,timers,journal:{write:(name,value)=>writeExclusive(path.join(d,name),value)},commitBinding:q=>{const binding={schema:1,appId,run:q.run,nonce:q.nonce,token:q.token,activityId:q.activityId,activityName:q.activityName,state:'bound'};require('./rotation-store').initialize(d,binding);writeExclusive(path.join(d,'binding.bound.json'),binding);},makeBridge:()=>({handle:async m=>{await boundTick(m);return {status:'delegated'};}})});
admissions.set(q.run,admission);respond(m,{returnValue:true,status:'prepared',run:q.run});}catch(_){respond(m,{returnValue:false,status:'rejected'});}}
 function bind(m){try{exactSender(m,appId,'bind');const q=safePayload(m);if(Object.keys(q).sort().join(',')!=='activityId,activityName,nonce,run,token'||!RUN.test(q.run||'')||(!NONCE.test(q.nonce||'')||!NONCE.test(q.token||''))||!Number.isSafeInteger(q.activityId)||q.activityId<1||q.activityName!==appId+'.persistent')throw Error('request-invalid');ensureRoot();const d=dirFor(q.run),old=readSafe(path.join(d,'binding.json'));if(old.appId!==appId||old.run!==q.run||(old.nonce!==q.nonce||old.token!==q.token)||old.state!=='prepared')throw Error('prepare-mismatch');const admission=admissions.get(q.run);if(!admission||admission.bind(q).status!=='bound')throw Error('admission-bind-rejected');const st=fsys.statSync(d);respond(m,{returnValue:true,status:'bound',run:q.run,activityId:q.activityId,dirDev:st.dev,dirIno:st.ino});}catch(_){respond(m,{returnValue:false,status:'rejected'});}}
 let resumeBusy=false;
 async function resumeVerified(m){
  let acquired=false;
  try{exactSender(m,appId,'resumeVerified');const q=safePayload(m);
   if(Object.keys(q).sort().join(',')!=='eligible,fingerprint,run'||!require('./standby-resume').valid(q)||resumeBusy)throw Error('invalid-resume');
   resumeBusy=true;acquired=true;ensureRoot();
   const result=await require('./standby-resume').run({root,handle,evidence:async()=>q,verify:()=>true,launch:id=>require('./coordinator-launcher').createLauncher(handle,timers,8000).launch(id)});
   respond(m,{returnValue:result.status==='launch-accepted'||result.status==='already-claimed',...result});
  }catch(_){respond(m,{returnValue:false,status:'resume-unconfirmed'});}finally{if(acquired)resumeBusy=false;}
 }
 async function expiryCheck(m){
  try{exactSender(m,appId,'expiryCheck');if(m.payload()!=='{}')throw Error('request-invalid');ensureRoot();
   const result=await expiryRun({root:path.join(root,'expiry'),handle,allowExtension:false,forceRead:true});
   respond(m,{returnValue:result.status==='time-sufficient'||result.status==='due-read-only'||result.status==='renewal-verified',...result});
  }catch(_){respond(m,{returnValue:false,status:'rejected'});}
 }
 function receiverPin(m){try{if(m.category()!=='/'||m.method()!=='receiverPin'||m.isSubscription()!==false||m.payload()!=='{}')throw Error('request-invalid');respond(m,{returnValue:true,pin:require('./pins').receiver});}catch(_){respond(m,{returnValue:false,status:'rejected'});}}
 function disarm(m){try{exactSender(m,appId,'disarm');const q=safePayload(m);if(Object.keys(q).sort().join(',')!=='activityName,nonce,run'||!RUN.test(q.run||'')||q.activityName!==appId+'.persistent')throw Error('bad-disarm');ensureRoot();const d=dirFor(q.run),b=readSafe(path.join(d,'binding.json'));if(b.run!==q.run||b.nonce!==q.nonce||b.appId!==appId)throw Error('binding-mismatch');const file=path.join(d,'disabled.json');try{writeExclusive(file,{schema:1,run:q.run,disabled:true});}catch(e){if(e.code!=='EEXIST')throw e;const old=readSafe(file);if(old.run!==q.run||old.disabled!==true)throw Error('bad-disarm-state');}respond(m,{returnValue:true,status:'disarmed'});}catch(_){respond(m,{returnValue:false,status:'disarm-unconfirmed'});}}
 async function boundTick(m){try{if(m.senderServiceName()!=='com.webos.service.activitymanager'||m.applicationID()!==appId||m.category()!=='/'||m.method()!=='tick'||m.isSubscription()!==false)throw Error('callback-identity');const p=safePayload(m);if(Object.keys(p).sort().join(',')!=='$activity,nonce,run,token'||!p.$activity||!Number.isSafeInteger(p.$activity.activityId)||(!NONCE.test(p.nonce||'')||!NONCE.test(p.token||'')||!RUN.test(p.run||'')))throw Error('callback-payload');ensureRoot();const found=[];for(const n of fsys.readdirSync(root)){if(!RUN.test(n))continue;try{const b=readSafe(path.join(dirFor(n),'binding.bound.json'));if(b.activityId===p.$activity.activityId&&b.nonce===p.nonce&&b.run===p.run)found.push(b);}catch(_){}}if(found.length!==1)throw Error('binding-not-unique');const b=found[0];if(fsys.existsSync(path.join(dirFor(b.run),'disabled.json')))throw Error('binding-disabled');let bridge=active.get(b.run);if(!bridge){const expected={creator:appId,activityId:b.activityId,nonce:b.nonce,run:b.run,callbackService:serviceId};const cbDeps={parse:parseStrict,...createTransport(handle,parseStrict,timers,15000,stage=>{try{const value={schema:1,epochMs:Date.now(),activityId:b.activityId,stage};const tmp=path.join(root,'.transport-status-'+process.pid);fs.writeFileSync(tmp,JSON.stringify(value)+'\n',{mode:0o600});fs.renameSync(tmp,path.join(root,'transport-status.json'));}catch(_){}})};bridge=createRuntimeBridge({handle,expected,callbackDeps:cbDeps,stateDir:dirFor(b.run),getBootIdentity:()=>getBootIdentity(),volatileRoot,timers,resume:()=>require('./wake-checker').run({root,handle,timers}),launchOverride:{launch:id=>require('./coordinator-launcher').createLauncher(handle,timers,8000).launch(id)}});active.set(b.run,bridge);}const result=await bridge.handle(m);const okay=result.status==='launch-accepted'||result.status==='already-claimed';respond(m,{returnValue:okay,status:result.status});if(okay){resetLifetime(60000);try{await expiryRun({root:path.join(root,'expiry'),handle});}catch(_){}finally{resetLifetime();}}}catch(_){respond(m,{returnValue:false,status:'unknown'});}}
 async function tick(m){
  try{
   // Apply the existing sender/shape checks before selecting any prepared run.
   if(m.senderServiceName()!=='com.webos.service.activitymanager'||m.applicationID()!==appId||m.category()!=='/'||m.method()!=='tick'||m.isSubscription()!==false)throw Error('callback-identity');
   const p=safePayload(m);if(Object.keys(p).sort().join(',')!=='$activity,nonce,run,token'||!p.$activity||!Number.isSafeInteger(p.$activity.activityId)||p.$activity.activityId<1||!NONCE.test(p.nonce||'')||!NONCE.test(p.token||'')||!RUN.test(p.run||''))throw Error('callback-payload');
   const admission=admissions.get(p.run);
   if(!admission){await boundTick(m);return;}
   const r=await admission.handle(m);
   if(r.status!=='delegated')respond(m,{returnValue:false,status:r.status});
  }catch(_){respond(m,{returnValue:false,status:'unknown'});}
 }
 handle.registerMethod('/','resumeVerified');handle.registerMethod('/','stateSummary');handle.registerMethod('/','expiryCheck');handle.registerMethod('/','receiverPin');handle.registerMethod('/','disarm');handle.registerMethod('/','prepare');handle.registerMethod('/','bind');handle.registerMethod('/','tick');handle.addListener('request',m=>{resetLifetime(60000);if(m.method()==='resumeVerified'){resumeVerified(m);}else if(m.method()==='stateSummary'){try{if(m.payload()!=='{}'||m.isSubscription()!==false)throw Error();require('./standby-resume').readPower(handle,timers).then(power=>respond(m,{returnValue:true,...require('./state-summary').read(root),power})).catch(()=>respond(m,{returnValue:false,status:'unavailable'}));}catch(_){respond(m,{returnValue:false,status:'unavailable'});}}else if(m.method()==='expiryCheck'){const next=callbackTail.then(()=>expiryCheck(m),()=>expiryCheck(m));callbackTail=next.catch(()=>{});}else if(m.method()==='receiverPin')receiverPin(m);else if(m.method()==='disarm'){const next=callbackTail.then(()=>disarm(m),()=>disarm(m));callbackTail=next.catch(()=>{});}else if(m.method()==='prepare')prepare(m);else if(m.method()==='bind')bind(m);else if(m.method()==='tick'){const operation=()=>{resetLifetime(60000);return tick(m);};const next=callbackTail.then(operation,operation);callbackTail=next.catch(()=>{});}});
 function close(){if(stopped)return;stopped=true;if(lifetime)timers.clearTimeout(lifetime);try{handle.unregister();}catch(_){}global.unified_service=false;processExit();}
 resetLifetime(20000);
 return {handle,close,active};
}
module.exports={APP,SERVICE,ROOT,createService};
