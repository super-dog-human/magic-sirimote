'use strict';
const fs=require('fs'),path=require('path'),{parseStrict}=require('./strict-json'),creator=require('./creator');
function hasRequest(state){return fs.existsSync(path.join(state,'expiry-request.json'));}
function save(state,name,v){const fd=fs.openSync(path.join(state,name),fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o640);try{fs.fchmodSync(fd,0o640);fs.writeFileSync(fd,JSON.stringify(v)+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}}
async function run({state,Handle,now=Date.now,requestUid=5415,group=5000}={}){
 const fd=fs.openSync(path.join(state,'expiry-request.json'),fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);let q;
 try{const st=fs.fstatSync(fd);if(!st.isFile()||st.nlink!==1||st.uid!==requestUid||st.gid!==group||(st.mode&0o777)!==0o640||st.size>1024)throw Error('expiry-request-invalid');q=parseStrict(fs.readFileSync(fd,'utf8'));}finally{fs.closeSync(fd);}
 if(Object.keys(q).sort().join(',')!=='action,appId,expiresEpochMs,nonce,schema'||q.schema!==1||q.action!=='check-only'||q.appId!==creator.APP||!/^[a-f0-9]{32}$/.test(q.nonce||'')||!Number.isSafeInteger(q.expiresEpochMs)||q.expiresEpochMs<now()||q.expiresEpochMs>now()+180000)throw Error('expiry-request-invalid');
 save(state,'expiry-'+q.nonce+'-intent.json',{schema:1,nonce:q.nonce,action:'check-only'});
 let h,result;
 try{h=new (Handle||require('palmbus').Handle)(creator.APP);result=await new Promise(resolve=>{
  let done=false,req;const finish=v=>{if(done)return;done=true;clearTimeout(timer);try{if(req)req.cancel();}catch(_){}resolve(v);};const timer=setTimeout(()=>finish(null),18000);
  try{req=h.call('luna://'+creator.SERVICE+'/expiryCheck','{}');req.addListener('response',m=>{try{const raw=m.payload();if(typeof raw!=='string'||Buffer.byteLength(raw)>2048)throw Error();const r=parseStrict(raw);finish(r);}catch(_){finish(null);}});}catch(_){finish(null);}
 });}finally{if(h)h.unregister();}
 const out={schema:1,nonce:q.nonce,action:'check-only',uid:process.getuid(),result};save(state,'expiry-'+q.nonce+'-result.json',out);return out;
}
module.exports={hasRequest,run};
