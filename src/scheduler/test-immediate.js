'use strict';
const assert=require('assert'),fs=require('fs'),path=require('path'),os=require('os'),{EventEmitter}=require('events');
const creator=require('./creator'),service=require('./service'),APP=creator.APP;
async function scenario(early,callbackId=165){
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'early-v4-'));fs.chmodSync(temp,0o700);
 const root=path.join(temp,'service'),state=path.join(temp,'app');fs.mkdirSync(state,{mode:0o700});
 let listener,created,tickPromise,launches=0;const calls=[];
 const reply=(req,value)=>queueMicrotask(()=>req.emit('response',{payload:()=>JSON.stringify(value)}));
 const tick=(params,who='com.webos.service.activitymanager')=>new Promise(resolve=>listener({senderServiceName:()=>who,applicationID:()=>APP,category:()=> '/',method:()=> 'tick',isSubscription:()=>false,payload:()=>JSON.stringify({...params,$activity:{activityId:callbackId}}),respond:raw=>resolve(JSON.parse(raw))}));
 function dispatch(sender,uri,payload){const req=new EventEmitter(),q=JSON.parse(payload);calls.push({sender,uri,q});
  if(uri.startsWith('luna://'+APP+'.service/'))queueMicrotask(()=>listener({senderServiceName:()=>sender,applicationID:()=>sender,category:()=> '/',method:()=>uri.split('/').pop(),isSubscription:()=>false,payload:()=>payload,respond:raw=>reply(req,JSON.parse(raw))}));
  else if(uri.endsWith('/create')){
   created=q;
   if(early){queueMicrotask(()=>{tickPromise=tick(q.activity.callback.params);setImmediate(()=>{
    assert(!calls.some(c=>c.uri.endsWith('/adopt')||c.uri.endsWith('/complete')||c.uri.endsWith('/launch')));
    reply(req,{returnValue:true,activityId:165});
   });});}else reply(req,{returnValue:true,activityId:165});
  }else if(uri.endsWith('/adopt'))reply(req,{returnValue:true,adopted:true});
  else if(uri.endsWith('/complete')||uri.endsWith('/cancel'))reply(req,{returnValue:true});
  else if(uri.endsWith('/launch')){launches++;reply(req,{returnValue:true});}
  else throw Error('unexpected LS2');
  req.cancel=()=>true;return req;
 }
 class Handle{constructor(id){this.id=id;}registerMethod(){}addListener(_,fn){listener=fn;}call(uri,payload){return dispatch(this.id,uri,payload);}subscribe(uri,payload){return dispatch(this.id,uri,payload);}unregister(){}}
 const runtime=service.createService({expiryRun:async()=>({status:"test-disabled"}),Handle,root,volatileRoot:root,getBootIdentity:()=>({bootId:'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',btime:1000,uptimeMs:1000}),processExit:()=>{}}),h=new Handle(APP);
 try{
  const result=await creator.provision({handle:h,stateDir:state,intent:true,verify:()=>{}});if(callbackId!==165){
   assert.equal(result.status,'bind-unconfirmed');assert.equal((await tickPromise).status,'attention');
   assert.equal(launches,0);assert(!calls.some(c=>c.uri.endsWith('/adopt')||c.uri.endsWith('/complete')));return;
  }
  assert.equal(result.status,'armed-unverified-on-hardware');
  assert(created.activity.schedule.start);assert.equal(created.activity.trigger,undefined);
  if(!early)tickPromise=tick(created.activity.callback.params);
  assert.equal((await tickPromise).status,'launch-accepted');assert.equal(launches,1);
  const complete=calls.find(c=>c.uri.endsWith('/complete'));assert(complete.q.schedule.start);assert.equal(complete.q.restart,true);
  assert.equal(calls.filter(c=>c.uri.endsWith('/create')).length,1);assert.equal(calls.filter(c=>c.uri.endsWith('/complete')).length,1);
  assert.equal((await tick(created.activity.callback.params)).status,'callback-not-confirmed');assert.equal(launches,1);
  assert.equal((await tick(created.activity.callback.params,'attacker')).status,'unknown');assert.equal(launches,1);
  const files=fs.readdirSync(path.join(root,created.activity.callback.params.run));assert.equal(files.includes('edge-admission-early.json'),early);
  const canceled=await creator.cancel({handle:h,stateDir:state,intent:true});assert.equal(canceled.status,'cancel-acknowledged-absence-unverified');
  const disarm=calls.findIndex(c=>c.uri.endsWith('/disarm')),cancel=calls.findIndex(c=>c.uri.endsWith('/cancel'));
  assert(disarm>=0&&cancel>disarm);assert.equal(calls[cancel].sender,APP);assert.deepEqual(calls[cancel].q,{activityName:creator.NAME});
  const current=JSON.parse(fs.readFileSync(path.join(root,created.activity.callback.params.run,'rotation-state.json'))).token;
  assert.equal((await tick({...created.activity.callback.params,token:current})).status,'unknown');assert.equal(launches,1);
 }finally{runtime.close();fs.rmSync(temp,{recursive:true,force:true});}
}
(async()=>{await scenario(true);await scenario(false);await scenario(true,166);console.log('PASS real creator/service/bridge: callback during create and callback after bind, existing token auth, schedule rearm and disarm-before-cancel');})().catch(e=>{console.error(e);process.exitCode=1;});
