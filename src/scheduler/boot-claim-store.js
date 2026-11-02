'use strict';
// Experimental durable startup claim. Missing volatile evidence alone never
// means reboot; incomplete state transitions suppress a retry.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const marker=require('./continuity-marker'),boot=require('./boot-evidence');
const APP_ID='org.codex.siriremote.autocoord20261029v';
function readBootIdentity(){return boot.captureStable();}
function createBootClaimStore(dir,getBootIdentity=readBootIdentity,{volatileRoot='/dev/shm'}={}){
 if(typeof dir!=='string'||!path.isAbsolute(dir)||typeof volatileRoot!=='string'||!path.isAbsolute(volatileRoot)||typeof getBootIdentity!=='function')throw Error('invalid-store-configuration');
 const owner=process.getuid(),root=fs.lstatSync(dir);
 if(!root.isDirectory()||root.isSymbolicLink()||root.uid!==owner||(root.mode&0o777)!==0o700)throw Error('invalid-store-directory');
 let active=null;
 function checkRoot(){const s=fs.lstatSync(dir);if(!s.isDirectory()||s.isSymbolicLink()||s.uid!==owner||(s.mode&0o777)!==0o700||s.dev!==root.dev||s.ino!==root.ino)throw Error('store-directory-changed');}
 function syncDir(){const fd=fs.openSync(dir,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);try{fs.fsyncSync(fd);}finally{fs.closeSync(fd);}}
 function exclusive(file,obj){checkRoot();const fd=fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);try{fs.fchmodSync(fd,0o600);fs.writeFileSync(fd,JSON.stringify(obj)+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}syncDir();}
 function read(file){checkRoot();const a=fs.lstatSync(file);if(!a.isFile()||a.isSymbolicLink()||a.nlink!==1||a.uid!==owner||(a.mode&0o777)!==0o600||a.size>2048)throw Error('invalid-state-file');const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);try{const b=fs.fstatSync(fd);if(a.dev!==b.dev||a.ino!==b.ino||a.size!==b.size)throw Error('state-replaced');const bytes=fs.readFileSync(fd,'utf8'),c=fs.fstatSync(fd);if(b.dev!==c.dev||b.ino!==c.ino||b.size!==c.size||b.mtimeMs!==c.mtimeMs||b.ctimeMs!==c.ctimeMs)throw Error('state-changed');const v=JSON.parse(bytes);if(JSON.stringify(v)+'\n'!==bytes)throw Error('noncanonical-state');return v;}finally{fs.closeSync(fd);}}
 function stateRead(){const x=read(path.join(dir,'epoch-state.json'));if(!x||Object.keys(x).sort().join(',')!=='marker,sample,schema'||x.schema!==1||!x.marker||Object.keys(x.marker).sort().join(',')!=='device,inode,token')throw Error('invalid-epoch-state');boot.validate(x.sample);return x;}
 function atomicState(state,expected){checkRoot();if(expected!==null&&JSON.stringify(stateRead())!==JSON.stringify(expected))throw Error('state-changed');const temp=path.join(dir,'epoch-next-'+crypto.randomBytes(16).toString('hex')+'.json');exclusive(temp,state);if(expected!==null&&JSON.stringify(stateRead())!==JSON.stringify(expected))throw Error('state-changed');fs.renameSync(temp,path.join(dir,'epoch-state.json'));syncDir();checkRoot();}
 function transact(fn){checkRoot();const lock=path.join(dir,'epoch-transition.lock');fs.mkdirSync(lock,{mode:0o700});const before=fs.lstatSync(lock);if(!before.isDirectory()||before.isSymbolicLink()||before.uid!==owner||(before.mode&0o777)!==0o700)throw Error('invalid-transition-lock');syncDir();try{if(fs.readdirSync(dir).some(n=>/^epoch-next-/.test(n)))throw Error('uncertain-state-transition');return fn();}finally{const after=fs.lstatSync(lock);if(before.dev!==after.dev||before.ino!==after.ino||after.uid!==owner)throw Error('transition-lock-changed');fs.rmdirSync(lock);syncDir();}}
 function current(){return boot.validate(getBootIdentity());}
 function createEpoch(sample){const token=crypto.randomBytes(16).toString('hex');return {schema:1,marker:marker.create(volatileRoot,token),sample};}
 function currentMarker(state){return marker.sameAs(volatileRoot,state.marker);}
 function intentPath(token){return path.join(dir,'epoch-launch-intent-'+token+'.json');}
 function outcomePath(token){return path.join(dir,'epoch-launch-outcome-'+token+'.json');}
 return {
  initialize(){return transact(()=>{try{stateRead();return false;}catch(e){if(e.code!=='ENOENT')throw e;}
   if(fs.readdirSync(dir).some(n=>/^boot-launch-(intent|outcome)-/.test(n)||/^epoch-launch-(intent|outcome)-/.test(n)||/^epoch-next-/.test(n)))throw Error('legacy-or-uncertain-claim');
   const state=createEpoch(current());exclusive(path.join(dir,'epoch-state.json'),state);return true;});},
  claim(appId){if(appId!==APP_ID)throw Error('launch-target-mismatch');return transact(()=>{
   let prior=stateRead(),now=current(),present=currentMarker(prior),next;
   if(present){if(now.bootId!==prior.sample.bootId||now.uptimeMs+1000<prior.sample.uptimeMs)throw Error('contradictory-session-evidence');next={...prior,sample:now};}
   else {const cmp=boot.compare(prior.sample,now);if(cmp.classification!=='new-boot-evidence')throw Error('boot-epoch-ambiguous');next=createEpoch(now);}
   if(JSON.stringify(next)!==JSON.stringify(prior))atomicState(next,prior);
   const record={schema:1,appId:APP_ID,token:next.marker.token,state:'intent'};
   try{exclusive(intentPath(next.marker.token),record);active={token:next.marker.token};return true;}
   catch(e){if(e.code!=='EEXIST')throw e;if(JSON.stringify(read(intentPath(next.marker.token)))!==JSON.stringify(record))throw Error('intent-mismatch');return false;}
  });},
  finish(status){if(!active||!['accepted','rejected','unknown'].includes(status))throw Error('invalid-launch-outcome');return transact(()=>{
   const state=stateRead(),now=current();if(state.marker.token!==active.token||!currentMarker(state)||now.bootId!==state.sample.bootId||now.uptimeMs+1000<state.sample.uptimeMs)throw Error('session-changed-during-launch');
   const intent=read(intentPath(active.token));if(JSON.stringify(intent)!==JSON.stringify({schema:1,appId:APP_ID,token:active.token,state:'intent'}))throw Error('intent-mismatch');
   exclusive(outcomePath(active.token),{schema:1,appId:APP_ID,token:active.token,status});active=null;return true;
  });}
 };
}
module.exports={APP_ID,readBootIdentity,createBootClaimStore};
