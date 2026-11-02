'use strict';
// No scheduling, persistent writes, process launches or device I/O on import.
const fs = require('fs');
const path = require('path');
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
function validate(s) {
 if (!s || typeof s !== 'object' || Array.isArray(s) || typeof s.bootId !== 'string' || !UUID.test(s.bootId) ||
     !Number.isSafeInteger(s.btime) || s.btime < 1 || !Number.isSafeInteger(s.uptimeMs) || s.uptimeMs < 0) throw Error('invalid-boot-evidence');
 return {bootId:s.bootId,btime:s.btime,uptimeMs:s.uptimeMs};
}
function readSample(read=fs.readFileSync, root='/proc') {
 const bootId=String(read(path.join(root,'sys/kernel/random/boot_id'),'utf8')).trim().toLowerCase();
 const stat=String(read(path.join(root,'stat'),'utf8'));
 const bt=/^btime\s+(\d+)\s*$/m.exec(stat);
 const uptime=String(read(path.join(root,'uptime'),'utf8')).trim();
 const up=/^(\d+)(?:\.(\d{1,3}))?\s+\d+(?:\.\d+)?$/.exec(uptime);
 if(!bt||!up)throw Error('invalid-proc-boot-data');
 const seconds=Number(up[1]), milliseconds=Number((up[2]||'').padEnd(3,'0'));
 if(!Number.isSafeInteger(seconds)||seconds>Math.floor((Number.MAX_SAFE_INTEGER-milliseconds)/1000))throw Error('invalid-proc-uptime');
 return validate({bootId,btime:Number(bt[1]),uptimeMs:seconds*1000+milliseconds});
}
function captureStable(read=fs.readFileSync,root='/proc') {
 const first=readSample(read,root),second=readSample(read,root);
 if(first.bootId!==second.bootId||first.btime!==second.btime||second.uptimeMs<first.uptimeMs||second.uptimeMs-first.uptimeMs>3000)throw Error('unstable-boot-evidence');
 return second;
}
// Any ambiguous comparison forbids an automatic second launch. A decreasing
// uptime is evidence of a restart only when both snapshots address the same
// physical TV and the same kernel procfs, which callers must establish.
function compare(previous,current) {
 const a=validate(previous),b=validate(current);
 if(a.bootId!==b.bootId)return {classification:'new-boot-evidence',reason:'boot-id-changed'};
 if(b.uptimeMs+1000<a.uptimeMs)return {classification:'new-boot-evidence',reason:'uptime-decreased'};
 return {classification:'same-or-ambiguous',reason:b.btime===a.btime?'no-new-boot-evidence':'wall-clock-or-reboot-ambiguous'};
}
function decideLaunch(previous,current,{freshInstallVerified=false}={}) {
 validate(current);
 if(previous===null)return freshInstallVerified===true
  ? {allow:true,reason:'verified-fresh-install'}
  : {allow:false,reason:'missing-prior-claim'};
 const result=compare(previous,current);
 return {allow:result.classification==='new-boot-evidence',reason:result.reason};
}
module.exports={validate,readSample,captureStable,compare,decideLaunch};
