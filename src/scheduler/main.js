'use strict';
const fs=require('fs'),path=require('path'),{parseStrict}=require('./strict-json'),creator=require('./creator');
const STATE='/media/developer/apps/usr/palm/applications/'+creator.APP+'/state';
async function main({state=STATE,Handle,now=Date.now,verify=creator.verifyPins,automaticResume=false}={}){
 if(automaticResume)require('./native-checker').report(state,{status:'native-entry'});
 const expiry=require('./expiry-request');
 if(expiry.hasRequest(state))return expiry.run({state,Handle,now});
 let handle;
 const rearm=require('./rearm-request');
 if(rearm.hasRequest(state))return rearm.run({state,Handle,now,verify,report:event=>require('./public-status').publish(state,{...event,action:'rearm'})});
 const maintenance=require('./maintenance');
 if(maintenance.hasRequest(state))return maintenance.run({state,Handle,now});
 const diagnostic=require('./diagnose');
 if(diagnostic.hasRequest(state))return diagnostic.run({state,now,verify});
 const file=path.join(state,'intentional-action.json');
 if(!fs.existsSync(file))return automaticResume?require('./native-checker').run({state,Handle,verify}):{status:'disabled'};
 const st=fs.lstatSync(file);
 if(!st.isFile()||st.isSymbolicLink()||st.uid!==5415||st.gid!==5000||(st.mode&0o777)!==0o640||st.size>1024)throw Error('initial-installer-action-invalid');
 const q=parseStrict(fs.readFileSync(file,'utf8'));
 if(!/^[a-f0-9]{32}$/.test(q.operationId||'')||q.appId!==creator.APP||!['provision','cancel'].includes(q.action)||q.experimentalIntent!=='enable-experimental-tv-local-startup'||!Number.isSafeInteger(q.expiresEpochMs)||q.expiresEpochMs<now()||q.expiresEpochMs>now()+300000)throw Error('intentional-action-expired-or-invalid');
 const report=event=>require('./public-status').publish(state,{...event,action:q.action,operationId:q.operationId});
 const privateDir=path.join(state,'creator-private');
 require('./private-directory').ensurePrivateDirectory(privateDir);
 if(q.action==='provision')verify();
 const H=Handle||require('palmbus').Handle;handle=new H(creator.APP);
 try{return await creator[q.action]({handle,stateDir:privateDir,intent:true,verify,now,report});}
 catch(e){report({stage:'attention',status:'local-error-possibly-dispatched'});throw e;}
 finally{handle.unregister();}
}
if(require.main===module)main({automaticResume:true}).then(x=>console.log(JSON.stringify(x))).catch(e=>{console.error(e.message);process.exitCode=2});
module.exports={main};
