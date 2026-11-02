'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto'),creator=require('./creator');
const EXPECTED='02549be061937a399c6527d2649a84a825d150951f2c065d92a1b55ac70923e5';
function hasRequest(state){return fs.existsSync(path.join(state,'maintenance-request.json'));}
function read(file,uid,max){const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);try{const s=fs.fstatSync(fd);if(!s.isFile()||s.nlink!==1||s.uid!==uid||s.gid!==5000||s.size>max)throw Error('maintenance-file-invalid');const b=fs.readFileSync(fd);if(b.length!==s.size)throw Error('maintenance-file-changed');return {bytes:b,stat:s,value:require('./strict-json').parseStrict(b.toString(),{maxBytes:max})};}finally{fs.closeSync(fd);}}
function write(file,value){const fd=fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o640);try{fs.fchmodSync(fd,0o640);fs.writeFileSync(fd,JSON.stringify(value)+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}const d=fs.openSync(path.dirname(file),'r');try{fs.fsyncSync(d);}finally{fs.closeSync(d);}}
async function run({state,Handle,now=Date.now}){
 const request=read(path.join(state,'maintenance-request.json'),5415,1024),q=request.value;
 if((request.stat.mode&0o777)!==0o640||Object.keys(q).sort().join(',')!=='action,activityId,appId,expiresEpochMs,nonce,schema'||q.schema!==1||q.appId!==creator.APP||q.activityId!==244||q.action!=='disarm'||!/^[a-f0-9]{32}$/.test(q.nonce||'')||!Number.isSafeInteger(q.expiresEpochMs)||q.expiresEpochMs<now()||q.expiresEpochMs>now()+300000)throw Error('maintenance-request-rejected');
 const old=read(path.join(state,'creator-private','created.json'),process.getuid(),8192);
 if(crypto.createHash('sha256').update(old.bytes).digest('hex')!==EXPECTED||old.value.activityId!==244||old.value.appId!==creator.APP||old.value.activityName!==creator.NAME)throw Error('maintenance-creator-mismatch');
 const claim=path.join(state,'maintenance-'+q.nonce+'-claim.json');
 // Reserve before dispatch; a duplicate launch cannot send the operation twice.
 write(claim,{schema:1,action:q.action,activityId:244,nonce:q.nonce});
 const H=Handle||require('palmbus').Handle;let handle;let result;
 try{handle=new H(creator.APP);const reply=await creator.call(handle,'luna://'+creator.SERVICE+'/disarm',{run:old.value.run,nonce:old.value.nonce,activityName:creator.NAME});result={schema:1,nonce:q.nonce,action:q.action,activityId:244,reply,status:reply&&reply.returnValue===true&&reply.status==='disarmed'?'disarmed':'unconfirmed'};}
 catch(e){result={schema:1,nonce:q.nonce,action:q.action,activityId:244,status:'unconfirmed',errorType:e.name};}
 finally{if(handle)handle.unregister();}
 write(path.join(state,'maintenance-'+q.nonce+'-result.json'),result);return result;
}
module.exports={hasRequest,run};
