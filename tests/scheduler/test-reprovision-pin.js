'use strict';
const assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path'),crypto=require('crypto');
const {verifyPins}=require('../../src/scheduler/creator'),sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'pin-reprovision-')),root=path.join(tmp,'applications');fs.mkdirSync(root);
try{
 const pins={};for(const role of ['controller','receiver']){
  const id='test.'+role,app=path.join(root,id),pkg=path.join(tmp,'packages',id);fs.mkdirSync(app,{recursive:true});fs.mkdirSync(pkg,{recursive:true});
  fs.writeFileSync(path.join(app,'entry'),'original');fs.writeFileSync(path.join(pkg,'packageinfo.json'),'info');pins[role]={appId:id,files:{entry:sha('original')},packageInfoSha256:sha('info')};
 }
 assert.equal(verifyPins(root,pins),true); // No developer-owned state pin.
 fs.writeFileSync(path.join(root,'test.receiver','entry'),'tampered');assert.throws(()=>verifyPins(root,pins),/installed-package-pin-mismatch/);
 fs.writeFileSync(path.join(root,'test.receiver','entry'),'original');fs.writeFileSync(path.join(tmp,'packages','test.controller','packageinfo.json'),'tampered');assert.throws(()=>verifyPins(root,pins),/installed-package-info-mismatch/);
 console.log('PASS reprovision checks both exact packages without old state pin');
}finally{fs.rmSync(tmp,{recursive:true,force:true});}
