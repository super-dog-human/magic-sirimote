"use strict";
const fs=require('fs'),path=require('path');
const {parseStrict}=require('./strict-json');
const TOKEN=/^[a-f0-9]{48}$/;
// Exclusive, trusted 0700 directory; all writers must use this protocol.
function store(dir,options={}) {
 const original=fs.lstatSync(dir);
 const point=options.point||(()=>{});
 function check(){const d=fs.lstatSync(dir);if(!d.isDirectory()||d.isSymbolicLink()||d.uid!==process.getuid()||(d.mode&511)!==448||d.ino!==original.ino||d.dev!==original.dev)throw Error('directory-invalid');}
 function sync(){const fd=fs.openSync(dir,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);try{fs.fsyncSync(fd);}finally{fs.closeSync(fd);}}
 function write(name,data){const encoded=JSON.stringify(data)+'\n';if(Buffer.byteLength(encoded)>2048)throw Error('record-too-large');check();const fd=fs.openSync(path.join(dir,name),fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,384);try{fs.writeFileSync(fd,encoded);point('before-file-fsync',name);fs.fsyncSync(fd);point('after-file-fsync',name);}finally{fs.closeSync(fd);}point('before-directory-fsync',name);sync();point('after-directory-fsync',name);check();}
 function read(name){check();const fd=fs.openSync(path.join(dir,name),fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);try{const s=fs.fstatSync(fd);if(!s.isFile()||s.nlink!==1||s.uid!==process.getuid()||(s.mode&511)!==384||s.size>2048)throw Error('record-invalid');return parseStrict(fs.readFileSync(fd,'utf8'));}finally{fs.closeSync(fd);}}
 return {read,write,lock(){write('rotation.lock',{schema:2,state:'locked'});},
 replace(record){write('rotation-state.tmp',record);point('before-rename',record.phase);fs.renameSync(path.join(dir,'rotation-state.tmp'),path.join(dir,'rotation-state.json'));point('after-rename',record.phase);point('before-commit-fsync',record.phase);sync();point('after-commit-fsync',record.phase);check();},
 // Ready state was committed before unlink. No directory fsync is required:
 // resurrection of the lock after power loss only stops progress safely.
 unlock(){check();point('before-unlock');fs.unlinkSync(path.join(dir,'rotation.lock'));point('after-unlock');}};
}
function initialize(dir,b){if(!TOKEN.test(b.token)||!Number.isSafeInteger(b.activityId)||b.activityId<1||typeof b.nonce!=='string'||typeof b.run!=='string')throw Error('invalid-binding');store(dir).write('rotation-state.json',{schema:2,phase:'ready',token:b.token,activityId:b.activityId,nonce:b.nonce,run:b.run});}
module.exports={store,initialize,TOKEN};
