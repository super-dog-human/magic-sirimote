'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto');
function publish(state,event){
 const allowed=['intent-reserved','created','finished','attention'];
 if(!event||!['provision','cancel','rearm'].includes(event.action)||!/^[a-f0-9]{32}$/.test(event.operationId||'')||!allowed.includes(event.stage)||typeof event.status!=='string'||!/^[a-z0-9-]{1,100}$/.test(event.status))throw Error('invalid-public-status');
 const value={schema:1,action:event.action,operationId:event.operationId,appId:'org.codex.siriremote.v20scheduler20261031a',stage:event.stage,status:event.status,activityAbsent:false,epochMs:Date.now()};
 if(Number.isSafeInteger(event.activityId)&&event.activityId>0)value.activityId=event.activityId;
 const tmp=path.join(state,'.public-status-'+process.pid+'-'+crypto.randomBytes(8).toString('hex'));
 const fd=fs.openSync(tmp,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o640);
 try{fs.fchmodSync(fd,0o640);fs.writeFileSync(fd,JSON.stringify(value)+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
 fs.renameSync(tmp,path.join(state,'public-status.json'));
 const d=fs.openSync(state,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);try{fs.fsyncSync(d);}finally{fs.closeSync(d);}
 return value;
}
module.exports={publish};
