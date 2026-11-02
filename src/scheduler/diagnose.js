'use strict';
// Explicit same-app diagnostic. No Activity, Bluetooth, input, or sensor calls.
const fs=require('fs'),path=require('path');
const APP='org.codex.siriremote.v20scheduler20261031a';
function hasRequest(state){return fs.existsSync(path.join(state,'diagnose-request.json'));}
function run({state,now=Date.now,verify,requestUid=5415,group=5000}){
 const file=path.join(state,'diagnose-request.json'),prior=fs.lstatSync(file);
 if(!prior.isFile()||prior.isSymbolicLink()||prior.nlink!==1||prior.uid!==requestUid||prior.gid!==group||(prior.mode&0o777)!==0o640||prior.size>1024)throw Error('diagnostic-request-invalid');
 const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);let q;
 try{const s=fs.fstatSync(fd);if(s.dev!==prior.dev||s.ino!==prior.ino||s.size!==prior.size)throw Error('request-changed');q=require('./strict-json').parseStrict(fs.readFileSync(fd,'utf8'));}finally{fs.closeSync(fd);}
 if(!q||Object.keys(q).sort().join(',')!=='appId,expiresEpochMs,nonce,schema'||q.schema!==1||q.appId!==APP||!/^[a-f0-9]{32}$/.test(q.nonce||'')||!Number.isSafeInteger(q.expiresEpochMs)||q.expiresEpochMs<now()||q.expiresEpochMs>now()+180000)throw Error('diagnostic-request-rejected');
 let pin='ok';try{verify();}catch(e){pin=(e&&e.code==='EACCES')?'permission-denied':'failed';}
 const d=path.join(state,'creator-private');let privateState='missing',hasProvisionIntent=null,hasCreated=null;
 try{const s=fs.lstatSync(d);if(!s.isDirectory()||s.isSymbolicLink()||s.uid!==process.getuid()||(s.mode&0o777)!==0o700)throw Error('private-dir-invalid');const names=fs.readdirSync(d);if(names.length>50)throw Error('too-many-entries');privateState='readable';hasProvisionIntent=names.includes('provision-intent.json');hasCreated=names.includes('created.json');}
 catch(e){if(e.code!=='ENOENT')privateState='unavailable';}
 const out={schema:1,appId:APP,nonce:q.nonce,pin,privateState,hasProvisionIntent,hasCreated,activityCalls:0};
 const name=path.join(state,'diagnose-result-'+q.nonce+'.json'),w=fs.openSync(name,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o640);
 try{fs.fchmodSync(w,0o640);fs.writeFileSync(w,JSON.stringify(out)+'\n');fs.fsyncSync(w);}finally{fs.closeSync(w);}
 const dfd=fs.openSync(state,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);try{fs.fsyncSync(dfd);}finally{fs.closeSync(dfd);}
 return out;
}
module.exports={hasRequest,run};
