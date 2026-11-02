'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto');
function report(root,value){try{const temp=path.join(root,'.wake-status-'+crypto.randomBytes(8).toString('hex'));const fd=fs.openSync(temp,'wx',0o600);try{fs.fchmodSync(fd,0o600);fs.writeFileSync(fd,JSON.stringify({schema:1,epochMs:Date.now(),...value})+'\n');}finally{fs.closeSync(fd);}fs.renameSync(temp,path.join(root,'wake-status.json'));}catch(_){}return value;}
const APP='org.codex.siriremote.v20scheduler20261031a';
async function run({root,handle,timers=globalThis,power=()=>require('./standby-resume').readPower(handle,timers),launch}={}){
 const p=await power();if(!p||p.state!=='Active'||(p.processing!==undefined&&p.processing!==''))return report(root,{status:'already-claimed',reason:p?'power-not-active':'power-unavailable',power:p});
 const request=launch||(()=>new Promise(resolve=>{
  let done=false,req;const finish=r=>{if(done)return;done=true;timers.clearTimeout(timer);try{if(req)req.cancel();}catch(_){}resolve(r);};
  const timer=timers.setTimeout(()=>finish('unknown'),8000);
  try{req=handle.call('luna://com.webos.applicationManager/launch',JSON.stringify({id:APP,params:{}}));req.addListener('response',m=>{try{const raw=m.payload();if(typeof raw!=='string'||Buffer.byteLength(raw)>2048)throw Error();const v=require('./strict-json').parseStrict(raw);finish(v.returnValue===true?'accepted':'unknown');}catch(_){finish('unknown');}});}catch(_){finish('unknown');}
 }));
 const result=await request(APP);return report(root,{status:'already-claimed',reason:result==='accepted'?'native-check-requested':'native-check-launch-unconfirmed',power:p});
}
module.exports={run};
