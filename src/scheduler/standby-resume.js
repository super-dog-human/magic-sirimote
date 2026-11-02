'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const APP='org.codex.siriremote.autocoord20261029v';
function valid(e){return e&&e.eligible===true&&/^[a-f0-9]{32}$/.test(e.run||'')&&/^[a-f0-9]{64}$/.test(e.fingerprint||'');}
function inspect(execFile=require('child_process').execFile){return new Promise(resolve=>{
 execFile('/usr/bin/python3',['-I','-B',path.join(__dirname,'resume-evidence.py')],{timeout:5000,maxBuffer:4096},(err,stdout)=>{
  if(err)return resolve({eligible:false,reason:'evidence-helper-unavailable'});
  try{const v=require('./strict-json').parseStrict(stdout,{maxBytes:4096});resolve(valid(v)?v:{eligible:false,reason:typeof v.reason==='string'?v.reason:'evidence-unavailable',component:v.component||null});}catch(_){resolve({eligible:false,reason:'evidence-unavailable'});}
 });
});}
function readNamedPower(handle,timers=globalThis){return new Promise(resolve=>{
 let req,done=false;const finish=v=>{if(done)return;done=true;timers.clearTimeout(timer);try{if(req)req.cancel();}catch(_){}resolve(v);};
 const timer=timers.setTimeout(()=>finish(null),4000);
 try{req=handle.call('luna://com.webos.service.tvpower/power/getPowerState','{"subscribe":false}');req.addListener('response',m=>{try{
  const raw=m.payload();if(typeof raw!=='string'||Buffer.byteLength(raw)>2048)throw Error();const v=require('./strict-json').parseStrict(raw);
  finish(v.returnValue===true&&typeof v.state==='string'?{state:v.state,processing:v.processing}:{state:'Unavailable',errorCode:v.errorCode,errorText:typeof v.errorText==='string'?v.errorText.slice(0,200):null});
 }catch(_){finish(null);}});}catch(_){finish(null);}
});}
async function readPower(handle,timers=globalThis,execFile=require('child_process').execFile){
 const named=await readNamedPower(handle,timers);if(named&&named.state!=='Unavailable')return named;
 const native=await new Promise(resolve=>execFile('/usr/bin/python3',['-I','-B',path.join(__dirname,'power-read.py')],{timeout:5000,maxBuffer:2048},(error,stdout)=>{try{if(error)throw error;const v=require('./strict-json').parseStrict(stdout);resolve(v&&typeof v.state==='string'?v:null);}catch(_){resolve(null);}}));
 return native||named;
}
function claim(root,e){
 const s=fs.lstatSync(root);if(!s.isDirectory()||s.isSymbolicLink()||s.uid!==process.getuid()||(s.mode&0o777)!==0o700)throw Error('resume-root-invalid');
 const file=path.join(root,'resume-intent-'+e.run+'.json');let fd;
 try{fd=fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);}catch(error){if(error.code==='EEXIST')return false;throw error;}
 try{fs.fchmodSync(fd,0o600);fs.writeFileSync(fd,JSON.stringify({schema:1,appId:APP,run:e.run,fingerprint:e.fingerprint})+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
 const d=fs.openSync(root,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);try{fs.fsyncSync(d);}finally{fs.closeSync(d);}return true;
}
function finish(root,e,outcome){const file=path.join(root,'resume-outcome-'+e.run+'.json'),fd=fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);try{fs.fchmodSync(fd,0o600);fs.writeFileSync(fd,JSON.stringify({schema:1,run:e.run,outcome})+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}const d=fs.openSync(root,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);try{fs.fsyncSync(d);}finally{fs.closeSync(d);}}
function publish(value,state){
 // Diagnostic only: no callbacks, credentials or input data are written.

 try{const v={schema:1,epochMs:Date.now(),status:value.status,reason:value.reason||null,run:value.run||null};
  const temp=path.join(state,'.resume-status-'+crypto.randomBytes(8).toString('hex'));const fd=fs.openSync(temp,'wx',0o600);
  try{fs.fchmodSync(fd,0o600);fs.writeFileSync(fd,JSON.stringify(v)+'\n');}finally{fs.closeSync(fd);}fs.renameSync(temp,path.join(state,'resume-status.json'));
 }catch(_){}
}
async function run({root,handle,launch,verify=require('./creator').verifyPins,evidence=inspect,power=()=>readPower(handle),reserve=e=>claim(root,e),save=(e,r)=>finish(root,e,r),report=value=>publish(value,root)}={}){
 const done=v=>{report(v);return v;};
 try{
  const before=await evidence();if(!valid(before))return done({status:'already-claimed',reason:before&&before.reason||'not-eligible'});
  const p=await power();if(!p||p.state!=='Active'||(p.processing!==undefined&&p.processing!==''))return done({status:'already-claimed',reason:p?'power-not-active':'power-unavailable',run:before.run});
  verify();const after=await evidence();if(!valid(after)||after.run!==before.run||after.fingerprint!==before.fingerprint)return done({status:'already-claimed',reason:'evidence-changed'});
  if(!reserve(after))return done({status:'already-claimed',reason:'resume-already-attempted',run:after.run});
  const outcome=await launch(APP);save(after,outcome);
  return done({status:outcome==='accepted'?'launch-accepted':'launch-uncertain',reason:'standby-resume',run:after.run});
 }catch(_){return done({status:'resume-unconfirmed',reason:'retain-state-no-retry'});}
}
module.exports={run,inspect,readPower,readNamedPower,claim,finish,valid};
