'use strict';
const assert = require('assert'), cp = require('child_process'), EventEmitter = require('events');
const {createService} = require('../src/integrated/service');
const {createStartup, APP} = require('../src/integrated/startup');
const flush = () => new Promise(resolve => setImmediate(resolve));
async function runCase(enabled, phase, expectStart) {
  const scheduled = [], helpers = [], activityCalls = [], launches = [];
  const original = cp.execFile;
  let state = {schema:1, token:'a'.repeat(48), enabled, phase, activityId:17};
  const store = {read:()=>JSON.parse(JSON.stringify(state)), write:s=>{state=JSON.parse(JSON.stringify(s));}};
  class Handle extends EventEmitter { registerMethod() {} unregister() {} }
  cp.execFile = (_command,args,_options,callback) => {
    const power = args[2].endsWith('/power-read.py');
    if (!power) helpers.push(args[3]);
    const reply = power ? {state:'Active'} : args[3]==='status'
      ? {returnValue:true,processes:{controller:[],receiver:[],ui:[],legacy:[]}}
      : {returnValue:true,status:'already-running'};
    setImmediate(()=>callback(null,JSON.stringify(reply)));
    return {stdin:{on(){},end(){}}};
  };
  try {
    const {handle} = createService({Handle, controllerLauncher: async () => { launches.push('start'); return {returnValue:true,status:'starting'}; }, powerReader: {read: async () => ({state: 'Active'}), close() {}}, startupStore:store,
      processReader:()=>({controller:[],receiver:[],ui:[],legacy:[]}),
      startupFactory:()=>createStartup({store,boot:()=> '11111111-1111-1111-1111-111111111111',
        token:()=> 'b'.repeat(48),activity:async method=>{
          activityCalls.push(method);
          if(method==='adopt') return {value:{returnValue:true,adopted:true},request:{cancel(){}}};
          assert.equal(method,'complete'); return {value:{returnValue:true}};
        }}),timers:{setTimeout(callback,delay){scheduled.push({callback,delay});return {};},clearTimeout(){}}});
    const request = (method,sender,params={})=>new Promise(resolve=>handle.emit('request',{
      method:()=>method,category:()=> '/',isSubscription:()=>false,payload:()=>JSON.stringify(params),
      senderServiceName:()=>sender,applicationID:()=>APP,respond:raw=>resolve(JSON.parse(raw))}));
    const before = JSON.stringify(state);
    assert.equal((await request('preview','other.app')).returnValue,false);
    assert.equal((await request('preview','com.webos.service.contentminer',[])).returnValue,false);
    assert.equal((await request('preview','com.webos.service.contentminer',{request:'preview'})).returnValue,true);
    assert.equal(JSON.stringify(state),before,'Preview does not change saved startup state');
    assert.equal(helpers.length,0,'Preview does not launch a separate helper');
    scheduled.find(t=>t.delay===0).callback();
    for(let i=0;i<15;i++) await flush();
    const confirm=scheduled.find(t=>t.delay===150);
    if(confirm) {confirm.callback();for(let i=0;i<15;i++) await flush();}
    assert.equal(launches.length,expectStart?1:0);
    assert.deepEqual(activityCalls,[],'Early startup does not wait for Activity Manager');
    assert.deepEqual(helpers,[],'Automatic launch does not spawn the separate preflight helper');
    assert.equal(state.enabled,enabled,'Preview cannot re-enable a maintenance stop');
    if(expectStart) {
      const attempt=state.attempt;
      assert(attempt);
      assert.equal((await request('startupTick','com.webos.service.activitymanager',
        {token:state.token,$activity:{activityId:17}})).returnValue,true);
      assert.deepEqual(activityCalls,['adopt','complete']);
      assert.equal(state.phase,'ready');assert.equal(state.attempt,attempt);
      assert.equal(launches.length,1,'Later fallback callback must not start a second controller');
      await request('preview','com.webos.service.contentminer');
      assert.equal(state.attempt,attempt,'Repeated previews do not reset the start attempt');
      assert.equal(launches.length,1);
    }
  } finally {cp.execFile=original;global.unified_service=false;}
}
(async()=>{
  await runCase(true,'ready',true);
  await runCase(false,'ready',false);
  await runCase(true,'attention',false);
  await runCase(true,'completing',false);
  await runCase(true,'prepared',false);
  console.log('Preview startup: non-root trigger, no Activity dependency, no duplicate start, maintenance and uncertain-state guards preserved');
})().catch(error=>{console.error(error);process.exitCode=1;});
