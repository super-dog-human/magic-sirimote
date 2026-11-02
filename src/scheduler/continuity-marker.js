'use strict';
// Offline candidate. The marker is positive same-session evidence only:
// absence never proves a restart. Nothing executes or writes on import.
const fs=require('fs'),path=require('path');
const TOKEN=/^[a-f0-9]{32}$/;
function rootCheck(root){
 if(typeof root!=='string'||!path.isAbsolute(root))throw Error('invalid-root');
 const s=fs.lstatSync(root);if(!s.isDirectory()||s.isSymbolicLink())throw Error('invalid-root');return s;
}
function dirPath(root,token){if(typeof token!=='string'||!TOKEN.test(token))throw Error('invalid-token');return path.join(root,'codex-siri-epoch-'+token);}
function same(a,b){return a.dev===b.dev&&a.ino===b.ino&&a.uid===b.uid&&a.gid===b.gid&&a.mode===b.mode;}
function validateDir(s,uid){return s.isDirectory()&&!s.isSymbolicLink()&&s.uid===uid&&(s.mode&0o777)===0o700;}
function readProof(root,token,{uid=process.getuid()}={}){
 if(!Number.isInteger(uid)||uid<0)throw Error('invalid-marker-owner');
 const base=rootCheck(root),dir=dirPath(root,token),before=fs.lstatSync(dir);
 if(!validateDir(before,uid))throw Error('invalid-marker-directory');
 const dfd=fs.openSync(dir,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);
 try{
  if(!same(before,fs.fstatSync(dfd)))throw Error('marker-directory-changed');
  const p=path.join(dir,'marker'),prior=fs.lstatSync(p);
  if(!prior.isFile()||prior.isSymbolicLink()||prior.nlink!==1||prior.uid!==uid||(prior.mode&0o777)!==0o600||prior.size!==33)throw Error('invalid-marker-file');
  const fd=fs.openSync(p,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
  try{
   const opened=fs.fstatSync(fd);if(!same(prior,opened)||opened.size!==prior.size)throw Error('marker-file-changed');
   const data=fs.readFileSync(fd,'utf8');const after=fs.fstatSync(fd);
   if(data!==token+'\n'||!same(opened,after)||after.size!==opened.size||after.mtimeMs!==opened.mtimeMs||after.ctimeMs!==opened.ctimeMs||after.nlink!==1)throw Error('marker-content-changed');
  }finally{fs.closeSync(fd);}
  const pathAfter=fs.lstatSync(p);
  if(!same(prior,pathAfter)||pathAfter.size!==prior.size||pathAfter.mtimeMs!==prior.mtimeMs||pathAfter.ctimeMs!==prior.ctimeMs||pathAfter.nlink!==1)throw Error('marker-file-replaced');
  if(!same(before,fs.fstatSync(dfd))||!same(before,fs.lstatSync(dir))||!same(base,fs.lstatSync(root)))throw Error('marker-path-changed');
  return {token,device:before.dev,inode:before.ino};
 }finally{fs.closeSync(dfd);}
}
function create(root,token,{uid=process.getuid()}={}){
 if(!Number.isInteger(uid)||uid<0)throw Error('invalid-marker-owner');
 const base=rootCheck(root),dir=dirPath(root,token);
 fs.mkdirSync(dir,{mode:0o700}); // O_EXCL equivalent; never reuse or delete an uncertain marker.
 const dfd=fs.openSync(dir,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);
 try{
  const d=fs.fstatSync(dfd);if(!validateDir(d,uid)||!same(d,fs.lstatSync(dir))||!same(base,fs.lstatSync(root)))throw Error('marker-directory-unverified');
  const fd=fs.openSync(path.join(dir,'marker'),fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);
  try{fs.fchmodSync(fd,0o600);fs.writeFileSync(fd,token+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
  if(!same(d,fs.lstatSync(dir)))throw Error('marker-directory-changed');
  fs.fsyncSync(dfd);
 }finally{fs.closeSync(dfd);}
 const proof=readProof(root,token,{uid});const rfd=fs.openSync(root,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);
 try{fs.fsyncSync(rfd);}finally{fs.closeSync(rfd);}
 return proof;
}
function sameAs(root,expected,options){
 if(!expected||typeof expected.token!=='string'||!TOKEN.test(expected.token)||!Number.isSafeInteger(expected.device)||!Number.isSafeInteger(expected.inode))throw Error('invalid-saved-proof');
 try{const live=readProof(root,expected.token,options);return live.device===expected.device&&live.inode===expected.inode;}
 catch(e){if(e&&e.code==='ENOENT')return false;throw e;}
}
module.exports={create,readProof,sameAs};
