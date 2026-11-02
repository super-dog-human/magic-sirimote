'use strict';
const assert=require('assert'),fs=require('fs'),path=require('path'),os=require('os'),crypto=require('crypto'),{EventEmitter}=require('events');
const creator=require('./creator'),service=require('./service'),request=require('./rearm-request');
const APP=creator.APP,sha=b=>crypto.createHash('sha256').update(b).digest('hex');
async function scenario(mode){
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'rearm-')),state=path.join(tmp,'app'),root=path.join(tmp,'service'),oldDir=path.join(state,'creator-private');
 fs.mkdirSync(state,{mode:0o700});fs.mkdirSync(oldDir,{mode:0o700});
 let listener,activity=null,nextId=244,launches=0,unregistered=0,phase='initial';const calls=[];
 const reply=(req,v)=>queueMicrotask(()=>req.emit('response',{payload:()=>JSON.stringify(v)}));
 function dispatch(sender,uri,payload){
  const req=new EventEmitter(),q=JSON.parse(payload);calls.push({sender,uri,q});
  if(uri.startsWith('luna://'+APP+'.service/')){
   if(phase==='rearm'&&mode==='disarm-rejected'&&uri.endsWith('/disarm'))reply(req,{returnValue:false});
   else queueMicrotask(()=>listener({senderServiceName:()=>sender,applicationID:()=>sender,category:()=> '/',method:()=>uri.split('/').pop(),isSubscription:()=>false,payload:()=>payload,respond:raw=>reply(req,JSON.parse(raw))}));
  }else if(uri.endsWith('/create')){
   assert.strictEqual(q.replace,false);assert.strictEqual(sender,APP);
   if(activity){reply(req,{returnValue:false,errorCode:17});}
   else{activity={id:nextId++,q};reply(req,{returnValue:true,activityId:activity.id});}
  }else if(uri.endsWith('/cancel')){
   assert.deepStrictEqual(q,{activityName:creator.NAME});assert.strictEqual(sender,APP);
   if(mode==='cancel-unknown'){reply(req,{returnValue:false,errorCode:-1});}
   else{if(mode!=='collision')activity=null;reply(req,{returnValue:true});}
  }else if(uri.endsWith('/adopt'))reply(req,{returnValue:true,adopted:true});
  else if(uri.endsWith('/complete'))reply(req,{returnValue:true});
  else if(uri.endsWith('/launch')){launches++;reply(req,{returnValue:true});}
  else throw Error('unexpected method: '+uri);
  req.cancel=()=>true;return req;
 }
 class Handle{constructor(id){this.id=id;}registerMethod(){}addListener(_,fn){listener=fn;}call(uri,q){return dispatch(this.id,uri,q);}subscribe(uri,q){return dispatch(this.id,uri,q);}unregister(){unregistered++;}}
 const runtime=service.createService({expiryRun:async()=>({status:"test-disabled"}),Handle,root,volatileRoot:root,getBootIdentity:()=>({bootId:'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',btime:1000,uptimeMs:1000}),processExit:()=>{}});
 const tick=(a)=>new Promise(resolve=>listener({senderServiceName:()=> 'com.webos.service.activitymanager',applicationID:()=>APP,category:()=> '/',method:()=> 'tick',isSubscription:()=>false,payload:()=>JSON.stringify({...a.q.activity.callback.params,$activity:{activityId:a.id}}),respond:raw=>resolve(JSON.parse(raw))}));
 try{
  assert.strictEqual((await creator.provision({handle:new Handle(APP),stateDir:oldDir,intent:true,verify:()=>{}})).status,'armed-unverified-on-hardware');
  const oldActivity=activity,oldBytes=fs.readFileSync(path.join(oldDir,'created.json'));
  const q={schema:1,appId:APP,action:'rearm',operationId:'a'.repeat(32),priorCreated:'creator-private/created.json',priorCreatedSha256:sha(oldBytes),expiresEpochMs:Date.now()+120000};
  if(mode==='expired')q.expiresEpochMs=1;
  if(mode==='hash-mismatch')q.priorCreatedSha256='0'.repeat(64);
  if(mode==='traversal')q.priorCreated='../creator-private/created.json';
  const qfile=path.join(state,'rearm-request.json');fs.writeFileSync(qfile,JSON.stringify(q),{mode:0o640});fs.chmodSync(qfile,0o640);
  // Match the observed TV boot mode change. Hash validation permits the old
  // bytes to be read without rewriting historical evidence or trusting mode.
  fs.chmodSync(oldDir,0o775);fs.chmodSync(path.join(oldDir,'created.json'),0o775);
  phase='rearm';const before=calls.length;
  const options={state,Handle,verify:()=>{},requestUid:process.getuid(),ownerUid:process.getuid(),group:process.getgid()};
  if(mode==='prior-operation-busy')fs.mkdirSync(path.join(oldDir,'operation-lock'),{mode:0o700});
  if(['expired','hash-mismatch','traversal','prior-operation-busy'].includes(mode)){
   await assert.rejects(()=>request.run(options));assert.strictEqual(calls.length,before);return;
  }
  const result=await request.run(options),ops=calls.slice(before);
  assert.strictEqual(unregistered,1);assert.strictEqual(launches,0);
  assert(!ops.some(x=>x.uri.endsWith('/getActivityInfo')));
  assert.deepStrictEqual(fs.readFileSync(path.join(oldDir,'created.json')),oldBytes);
  assert.strictEqual(fs.statSync(path.join(oldDir,'created.json')).mode&0o777,0o775);
  if(mode==='disarm-rejected'){assert.strictEqual(result.status,'rearm-disarm-unconfirmed');assert.strictEqual(ops.length,1);}
  else if(mode==='cancel-unknown'){assert.strictEqual(result.status,'rearm-cancel-unconfirmed');assert.strictEqual(ops.length,2);}
  else if(mode==='collision'){assert.strictEqual(result.status,'create-unconfirmed');assert(!ops.some(x=>x.uri.endsWith('/bind')));}
  else{
   assert.strictEqual(result.status,'armed-unverified-on-hardware');assert.strictEqual(result.activityId,245);
   assert.deepStrictEqual(ops.map(x=>x.uri.split('/').pop()),['disarm','cancel','prepare','create','bind']);
   const oldTick=await tick(oldActivity);assert.strictEqual(oldTick.status,'unknown');assert.strictEqual(launches,0);
   const newTick=await tick(activity);assert.strictEqual(newTick.status,'launch-accepted');assert.strictEqual(launches,1);
   const newCreated=JSON.parse(fs.readFileSync(path.join(state,'rearm-'+q.operationId,'created.json')));
   assert.notStrictEqual(newCreated.run,JSON.parse(oldBytes).run);assert.notStrictEqual(newCreated.token,JSON.parse(oldBytes).token);
  }
  const after=calls.length;await assert.rejects(()=>request.run(options));assert.strictEqual(calls.length,after);
 }finally{runtime.close();fs.rmSync(tmp,{recursive:true,force:true});}
}
(async()=>{for(const mode of ['success','disarm-rejected','cancel-unknown','collision','expired','hash-mismatch','traversal','prior-operation-busy'])await scenario(mode);console.log('PASS 8 rearm scenarios: actual creator/service, old callbacks disabled, new callback launch, collision, unknown outcomes, exact receipt hash, expiry/path checks, shared creator lock, no replay');})().catch(e=>{console.error(e);process.exitCode=1;});
