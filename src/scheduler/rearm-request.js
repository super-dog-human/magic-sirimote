'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto'),creator=require('./creator'),{parseStrict}=require('./strict-json'),{rearm,validPrior}=require('./rearm');
const REQUEST='rearm-request.json',hex=/^[a-f0-9]{32}$/;
function hasRequest(state){return fs.existsSync(path.join(state,REQUEST));}
function read(file,uid,max,group=5000){
 const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
 try{const st=fs.fstatSync(fd);if(!st.isFile()||st.nlink!==1||st.uid!==uid||st.gid!==group||st.size>max)throw Error('rearm-file-invalid');const bytes=fs.readFileSync(fd);if(bytes.length!==st.size)throw Error('rearm-file-changed');return {st,bytes,value:parseStrict(bytes.toString(),{maxBytes:max})};}
 finally{fs.closeSync(fd);}
}
function readPrior(state,q,uid,group=5000){
 if(!/^(?:creator-private|rearm-[a-f0-9]{32})\/created\.json$/.test(q.priorCreated||''))throw Error('rearm-prior-path-invalid');
 const dir=path.join(state,path.dirname(q.priorCreated)),st=fs.lstatSync(dir);
 if(!st.isDirectory()||st.isSymbolicLink()||st.uid!==uid)throw Error('rearm-prior-directory-invalid');
 const old=read(path.join(state,q.priorCreated),uid,8192,group);
 // This exact original receipt may have mode 0775 after the TV's developer
 // mode boot processing. Preserve it unchanged and require its known hash.
 if(crypto.createHash('sha256').update(old.bytes).digest('hex')!==q.priorCreatedSha256||!validPrior(old.value))throw Error('rearm-prior-hash-or-binding-invalid');
 return old.value;
}
async function run({state,Handle,now=Date.now,verify=creator.verifyPins,requestUid=5415,ownerUid=process.getuid(),group=5000,report=()=>{},random}={}){
 const request=read(path.join(state,REQUEST),requestUid,1536,group),q=request.value;
 if((request.st.mode&0o777)!==0o640||!q||Object.keys(q).sort().join(',')!=='action,appId,expiresEpochMs,operationId,priorCreated,priorCreatedSha256,schema'||q.schema!==1||q.action!=='rearm'||q.appId!==creator.APP||!hex.test(q.operationId||'')||!/^[a-f0-9]{64}$/.test(q.priorCreatedSha256||'')||!Number.isSafeInteger(q.expiresEpochMs)||q.expiresEpochMs<now()||q.expiresEpochMs>now()+300000)throw Error('rearm-request-invalid');
 const prior=readPrior(state,q,ownerUid,group);verify();
 // Share the original creator lock with provision/cancel. A previously
 // running cancel must not remove the newly created Activity after rearm.
 const coordinator=path.join(state,'creator-private'),parent=fs.lstatSync(coordinator);
 if(!parent.isDirectory()||parent.isSymbolicLink()||parent.uid!==ownerUid)throw Error('rearm-coordinator-invalid');
 const lock=path.join(coordinator,'operation-lock');fs.mkdirSync(lock,{mode:0o700});
 let handle;
 try{
  const dir=path.join(state,'rearm-'+q.operationId);
  require('./private-directory').ensurePrivateDirectory(dir,fs,true);
  creator.journal(dir).write('request-accepted.json',{schema:1,operationId:q.operationId,requestSha256:crypto.createHash('sha256').update(request.bytes).digest('hex')});
  const H=Handle||require('palmbus').Handle;handle=new H(creator.APP);
  return await rearm({handle,stateDir:dir,prior,intent:true,verify,now,random,report:event=>report({...event,operationId:q.operationId})});
 }finally{try{if(handle)handle.unregister();}finally{fs.rmdirSync(lock);}}
}
module.exports={hasRequest,run,readPrior};
