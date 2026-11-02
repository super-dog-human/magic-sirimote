'use strict';
const assert=require('assert'),fs=require('fs'),path=require('path'),os=require('os'),{EventEmitter}=require('events');
const base=process.argv[2],APP='org.codex.siriremote.v20scheduler20261031a';
const app=require('./creator'),main=require('./main');
const service=require('./service'),expiry=require('./expiry');let expiryQueries=0,expiryLaunches=0;
const expiryRun=opts=>expiry.run({...opts,query:async()=>{expiryQueries++;return {remainingSeconds:1000*3600};},launch:async()=>{expiryLaunches++;return 'acknowledged';}});
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'scheduler-e2e-'));fs.chmodSync(temp,0o700);const root=path.join(temp,'service');let listener,calls=[],launches=0,created,subscriptionCanceled=0;
 const reply=(req,value)=>queueMicrotask(()=>req.emit('response',{payload:()=>JSON.stringify(value)}));
 function dispatch(sender,uri,payload){const req=new EventEmitter(),q=JSON.parse(payload);calls.push([sender,uri,q]);
  if(uri.startsWith('luna://'+APP+'.service/'))queueMicrotask(()=>listener({senderServiceName:()=>sender,applicationID:()=>sender,category:()=> '/',method:()=>uri.split('/').pop(),isSubscription:()=>false,payload:()=>payload,respond:raw=>reply(req,JSON.parse(raw))}));
  else if(uri.endsWith('/create')){created=q;reply(req,{returnValue:true,activityId:42});}
  else if(uri.endsWith('/adopt'))reply(req,{returnValue:true,adopted:true});
  else if(uri.endsWith('/complete')||uri.endsWith('/cancel'))reply(req,{returnValue:true});
  else if(uri.endsWith('/launch')){launches++;reply(req,{returnValue:true});}
  else throw Error('unexpected LS2');
  req.cancel=()=>{subscriptionCanceled++;return true;};return req;
 }
 class Handle{constructor(id){this.id=id;}registerMethod(){}addListener(event,fn){listener=fn;}call(uri,payload){return dispatch(this.id,uri,payload);}subscribe(uri,payload){return dispatch(this.id,uri,payload);}unregister(){}}
 let runtime=service.createService({expiryRun,Handle,root,volatileRoot:root,getBootIdentity:()=>({bootId:'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',btime:1000,uptimeMs:1000}),processExit:()=>{}});
 const creatorState=path.join(temp,'creator');fs.mkdirSync(creatorState,{mode:0o700});let verifyCount=0;
 const h=new Handle(APP);
 const badState=path.join(temp,'bad');fs.mkdirSync(badState,{mode:0o700});
 await assert.rejects(()=>app.provision({handle:h,stateDir:badState,intent:true,verify:()=>{throw Error('pin-mismatch');}}),/pin-mismatch/);assert.equal(calls.length,0);
 const uncertainState=path.join(temp,'uncertain');fs.mkdirSync(uncertainState,{mode:0o700});let unknownCalls=0;
 const uncertainHandle={call(uri,payload){unknownCalls++;const req=new EventEmitter();reply(req,uri.endsWith('/prepare')?{returnValue:true,status:'prepared'}:{bad:true});return req;}};
 assert.equal((await app.provision({handle:uncertainHandle,stateDir:uncertainState,intent:true,verify:()=>{}})).status,'create-unconfirmed');assert.equal(unknownCalls,2);
 await assert.rejects(()=>app.provision({handle:uncertainHandle,stateDir:uncertainState,intent:true,verify:()=>{}}),/EEXIST/);assert.equal(unknownCalls,2);
 assert.equal((await main.main({state:path.join(temp,'empty'),Handle})).status,'disabled');assert.equal(calls.length,0);
 assert.equal((await app.provision({handle:h,stateDir:creatorState})).status,'disabled');
 const stages=[];const result=await app.provision({handle:h,stateDir:creatorState,intent:true,verify:()=>{verifyCount++;},report:event=>{stages.push(event);require('./public-status').publish(creatorState,{...event,action:'provision',operationId:'a'.repeat(32)});}});assert.deepEqual(stages.map(e=>e.stage),['intent-reserved','created','finished']);assert.equal(JSON.parse(fs.readFileSync(path.join(creatorState,'public-status.json'))).activityId,42);assert.equal(result.status,'armed-unverified-on-hardware');assert.equal(verifyCount,1);
 assert.equal(created.activity.type.persist,true);assert.equal(created.replace,false);assert.equal(created.subscribe,false);assert.equal(created.activity.name,app.NAME);
 const q=created.activity.callback.params;
 const tick=()=>new Promise(resolve=>listener({senderServiceName:()=> 'com.webos.service.activitymanager',applicationID:()=>APP,category:()=> '/',method:()=> 'tick',isSubscription:()=>false,payload:()=>JSON.stringify({...q,$activity:{activityId:42}}),respond:raw=>resolve(JSON.parse(raw))}));
 assert.equal((await tick()).status,'launch-accepted');await new Promise(r=>setImmediate(r));assert.equal(expiryQueries,1);assert.equal(expiryLaunches,0);assert.equal(launches,1);assert.equal(subscriptionCanceled,1);
 assert.equal((await tick()).status,'callback-not-confirmed');assert.equal(launches,1);
 await assert.rejects(()=>app.provision({handle:h,stateDir:creatorState,intent:true,verify:()=>{}}),/EEXIST/);
 runtime.close();runtime=service.createService({expiryRun,Handle,root,volatileRoot:root,getBootIdentity:()=>({bootId:'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',btime:1000,uptimeMs:1000}),processExit:()=>{}});
 q.token=JSON.parse(fs.readFileSync(path.join(root,q.run,'rotation-state.json'),'utf8')).token;
 assert.equal((await tick()).status,'already-claimed');await new Promise(r=>setImmediate(r));assert.equal(expiryQueries,1);assert.equal(launches,1);
 assert.equal((await app.cancel({handle:h,stateDir:creatorState,intent:true})).status,'cancel-acknowledged-absence-unverified');
 assert.equal((await tick()).status,'unknown');assert.equal(launches,1);
 const cancel=calls.find(x=>x[1].endsWith('/cancel'));assert.equal(cancel[0],APP);assert.deepEqual(cancel[2],{activityName:app.NAME});
 await assert.rejects(()=>app.cancel({handle:h,stateDir:creatorState,intent:true}),/EEXIST/);
 assert.equal(expiryQueries,1);assert.equal(expiryLaunches,0);runtime.close();fs.rmSync(temp,{recursive:true,force:true});console.log('PASS real expiry module: authenticated callback queries once, replay/disabled callbacks excluded, daily limit survives service restart; cloned local app creator → service prepare/bind → persistent create → authenticated token tick → fixed launch; replay/reconstruction exclusion; original-creator exact-name cancel; default no action; no automatic repeat');
})().catch(e=>{console.error(e);process.exitCode=1});
