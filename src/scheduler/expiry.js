'use strict';
// Fixed official extension endpoint. No raw credential or response is persisted.
const fs=require('fs'),path=require('path');
const {parseStrict}=require('./strict-json');
const {ensurePrivateDirectory}=require('./private-directory');
const DAY=86400000,THRESHOLD=14*86400,MAX_SECONDS=1000*3600;
function readOfficial(){return new Promise(resolve=>{
 require('child_process').execFile('/usr/bin/python3',['-I','-B',path.join(__dirname,'expiry-query.py')],{timeout:12000,maxBuffer:4096},(err,stdout)=>{
  if(err){resolve(null);return;}
  try{const v=parseStrict(stdout);resolve(v.timeVerified===true&&Number.isSafeInteger(v.remainingSeconds)&&v.remainingSeconds>=0&&v.remainingSeconds<=MAX_SECONDS?{remainingSeconds:v.remainingSeconds}:null);}catch(_){resolve(null);}
 });
});}
function launchOfficial(handle,timers=globalThis){return new Promise(resolve=>{
 let done=false,request;
 const finish=status=>{if(done)return;done=true;timers.clearTimeout(timer);try{if(request)request.cancel();}catch(_){}resolve(status);};
 const timer=timers.setTimeout(()=>finish('unconfirmed'),10000);
 try{request=handle.call('luna://com.webos.applicationManager/launch',JSON.stringify({id:'com.palmdts.devmode',params:{extend:true},subscribe:false}));
  request.addListener('response',m=>{try{const raw=m.payload();if(typeof raw!=='string'||Buffer.byteLength(raw)>8192)throw Error();const v=parseStrict(raw);finish(v.returnValue===true&&(!('id'in v)||v.id==='com.palmdts.devmode')&&(!('appId'in v)||v.appId==='com.palmdts.devmode')?'acknowledged':v.returnValue===false?'rejected':'unconfirmed');}catch(_){finish('unconfirmed');}});
 }catch(_){finish('unconfirmed');}
});}
function createStore(root){
 ensurePrivateDirectory(root);const file=path.join(root,'state.json');
 function read(){
  let fd;try{fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);}catch(e){if(e.code==='ENOENT')return {schema:1,lastCheckMs:0,nextCheckMs:0,lastAttemptMs:0,pending:null,status:'new'};throw e;}
  try{const st=fs.fstatSync(fd);if(!st.isFile()||st.nlink!==1||st.uid!==process.getuid()||(st.mode&0o777)!==0o600||st.size>4096)throw Error('expiry-state-invalid');const b=fs.readFileSync(fd);if(b.length!==st.size)throw Error();const s=parseStrict(b.toString());
   if(s.schema!==1||!['lastCheckMs','nextCheckMs','lastAttemptMs'].every(k=>Number.isSafeInteger(s[k])&&s[k]>=0)||typeof s.status!=='string'||s.pending!==null&&(!Number.isSafeInteger(s.pending.atMs)||s.pending.atMs<0||!Number.isSafeInteger(s.pending.beforeSeconds)||s.pending.beforeSeconds<1||s.pending.beforeSeconds>THRESHOLD))throw Error('expiry-state-invalid');return s;
  }finally{fs.closeSync(fd);}
 }
 function write(s){const tmp=path.join(root,'state.next.json'),fd=fs.openSync(tmp,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);
  try{fs.fchmodSync(fd,0o600);fs.writeFileSync(fd,JSON.stringify(s)+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
  fs.renameSync(tmp,file);const d=fs.openSync(root,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);try{fs.fsyncSync(d);}finally{fs.closeSync(d);}
 }
 return {read,write,lock(){fs.mkdirSync(path.join(root,'lock'),{mode:0o700});},unlock(){fs.rmdirSync(path.join(root,'lock'));}};
}
async function run({root,handle,query=readOfficial,launch=()=>launchOfficial(handle),now=Date.now,wait=ms=>new Promise(r=>setTimeout(r,ms)),allowExtension=true,forceRead=false}={}){
 let disk,locked=false;
 try{
  disk=createStore(root);disk.lock();locked=true;
  let s=disk.read();const at=now();
  if(!Number.isSafeInteger(at)||at<Date.UTC(2024,0,1)||at<s.lastCheckMs||at<s.lastAttemptMs)return {status:'clock-untrusted'};
  if(!forceRead&&at<s.nextCheckMs)return {status:'not-due',nextCheckMs:s.nextCheckMs};
  // Persist the next allowed query first; a restart cannot flood the server.
  s={...s,lastCheckMs:at,nextCheckMs:at+6*3600000,status:'query-pending'};disk.write(s);
  let v;try{v=await query();}catch(_){v=null;}
  const valid=v=>v&&Number.isSafeInteger(v.remainingSeconds)&&v.remainingSeconds>=0&&v.remainingSeconds<=MAX_SECONDS;
  if(!valid(v)){s.status='query-unconfirmed';disk.write(s);return {status:s.status};}
  s.remainingSeconds=v.remainingSeconds;s.nextCheckMs=at+DAY;
  if(s.pending){
   const expected=Math.max(0,s.pending.beforeSeconds-Math.floor((at-s.pending.atMs)/1000));
   if(v.remainingSeconds>expected+60){s.pending=null;s.lastVerifiedMs=at;s.status='renewal-verified';}
   else s.status='extension-unconfirmed-no-retry';
   disk.write(s);return {status:s.status,remainingSeconds:v.remainingSeconds};
  }
  if(v.remainingSeconds===0){s.status='expired';disk.write(s);return {status:s.status,remainingSeconds:0};}
  if(v.remainingSeconds>THRESHOLD||!allowExtension){s.status=v.remainingSeconds>THRESHOLD?'time-sufficient':'due-read-only';disk.write(s);return {status:s.status,remainingSeconds:v.remainingSeconds};}
  if(at-s.lastAttemptMs<DAY){s.status='attempt-throttled';disk.write(s);return {status:s.status};}
  // Durable uncertainty marker precedes dispatch. It is never silently cleared.
  s.pending={atMs:at,beforeSeconds:v.remainingSeconds};s.lastAttemptMs=at;s.status='extension-pending';disk.write(s);
  let ack;try{ack=await launch();}catch(_){ack='unconfirmed';}
  s.lastLaunchStatus=['acknowledged','rejected','unconfirmed'].includes(ack)?ack:'unconfirmed';disk.write(s);
  await wait(3000);
  let after;try{after=await query();}catch(_){after=null;}
  if(valid(after)&&after.remainingSeconds>v.remainingSeconds+60){s.pending=null;s.remainingSeconds=after.remainingSeconds;s.lastVerifiedMs=now();s.status='renewal-verified';}
  else s.status='extension-unconfirmed-no-retry';
  disk.write(s);return {status:s.status,remainingSeconds:s.remainingSeconds,launchStatus:s.lastLaunchStatus};
 }catch(_){return {status:'local-state-attention'};}
 finally{if(locked)try{disk.unlock();}catch(_){}}
}
module.exports={run,readOfficial,launchOfficial,createStore,DAY,THRESHOLD};
