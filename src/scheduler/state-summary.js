'use strict';
// Narrow read-only diagnostic: never exposes binding tokens or callback params.
const fs=require('fs'),path=require('path');
function read(root){
 const ds=fs.lstatSync(root);if(!ds.isDirectory()||ds.isSymbolicLink()||ds.uid!==process.getuid()||(ds.mode&511)!==448)throw Error('root');
 function record(file){const s=fs.lstatSync(file);if(!s.isFile()||s.isSymbolicLink()||s.nlink!==1||s.uid!==process.getuid()||(s.mode&511)!==384||s.size>4096)throw Error('record');return {v:require('./strict-json').parseStrict(fs.readFileSync(file,'utf8')),mtimeMs:s.mtimeMs};}
 const names=fs.readdirSync(root);if(names.length>1024)throw Error('bound');
 const out={schema:1,epochMs:Date.now(),bindings:[],resumeAttempts:names.filter(n=>/^resume-intent-[a-f0-9]{32}\.json$/.test(n)).length};
 for(const n of names){if(!/^[a-f0-9]{32}$/.test(n))continue;const dir=path.join(root,n),s=fs.lstatSync(dir);if(!s.isDirectory()||s.isSymbolicLink()||s.uid!==process.getuid()||(s.mode&511)!==448)continue;
  const row={run:n};try{const b=record(path.join(dir,'binding.bound.json')).v;row.activityId=b.activityId;row.disabled=fs.existsSync(path.join(dir,'disabled.json'));const r=record(path.join(dir,'rotation-state.json'));row.phase=r.v.phase;row.rotationMtimeMs=r.mtimeMs;row.pendingSchedule=r.v.schedule||null;row.lock=fs.existsSync(path.join(dir,'rotation.lock'));row.temp=fs.existsSync(path.join(dir,'rotation-state.tmp'));}catch(_){row.unavailable=true;}out.bindings.push(row);
 }
 try{const e=record(path.join(root,'epoch-state.json'));out.boot={sample:e.v.sample,mtimeMs:e.mtimeMs};}catch(_){out.boot=null;}
 try{out.resumeStatus=record(path.join(root,'resume-status.json')).v;}catch(_){out.resumeStatus=null;}
 try{out.wakeStatus=record(path.join(root,'wake-status.json')).v;}catch(_){out.wakeStatus=null;}
 try{out.transportStatus=record(path.join(root,'transport-status.json')).v;}catch(_){out.transportStatus=null;}
 return out;
}
module.exports={read};
