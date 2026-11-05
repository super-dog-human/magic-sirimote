'use strict';
const assert=require('assert'),EventEmitter=require('events'),cp=require('child_process');
const {createService}=require('../src/integrated/service');
const {createControllerPreloader}=require('../src/integrated/controller-preload');
const empty=()=>({controller:[],receiver:[],legacy:[],ui:[]});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function fixture({enabled=true,registered=true,conflict=false}={}) {
 const scheduled=[],helpers=[];let deps,child,token,found=empty();
 if(conflict)found.receiver=[{pid:9}];
 class Handle extends EventEmitter{registerMethod(){}unregister(){}}
 const original=cp.execFile;
 cp.execFile=(exe,args,options,callback)=>{
  helpers.push(args.at(-1));setImmediate(()=>callback(null,JSON.stringify({returnValue:true,processes:found})));
  return {stdin:{on(){},end(){}}};
 };
 const timers={setTimeout(callback,delay){const t={callback,delay};scheduled.push(t);return t;},clearTimeout(t){const i=scheduled.indexOf(t);if(i>=0)scheduled.splice(i,1);}};
 const {handle}=createService({Handle,timers,startupStore:{},powerReader:{read:async()=>({state:'Active'}),close(){}},
  startupFactory:()=>({summary:()=>({enabled,registered}),poll:dependencies=>{deps=dependencies;},disable(){enabled=false;return {returnValue:true};}}),
  processReader:()=>found,
  preloaderFactory:()=>createControllerPreloader({uid:6000,timers,spawn(value){
   token=value;child=new EventEmitter();child.pid=123;child.exitCode=null;child.stdout=new EventEmitter();child.stdin=new EventEmitter();child.sent=[];child.stdin.end=value=>child.sent.push(value);
   found={...empty(),controller:[{pid:123,startTicks:456,uid:6000}]};return child;
  }})});
 scheduled.find(x=>x.delay===0).callback();await flush();
 function request(method){return new Promise(resolve=>handle.emit('request',{method:()=>method,category:()=> '/',payload:()=> '{}',isSubscription:()=>false,senderServiceName:()=> 'org.magicsirimote.app',respond:raw=>resolve(JSON.parse(raw))}));}
 return {child,helpers,deps,scheduled,request,
  ready(){child.stdout.emit('data',Buffer.from(JSON.stringify({stage:'controller-preloaded',token,pid:123,startTicks:456})+'\n'));},
  exit(){child.exitCode=0;found=empty();child.emit('exit',0);},
  close(){cp.execFile=original;global.unified_service=false;}};
}
(async()=>{
 for(const options of [{enabled:false},{registered:false},{conflict:true}]){
  const f=await fixture(options);try{assert.equal(f.child,undefined);}finally{f.close();}
 }
 {
  const f=await fixture();try{
   f.ready();assert.deepEqual(f.child.sent,[],'Preparing or reading power cannot release input');
   assert.deepEqual((await f.deps.status()).processes,empty());
   assert.equal((await f.request('status')).processes.controller.length,1,'Public process status retains the prepared child');
   assert.equal((await f.deps.start()).status,'starting');
   assert.equal(JSON.parse(f.child.sent[0]).action,'start');
   assert.equal((await f.deps.status()).processes.controller.length,1,'Activated controller stays visible');
  }finally{f.close();}
 }
 {
  const f=await fixture();try{
   const reply=f.request('stop');await flush();assert.deepEqual(f.child.sent,[undefined]);assert.deepEqual(f.helpers,[]);
   f.exit();assert.equal((await reply).returnValue,true);assert.deepEqual(f.helpers,['stop']);
  }finally{f.close();}
 }
 {
  const f=await fixture();try{
   const reply=f.request('drain');await flush();f.scheduled.find(x=>x.delay===10000).callback();
   assert.equal((await reply).returnValue,false);assert.deepEqual(f.helpers,[],'No helper proceeds before pending child exits');
   assert.equal((await f.deps.status()).processes.controller.length,1);
  }finally{f.close();}
 }
 console.log('Prepared service: startup gating, public visibility, activation and confirmed cancellation passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
