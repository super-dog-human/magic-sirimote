'use strict';
const assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path'),crypto=require('crypto');
const {verifyPins}=require('./creator');
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'siri-pin-test-'));
try{
 const root=path.join(temp,'applications');fs.mkdirSync(root);
 const pins={};
 for(const name of ['controller','receiver']){
  const app='test.'+name,dir=path.join(root,app),pkg=path.join(temp,'packages',app);fs.mkdirSync(dir,{recursive:true});fs.mkdirSync(pkg,{recursive:true});
  fs.writeFileSync(path.join(dir,'entry'),'original');fs.writeFileSync(path.join(pkg,'packageinfo.json'),'info');
  pins[name]={appId:app,files:{entry:sha('original')},packageInfoSha256:sha('info')};
 }
 fs.writeFileSync(path.join(root,'test.controller','entry'),'altered');
 assert.throws(()=>verifyPins(root,pins),/installed-package-pin-mismatch/);
 fs.writeFileSync(path.join(root,'test.controller','entry'),'original');
 fs.writeFileSync(path.join(temp,'packages','test.receiver','packageinfo.json'),'altered');
 assert.throws(()=>verifyPins(root,pins),/installed-package-info-mismatch/);
 console.log('tampered app and package metadata rejected before provisioning');
}finally{fs.rmSync(temp,{recursive:true,force:true});}
