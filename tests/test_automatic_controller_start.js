'use strict';
const assert = require('assert'), EventEmitter = require('events');
const {createService} = require('../src/integrated/service');
const empty = () => ({controller:[],receiver:[],legacy:[],ui:[]});
const flush = () => new Promise(resolve => setImmediate(resolve));
async function run(found, failure) {
  let dependencies, launches=0; const scheduled=[];
  class Handle extends EventEmitter {registerMethod() {} unregister() {}}
  try {
    createService({Handle, startupStore:{},
      startupFactory: () => ({summary:()=>({enabled:true}),poll:deps=>{dependencies=deps;}}),
      processReader:()=>{if(failure)throw Error('Incomplete process read');return found;},
      powerReader:{read:async()=>({state:'Active'}),close(){}},
      controllerLauncher:async()=>{launches++;return {returnValue:true,status:'starting'};},
      timers:{setTimeout(callback,delay){scheduled.push({callback,delay});return {};},clearTimeout(){}}});
    scheduled.find(x=>x.delay===0).callback(); await flush();
    if(failure) await assert.rejects(dependencies.start(),/Incomplete/);
    else {
      const result=await dependencies.start();
      assert.equal(result.returnValue,Object.values(found).every(v=>Array.isArray(v)&&!v.length));
    }
    return launches;
  } finally {global.unified_service=false;}
}
(async()=>{
  assert.equal(await run(empty()),1);
  for(const role of ['controller','receiver','legacy','ui']) {
    assert.equal(await run({...empty(),[role]:[{pid:123}]}),0);
    assert.equal(await run({...empty(),[role]:null}),0);
  }
  assert.equal(await run(empty(),true),0);
  console.log('Automatic controller: fresh conflict/incomplete-read rejection before direct launch passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
