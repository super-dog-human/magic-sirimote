'use strict';
const fs=require('fs'),path=require('path');
function ensurePrivateDirectory(dir,io=fs,exclusive=false){
 try{io.mkdirSync(dir,{mode:0o700});}catch(e){if(exclusive||e.code!=='EEXIST')throw e;}
 const st=io.lstatSync(dir);if(!st.isDirectory()||st.isSymbolicLink()||st.uid!==process.getuid()||(st.mode&0o777)!==0o700)throw Error('private-directory-invalid');
 const sync=d=>{const fd=io.openSync(d,io.constants.O_RDONLY|io.constants.O_DIRECTORY|io.constants.O_NOFOLLOW);try{io.fsyncSync(fd);}finally{io.closeSync(fd);}};
 sync(dir);sync(path.dirname(dir));return st;
}
module.exports={ensurePrivateDirectory};
