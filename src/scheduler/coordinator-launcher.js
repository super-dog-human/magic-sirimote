'use strict';
const COORDINATOR='org.codex.siriremote.autocoord20261029v';
const {parseStrict}=require('./strict-json');
const URI='luna://com.webos.applicationManager/launch';
function createLauncher(handle,timers=globalThis,timeoutMs=10000){
 if(!handle||typeof handle.call!=='function'||!Number.isInteger(timeoutMs)||timeoutMs<1||timeoutMs>30000)throw Error('invalid launcher');
 let attempted=false;
 return {launch:async app=>{
  if(app!==COORDINATOR||attempted)throw Error('invalid or duplicate launch');attempted=true;
  return await new Promise(resolve=>{
   let done=false,timer;function finish(x){if(done)return;done=true;timers.clearTimeout(timer);resolve(x);}
   timer=timers.setTimeout(()=>finish('unknown'),timeoutMs);
   try{
    const req=handle.call(URI,JSON.stringify({id:COORDINATOR,params:{}}));
    if(!req||typeof req.addListener!=='function')throw Error('invalid request');
    req.addListener('response',m=>{try{
     const raw=m.payload();if(typeof raw!=='string'||Buffer.byteLength(raw,'utf8')>4096)throw Error('bad response');
     const r=parseStrict(raw);if(!r||typeof r!=='object'||Array.isArray(r)||typeof r.returnValue!=='boolean'||('id' in r&&r.id!==COORDINATOR))throw Error('bad response');
     finish(r.returnValue?'accepted':'rejected');
    }catch(_){finish('unknown');}});
   }catch(_){finish('unknown');}
  });
 }};
}
module.exports={createLauncher};
