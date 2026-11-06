'use strict';
const assert=require('node:assert/strict'),test=require('node:test');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),cp=require('node:child_process');
const {TemporaryRoot,config,payload}=require('../tools/installer/temporary-root');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'tools/installer/temporary-root-page.html'),'utf8');
function page() {
  const c=config(),calls=[],events=[],timers=[],requests=[];
  function Bridge(){this.call=(uri,body)=>calls.push({uri,body:JSON.parse(body),reply:r=>this.onservicecallback(JSON.stringify(r))});}
  function XHR(){this.open=(method,url)=>{this.method=method;this.url=url;};this.setRequestHeader=()=>{};
    this.send=body=>{if(this.method==='POST')events.push(JSON.parse(body));else requests.push(this);};}
  vm.runInNewContext(source.replace('__CONFIG__',JSON.stringify(c)).split('<script>')[1].split('</script>')[0],
    {webOSServiceBridge:Bridge,XMLHttpRequest:XHR,document:{getElementById:()=>({})},setTimeout:(fn,ms)=>timers.push({fn,ms})});
  return {c,calls,events,timers,requests};
}
test('preflight denial never registers or triggers a root service',()=>{
  const p=page();p.calls[0].reply({returnValue:false});
  assert.equal(p.calls.length,1);assert.ok(p.events.some(e=>e.kind==='not-registered'));
});
test('registration failure still requests unregistration',()=>{
  const p=page();p.calls[0].reply({returnValue:true});p.calls[1].reply({returnValue:false});
  assert.ok(p.calls[2].uri.endsWith('/removeManifestsDir'));
  assert.ok(!p.calls.some(c=>c.uri.endsWith('/collect')));
});
test('cancellation during registration waits for it and never triggers payload',()=>{
  const p=page();p.calls[0].reply({returnValue:true});
  p.requests[0].responseText='{"finish":true}';p.requests[0].onload();
  p.calls[2].reply({returnValue:true});
  assert.ok(!p.events.some(e=>e.kind==='removed'));
  p.calls[1].reply({returnValue:true});p.calls[3].reply({returnValue:true});
  assert.ok(p.events.some(e=>e.kind==='removed'));
  assert.ok(!p.calls.some(c=>c.uri.endsWith('/collect')));
});
test('independent cleanup timer and retry survive absent HTTP replies',()=>{
  const p=page();p.calls[0].reply({returnValue:true});p.calls[1].reply({returnValue:true});
  p.timers.find(t=>t.ms===65000).fn();const count=p.calls.length;
  p.timers.filter(t=>t.ms===3000).at(-1).fn();
  assert.equal(p.calls.length,count+1);assert.ok(p.calls.at(-1).uri.endsWith('/removeManifestsDir'));
});
test('generated operations compile and reject arbitrary commands',()=>{
  for(const action of ['inspect','remove','apply']) {
    const result=cp.spawnSync('python3',['-c','import sys;compile(sys.stdin.read(),"operation","exec")'],{input:payload(root,action),encoding:'utf8'});
    assert.equal(result.status,0,result.stderr);
  }
  assert.throws(()=>payload(root,'reboot'),/Unknown/);assert.throws(()=>config('../bad'),/Invalid/);
});
test('staged payload contains no private host paths or credentials',()=>{
  const t=new TemporaryRoot({root}); const files=t.assets(config(),'apply');
  assert.deepEqual(Object.keys(files),['runner.py','operation.py','probe.service','manifests/probe.json']);
  assert.ok(!JSON.stringify(files).includes('/Users/'));assert.ok(!JSON.stringify(files).includes('192.168.1.2'));
});

async function sessionFixture({owner=0,sameBoot=true,operationError,cleanupOnly=false,deny=false}={}) {
  const c={...config(),cleanupOnly},calls=[];let simulation;
  const installer={root,ip:'127.0.0.1',device:'test',log:()=>{},cli:(_tool,args)=>{
    const url=JSON.parse(args.at(-1)).contentTarget;
    simulation=(async()=>{
      assert.equal((await fetch(url.replace(c.token,'wrong-token'))).status,404);
      assert.equal((await fetch(url)).status,200);
      const base=url.replace('/index.html','');
      const post=(kind,detail)=>fetch(base+'/event',{method:'POST',body:JSON.stringify({run:c.run,kind,detail})});
      if(cleanupOnly) {await post('removed',{returnValue:true});return;}
      if(deny) {await post('preflight',{returnValue:false});await post('not-registered',{});return;}
      await post('registered',{returnValue:true});
      for(let n=0;n<100;n++) {
        const result=await (await fetch(base+'/status')).json();
        if(result.finish) {await post('removed',{returnValue:true});return;}
        await new Promise(resolve=>setTimeout(resolve,10));
      }
      throw Error('Host did not request cleanup');
    })();
    return {ok:true,output:''};
  }};
  const transport=new TemporaryRoot(installer,{wait:()=>new Promise(resolve=>setTimeout(resolve,10))});
  transport.remote=request=>{
    calls.push(request);
    if(request.action==='cleanup')return {removed:true};
    return {owner,report:{rootUid:owner,run:c.run,sameBoot,error:operationError,result:{state:'installed'}}};
  };
  let result,error;
  try {result=await transport.session(c,'127.0.0.1');} catch(e) {error=e;}
  await simulation;
  return {calls,result,error};
}
test('host verifies root receipt and removes exact staging after HTTP cleanup',async()=>{
  const f=await sessionFixture();assert.ifError(f.error);assert.equal(f.result.state,'installed');
  assert.equal(f.calls.at(-1).action,'cleanup');
});
test('nonroot and changed-boot replies never count as success',async()=>{
  for(const args of [{owner:5000},{sameBoot:false}]) {
    const f=await sessionFixture(args);assert.match(f.error.message,/unavailable/);
    assert.equal(f.calls.at(-1).action,'cleanup');
  }
});
test('operation failure is reported only after temporary cleanup',async()=>{
  const f=await sessionFixture({operationError:'Input service failed'});
  assert.match(f.error.message,/Input service failed/);assert.equal(f.calls.at(-1).action,'cleanup');
});
test('prior interrupted operation is cleaned without reading or running a payload',async()=>{
  const f=await sessionFixture({cleanupOnly:true});assert.ifError(f.error);
  assert.deepEqual(f.calls.map(x=>x.action),['cleanup']);
});
test('permission denial removes staging without claiming root or leaving a registered service',async()=>{
  const f=await sessionFixture({deny:true});assert.match(f.error.message,/unavailable/);
  assert.deepEqual(f.calls.map(x=>x.action),['cleanup']);
});
