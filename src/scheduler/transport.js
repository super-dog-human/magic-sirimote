'use strict';
// Offline transport adapter. Holds an adoption subscription until the owner
// explicitly closes it following a confirmed completion/release.
const URI='luna://com.webos.service.activitymanager/';
function createTransport(handle,parse,timers,timeoutMs,trace=()=>{}){
 if(!handle||typeof handle.call!=='function'||typeof handle.subscribe!=='function'||typeof parse!=='function'||!timers||!Number.isInteger(timeoutMs)||timeoutMs<1||timeoutMs>30000)throw Error('invalid-transport');
 let lease=null,uncertain=false,cleanupUnconfirmed=false;
 const mark=name=>{try{trace(name);}catch(_){}};
 function call(method,payload,subscribe){
  if(uncertain)return Promise.resolve(null);
  return new Promise(resolve=>{
   let done=false,request;
   const finish=x=>{if(done)return;done=true;timers.clearTimeout(timer);resolve(x);};
   const timer=timers.setTimeout(()=>{mark(method+'-timeout');uncertain=true;finish(null);},timeoutMs);
   try{
    request=(subscribe?handle.subscribe:handle.call).call(handle,URI+method,JSON.stringify(payload));
    if(!request||typeof request.addListener!=='function')throw Error('invalid-request');
    if(subscribe)lease=request;
    request.addListener('response',m=>{
     if(done)return;
     try{
      const text=m.payload();if(typeof text!=='string'||Buffer.byteLength(text,'utf8')>4096)throw Error('invalid-response');
      const p=parse(text);if(!p||typeof p!=='object'||Array.isArray(p)||typeof p.returnValue!=='boolean')throw Error('invalid-response');
      if(subscribe&&p.returnValue===true&&p.adopted!==true){if(p.subscribed===false){mark(method+'-malformed');uncertain=true;finish(null);}else mark(method+'-pending');return;}
      if(subscribe&&p.returnValue===false&&!closeLease()){finish(null);return;}
      mark(method+(p.returnValue===true?'-ok':'-denied'));
      finish(p);
     }catch(_){mark(method+'-malformed');uncertain=true;finish(null);}
    });
   }catch(_){mark(method+'-error');uncertain=true;finish(null);}
  });
 }
 function closeLease(acknowledged=false){
  if(!lease)return true;
  try{if(typeof lease.cancel!=='function'||lease.cancel()===false)throw Error('cancel-unconfirmed');lease=null;return true;}
  catch(_){if(acknowledged){lease=null;cleanupUnconfirmed=true;mark('lease-cleanup-unconfirmed');return true;}uncertain=true;return false;}
 }
 return {
  adopt:id=>{if(lease)throw Error('lease-exists');return call('adopt',{activityId:id,subscribe:true,wait:false},true);},
  complete:async payload=>{const r=await call('complete',payload,false);if(r&&r.returnValue===true&&!closeLease(true))return null;return r;},
  release:async id=>{const r=await call('release',{activityId:id},false);if(r&&r.returnValue===true&&!closeLease(true))return null;return r;},
  snapshot:()=>({leaseHeld:!!lease,uncertain,cleanupUnconfirmed})
 };
}
module.exports={createTransport};
