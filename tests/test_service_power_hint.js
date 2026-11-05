'use strict';
const assert=require('assert'), EventEmitter=require('events');
const {createService}=require('../src/integrated/service');
const {createStartup}=require('../src/integrated/startup');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function main() {
  let state={schema:1,token:'a'.repeat(48),enabled:true,phase:'ready',activityId:17};
  let power='Active Standby',reads=0,starts=0,exited=false,readerClosed=false;
  const scheduled=new Set(), requests=[];
  const timers={setTimeout(fn,delay){const t={fn,delay};scheduled.add(t);return t;},clearTimeout(t){scheduled.delete(t);}};
  const store={read:()=>structuredClone(state),write:v=>{state=structuredClone(v);}};
  const empty=()=>({controller:[],receiver:[],legacy:[],ui:[]});
  class Handle extends EventEmitter {
    registerMethod() {}
    unregister() {this.unregistered=true;}
    subscribe(url,params) {
      assert.equal(url,'luna://com.webos.service.tvpower/power/getPowerState');
      assert.deepEqual(JSON.parse(params),{subscribe:true});
      const request=new EventEmitter();request.cancel=()=>{request.cancelled=true;};requests.push(request);return request;
    }
  }
  async function fire(delay) {
    const timer=[...scheduled].find(t=>t.delay===delay);assert(timer,'timer '+delay);
    scheduled.delete(timer);timer.fn();await flush();await flush();
  }
  try {
    const {handle}=createService({Handle,timers,startupStore:store,processReader:empty,
      preloaderFactory:()=>({prepare(){},filter:v=>v,activate:async()=>null,cancel:async()=>true}),
      startupFactory:()=>createStartup({store,boot:()=> '11111111-1111-1111-1111-111111111111',activity:()=>{}}),
      powerReader:{read:async()=>{reads++;return {state:power};},close(){readerClosed=true;}},
      controllerLauncher:async()=>{starts++;return {returnValue:true,status:'starting'};},processExit:()=>{exited=true;}});
    await fire(0);assert.equal(reads,1);assert.equal(starts,0);
    assert([...scheduled].some(t=>t.delay===2000));
    power='Active';requests[0].emit('response',{payload:()=>JSON.stringify({returnValue:true,subscribed:true,state:'Active'})});
    await flush();await fire(0);
    assert.equal(reads,2,'Notification causes a fresh read, not a cached-state launch');assert.equal(starts,0);
    await fire(150);assert.equal(reads,3);assert.equal(starts,1);
    requests[0].emit('response',{payload:()=>JSON.stringify({returnValue:true,subscribed:true,state:'Active'})});
    await flush();assert(![...scheduled].some(t=>t.delay===0));
    state.enabled=false;await fire(60000);
    assert(exited&&readerClosed&&handle.unregistered&&requests[0].cancelled);
    assert.equal(scheduled.size,0,'Closing the service also closes power hints and polling');
    console.log('Service power hint: notification to fresh read to confirmed single launch and complete shutdown passed');
  } finally {global.unified_service=false;}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
