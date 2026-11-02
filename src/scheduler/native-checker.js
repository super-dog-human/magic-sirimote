'use strict';
// Runs in the existing native app, whose LG mount namespace exposes A/B state.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const APP='org.codex.siriremote.v20scheduler20261031a';
function call(handle,payload,timers=globalThis){return new Promise(resolve=>{
 let req,done=false;const finish=r=>{if(done)return;done=true;timers.clearTimeout(timer);try{if(req)req.cancel();}catch(_){}resolve(r);};
 const timer=timers.setTimeout(()=>finish({status:'resume-response-unconfirmed'}),15000);
 try{req=handle.call('luna://'+APP+'.service/resumeVerified',JSON.stringify(payload));req.addListener('response',m=>{try{const raw=m.payload();if(typeof raw!=='string'||Buffer.byteLength(raw)>2048)throw Error();finish(require('./strict-json').parseStrict(raw));}catch(_){finish({status:'resume-response-unconfirmed'});}});}catch(_){finish({status:'resume-response-unconfirmed'});}
});}
function report(state,r){try{
 const target=path.join(state,'native-resume-status.json'),temp=path.join(state,'.native-resume-'+crypto.randomBytes(8).toString('hex'));
 const fd=fs.openSync(temp,'wx',0o640);try{fs.fchmodSync(fd,0o640);fs.writeFileSync(fd,JSON.stringify({schema:1,epochMs:Date.now(),status:r.status,reason:r.reason||null,run:r.run||null})+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}fs.renameSync(temp,target);
}catch(_){}return r;}
async function run({state,Handle,verify=require('./creator').verifyPins,evidence=require('./standby-resume').inspect,request=call,write=report}={}){
 let handle;const done=r=>write(state,r);
 try{
  const a=await evidence();if(!require('./standby-resume').valid(a))return done({status:'not-eligible',reason:a.reason||'evidence-unavailable'});
  verify();const b=await evidence();if(!require('./standby-resume').valid(b)||b.run!==a.run||b.fingerprint!==a.fingerprint)return done({status:'not-eligible',reason:'evidence-changed'});
  const H=Handle||require('palmbus').Handle;handle=new H(APP);
  const r=await request(handle,{eligible:true,run:b.run,fingerprint:b.fingerprint});return done({...r,run:b.run});
 }catch(error){return done({status:'native-check-unconfirmed',reason:error&&error.code==='EACCES'?'permission-denied':'verification-unavailable'});}
 finally{if(handle)handle.unregister();}
}
module.exports={run,call,report};
