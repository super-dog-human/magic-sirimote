'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path'), crypto = require('node:crypto');
const {Installer, shellQuote, validPort, verifyFiles, jsonReply, run} = require('../tools/installer/main');
const root = fs.mkdtempSync(path.join(os.tmpdir(),'sirimote-installer-test-'));
fs.mkdirSync(path.join(root,'releases')); fs.mkdirSync(path.join(root,'tools/installer'),{recursive:true});
fs.copyFileSync(path.join(__dirname,'../tools/installer/tv.py'),path.join(root,'tools/installer/tv.py'));
const data = 'package bytes', sha = crypto.createHash('sha256').update(data).digest('hex');
const packagePath = path.join(root,'releases/org.magicsirimote.app_arm.ipk');
fs.writeFileSync(packagePath,data);
fs.writeFileSync(path.join(root,'releases/SHA256SUMS'),sha+'  org.magicsirimote.app_arm.ipk\n');
fs.writeFileSync(path.join(root,'releases/manifest.json'),JSON.stringify({package:{packageSha256:sha,files:{'usr/palm/test':'123'}}}));
fs.cpSync(path.join(__dirname,'../tools/hid-guard'),path.join(root,'tools/hid-guard'),{recursive:true});
const cases=[];
function test(name,body) { cases.push([name,body]); }
function fixture({answers=['192.168.1.20','9922','n'], devices=[], appPresent=false, missing=[], fail, state, verification} = {}) {
  const calls=[],logs=[]; const pending=[...answers];
  const instance=new Installer({root,find:tool=>tool,log:message=>logs.push(message),wait:async()=>{},
    prompt:async (question,fallback)=>{assert.ok(pending.length,'Unexpected prompt: '+question);const value=pending.shift();return value === '' ? fallback || '' : value;},
    execute:(program,args,options={})=>{
      calls.push({program,args,options});
      const failure=fail?.(program,args,options,calls); if(failure) return failure;
      let output='';
      if(program==='ares-setup-device' && args.includes('--listfull')) output=JSON.stringify(devices);
      if(program==='ares-novacom' && args.includes('--run')) {
        const code=args.at(-1);
        if(code.includes('"action\\":\\"probe')) output=JSON.stringify({missing,appPresent});
        else if(code.includes('"action\\":\\"verify')) output=JSON.stringify(verification || {verifiedFiles:1,mismatch:[]});
        else if(code.includes('"action\\":\\"status')) output=JSON.stringify(state || {returnValue:true,cleanStop:true,startup:{enabled:false},processes:{controller:[],receiver:[],native:[],legacy:[]}});
        else output=JSON.stringify({staged:true});
      }
      if(program==='tar') output=Buffer.from([0,255,1,254]);
      return {ok:true,output};
    }});
  return {instance,calls,logs,pending};
}
const installed=f=>f.calls.some(c=>c.program==='ares-install' && !c.args.includes('--remove'));
test('argument quoting and input validation',()=>{
  for(const value of ['22','9922','65535']) assert.ok(validPort(value));
  for(const value of ['0','65536','22;reboot','-1','1.5']) assert.ok(!validPort(value));
  const value="address'; touch /tmp/never; '";
  assert.equal(run('/bin/sh',['-c','printf %s '+shellQuote(value)]).output,value);
  assert.deepEqual(jsonReply('cli prefix\n{"ok":true}\n'),{ok:true});
});
test('fresh installation verifies and launches without root',async()=>{
  const f=fixture(); await f.instance.run('1'); assert.ok(installed(f));
  assert.ok(f.calls.some(c=>c.program==='ares-launch')); assert.ok(!f.calls.some(c=>c.program==='ssh'));
  assert.equal(f.pending.length,0); assert.ok(f.logs.some(s=>s.includes('Installation complete')));
});
test('saved device reuse uses actual LG CLI listfull schema',async()=>{
  const f=fixture({devices:[{name:'living-room',deviceinfo:{ip:'192.168.1.20',port:'9922',user:'prisoner'}}]});
  await f.instance.run('1'); assert.equal(f.instance.device,'living-room'); assert.ok(!f.calls.some(c=>c.args.includes('--add')));
});
test('new device never replaces an existing nickname',async()=>{
  const f=fixture({devices:[{name:'sirimote-192-168-1-20',deviceinfo:{ip:'192.168.1.21',port:'9922',user:'prisoner'}}]});
  await f.instance.run('1'); assert.equal(f.instance.device,'sirimote-192-168-1-20-2');
});
test('invalid address/port are reprompted and never sent to commands',async()=>{
  const f=fixture({answers:['192.168.1.20;reboot','192.168.1.20','70000','9922','n']});
  await f.instance.run('1'); assert.ok(!JSON.stringify(f.calls).includes('192.168.1.20;reboot'));
});
test('missing CLI explains install and can be declined',async()=>{
  const f=fixture({answers:['n']}); f.instance.find=()=>null;
  await assert.rejects(f.instance.run('1'),/Install the webOS tools/); assert.equal(f.calls.length,0);
});
test('npm installation failure explains recovery without touching TV',async()=>{
  const f=fixture({answers:['y'],fail:p=>p==='npm'?{ok:false,error:'EACCES'}:null});
  f.instance.find=t=>t==='npm'?'npm':null;
  await assert.rejects(f.instance.run('1'),/permission errors/); assert.ok(!installed(f));
});
test('connection key is acquired interactively, no passphrase argument',async()=>{
  let n=0;
  const f=fixture({answers:['192.168.1.20','9922','y','n'],fail:p=>p==='ares-device' && n++===0?{ok:false,error:'key'}:null});
  await f.instance.run('1'); const key=f.calls.find(c=>c.args.includes('--getkey')); assert.ok(key.options.interactive);
});
test('failed connection never attempts install',async()=>{
  const f=fixture({fail:p=>p==='ares-device'?{ok:false,error:'offline'}:null});
  await assert.rejects(f.instance.run('1'),/Connection cancelled/); assert.ok(!installed(f));
});
test('capability failure prevents installation with specific explanation',async()=>{
  const f=fixture({missing:['SDL2_ttf']}); await assert.rejects(f.instance.run('1'),/SDL2_ttf/); assert.ok(!installed(f));
});
test('check mode does not launch, stop, install or access root',async()=>{
  const f=fixture({answers:['192.168.1.20','9922']}); await f.instance.run('check');
  assert.ok(!f.calls.some(c=>['ssh','ares-install','ares-launch'].includes(c.program)));
});
test('corrupt download prevents installation',async()=>{
  fs.writeFileSync(packagePath,'corrupt');
  try { const f=fixture(); await assert.rejects(f.instance.run('1'),/verification failed/); assert.ok(!installed(f)); }
  finally {fs.writeFileSync(packagePath,data);}
});
test('updating waits for cooperative stop before replacing app',async()=>{
  const f=fixture({appPresent:true,answers:['192.168.1.20','9922','','n']}); await f.instance.run('1');
  const close=f.calls.findIndex(c=>c.program==='ares-launch' && c.args.includes('--close'));
  assert.ok(close>=0 && close<f.calls.findIndex(c=>c.program==='ares-install'));
});
test('update failure to stop leaves existing package untouched',async()=>{
  const f=fixture({appPresent:true,answers:['192.168.1.20','9922',''],state:{returnValue:true,cleanStop:false,startup:{enabled:true}}});
  await assert.rejects(f.instance.run('1'),/No package was replaced/); assert.ok(!installed(f));
});
test('installed file mismatch prevents launch and TV fix',async()=>{
  const f=fixture({verification:{verifiedFiles:0,mismatch:['bad']}});
  await assert.rejects(f.instance.run('1'),/Installed-file verification failed/); assert.ok(!f.calls.some(c=>c.program==='ares-launch'));
});
test('optional fix failure is reported but app can still open',async()=>{
  const f=fixture({answers:['192.168.1.20','9922','y','22',''],fail:p=>p==='ssh'?{ok:false,error:'root unavailable'}:null});
  await f.instance.run('1'); assert.ok(f.logs.some(s=>s.includes('not completed'))); assert.ok(f.calls.some(c=>c.program==='ares-launch'));
  assert.equal(f.instance.sshTemp,null);
});
test('root password connection is reused for binary transfer and then closed',async()=>{
  const f=fixture({answers:['22','']}); f.instance.ip='192.168.1.20';
  try { await f.instance.tvFix('apply'); }
  finally { f.instance.cleanup(); }
  const ssh=f.calls.filter(c=>c.program==='ssh'); assert.equal(ssh.length,3);
  assert.ok(ssh[0].options.interactive); assert.ok(ssh[0].args.includes('ControlPersist=120'));
  assert.ok(Buffer.isBuffer(ssh[1].options.input)); assert.ok(ssh[1].args.includes('BatchMode=yes'));
  assert.equal(ssh[0].args[ssh[0].args.indexOf('-S')+1],ssh[1].args[ssh[1].args.indexOf('-S')+1]);
  assert.deepEqual(ssh[2].args.slice(0,2),['-O','exit']);
  assert.equal(f.calls.filter(c=>c.program==='tar').length,1);
});
test('uninstall cancellation preserves app',async()=>{
  const f=fixture(); await f.instance.run('2'); assert.ok(!f.calls.some(c=>c.program==='ares-install'));
});
test('uninstall removes package only after stop',async()=>{
  const f=fixture({appPresent:true,answers:['192.168.1.20','9922','y','','n']}); await f.instance.run('2');
  assert.ok(f.calls.some(c=>c.program==='ares-install' && c.args.includes('--remove')));
});
test('remove fix only does not touch app',async()=>{
  const f=fixture({answers:['192.168.1.20','9922','22','']}); await f.instance.run('3');
  assert.ok(!f.calls.some(c=>['ares-install','ares-launch'].includes(c.program)));
});
(async()=>{
  try { for (const [name,body] of cases) { await body(); console.log('OK '+name); } console.log(`${cases.length} installer tests passed`); }
  finally { fs.rmSync(root,{recursive:true,force:true}); }
})().catch(error=>{console.error(error);process.exitCode=1;});
