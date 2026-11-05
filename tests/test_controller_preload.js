'use strict';
const assert=require('assert'), EventEmitter=require('events');
const {createControllerPreloader}=require('../src/integrated/controller-preload');
function fixture() {
 const children=[], timers=new Set();let token;
 const loader=createControllerPreloader({uid:6000,spawn(value){
  token=value;const child=new EventEmitter();child.pid=123;child.exitCode=null;
  child.stdout=new EventEmitter();child.stdin=new EventEmitter();child.sent=[];
  child.stdin.end=value=>child.sent.push(value);children.push(child);return child;
 },timers:{setTimeout(callback){timers.add(callback);return callback;},clearTimeout(callback){timers.delete(callback);}}});
 loader.prepare();const child=children[0];
 const found=()=>({controller:[{pid:123,startTicks:456,uid:6000}],receiver:[],legacy:[],ui:[]});
 const ready=(extra={})=>child.stdout.emit('data',Buffer.from(JSON.stringify({stage:'controller-preloaded',token,pid:123,startTicks:456,...extra})+'\n'));
 const exit=()=>{child.exitCode=0;child.emit('exit',0);};
 return {loader,child,children,timers,found,ready,exit};
}
async function main(){
 {
  const f=fixture();f.loader.prepare();assert.equal(f.children.length,1);assert.deepEqual(f.child.sent,[]);
  assert.deepEqual(f.loader.filter(f.found()).controller,[]);
  const result=f.loader.activate(f.found());await Promise.resolve();assert.deepEqual(f.child.sent,[]);
  f.ready();assert.equal((await result).status,'starting');assert.equal(f.child.sent.length,1);
  assert.equal(JSON.parse(f.child.sent[0]).action,'start');
  assert.equal(f.loader.filter(f.found()).controller.length,1,'Active input is never masked');
  assert.equal(await f.loader.cancel(),true);assert.equal(f.child.sent.length,1,'Cancellation cannot stop an activated controller through the gate');
 }
 for(const change of [{pid:124},{uid:6001},{startTicks:0}]){
  const f=fixture(),found=f.found();found.controller[0]={...found.controller[0],...change};
  assert.strictEqual(f.loader.filter(found),found);assert.equal((await f.loader.activate(found)).returnValue,false);assert.deepEqual(f.child.sent,[]);
 }
 {
  const f=fixture();f.loader.filter(f.found());f.ready({startTicks:457});
  assert.deepEqual(f.child.sent,[undefined]);assert.equal((await f.loader.activate(f.found())).returnValue,false);
 }
 {
  const f=fixture();f.ready({token:'wrong'});assert.deepEqual(f.child.sent,[undefined]);
  f.exit();assert.equal(await f.loader.activate(f.found()),null);
 }
 {
  const f=fixture();const stop=f.loader.cancel();assert.deepEqual(f.child.sent,[undefined]);
  f.ready();assert.equal((await f.loader.activate(f.found())).returnValue,false);
  f.exit();assert.equal(await stop,true);assert.equal(f.child.sent.length,1);
 }
 {
  const f=fixture();const stop=f.loader.cancel();[...f.timers][0]();assert.equal(await stop,false);
  assert.equal(f.loader.filter(f.found()).controller.length,1,'Unconfirmed exit remains visible');
  assert.equal((await f.loader.activate(f.found())).returnValue,false);
 }
 {
  const f=fixture();const start=f.loader.activate(f.found());[...f.timers][0]();
  assert.equal((await start).returnValue,false);f.ready();assert.deepEqual(f.child.sent,[undefined]);
 }
 {
  const f=fixture();f.ready();const found=f.found();found.receiver=[{pid:9}];
  assert.equal((await f.loader.activate(found)).returnValue,false);assert.deepEqual(f.child.sent,[]);
 }
 {
  const f=fixture();f.exit();assert.equal(await f.loader.activate(f.found()),null);assert.equal(await f.loader.cancel(),true);
 }
 {
  const f=fixture();const result=f.loader.activate(f.found());f.exit();
  assert.equal(await result,null,'Confirmed exit before release permits the ordinary launch');
  assert.deepEqual(f.child.sent,[]);
 }
 {
  const f=fixture();f.ready();f.child.exitCode=0;
  assert.equal((await f.loader.activate(f.found())).returnValue,false);assert.deepEqual(f.child.sent,[]);
 }
 // Exercise Node's real inherited stdio transport, not a mocked FIFO.
 for(const release of [false,true]) {
  const cp=require('child_process'),path=require('path');
  const source=path.resolve(__dirname,'../src/integrated');
  const code='import sys;sys.path.insert(0,'+JSON.stringify(source)+');from controller_preload import await_start;print(await_start("'+ 'a'.repeat(32)+'",pid=12,ticks=34))';
  const child=cp.spawn('python3',['-I','-B','-c',code],{stdio:['pipe','pipe','pipe']});
  let output='',error='';child.stdout.on('data',data=>{
   output+=data;
   if(output.includes('controller-preloaded')&&!child.stdin.writableEnded)
    child.stdin.end(release?JSON.stringify({action:'start',token:'a'.repeat(32)})+'\n':undefined);
  });child.stderr.on('data',data=>error+=data);
  const exit=await new Promise((resolve,reject)=>{child.on('error',reject);child.on('close',resolve);});
  assert.equal(exit,0,error);assert(output.trim().endsWith(release?'True':'False'),output);
 }
 console.log('Controller preload: private release, exact child identity, conflicts, cancellation and timeout retention passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
