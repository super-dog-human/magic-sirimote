'use strict';
const assert = require('assert'), EventEmitter = require('events');
const {createPowerHints} = require('../src/integrated/power-hints');
const {createPowerObserver} = require('../src/integrated/power-observer');
const {createStartup} = require('../src/integrated/startup');
const flush = () => new Promise(resolve => setImmediate(resolve));
function clock() {
  let now = 0, next = 0;
  const pending = new Map();
  return {pending, now: () => now,
    setTimeout(fn, delay) { const id = ++next; pending.set(id, {fn, delay, at: now + delay}); return id; },
    clearTimeout(id) { pending.delete(id); },
    async step() {
      const [id, item] = [...pending].sort((a,b) => a[1].at - b[1].at)[0];
      pending.delete(id); now = item.at; item.fn(); await flush();
    }};
}
function hintsFixture() {
  const timers = clock(), requests = []; let wakes = 0;
  const handle = {subscribe(url, params) {
    assert.equal(url, 'luna://com.webos.service.tvpower/power/getPowerState');
    assert.deepEqual(JSON.parse(params), {subscribe:true});
    const r = new EventEmitter(); r.cancel = () => { r.cancelled = true; }; requests.push(r); return r;
  }};
  const hints = createPowerHints(handle, {timers, onActive: () => wakes++});
  const send = async value => {
    requests.at(-1).emit('response', {payload: () => typeof value === 'string' ? value : JSON.stringify(value)});
    await flush();
  };
  return {timers, requests, hints, send, wakes: () => wakes};
}
async function main() {
  const good = state => ({returnValue:true,subscribed:true,state});
  {
    const f = hintsFixture();
    await f.send(good('Active Standby')); assert.equal(f.wakes(),0);
    await f.send({...good('Active'),processing:'Request Resume'}); assert.equal(f.wakes(),0);
    await f.send(good('Active')); await f.send(good('Active')); assert.equal(f.wakes(),1);
    await f.send(good('Screen Off')); assert.equal(f.wakes(),1);
    await f.send(good('Active')); assert.equal(f.wakes(),2);
    f.hints.close(); assert(f.requests[0].cancelled); assert.equal(f.timers.pending.size,0);
    await f.send(good('Active')); assert.equal(f.wakes(),2);
  }
  for (const invalid of ['!', 'x'.repeat(4097), {returnValue:false}, {...good('Active'),subscribed:false}, {...good('Active'),processing:3}]) {
    const f = hintsFixture(); await f.send(invalid);
    assert.equal(f.wakes(),0); assert(f.requests[0].cancelled);
    assert.equal([...f.timers.pending.values()][0].delay,30000);
    const old=f.requests[0]; await f.timers.step(); assert.equal(f.requests.length,2);
    old.emit('response',{payload:()=>JSON.stringify(good('Active'))}); await flush(); assert.equal(f.wakes(),0);
    await f.send(good('Active')); assert.equal(f.wakes(),1); f.hints.close();
  }
  {
    const f=hintsFixture(); await f.timers.step(); assert(f.requests[0].cancelled); assert.equal(f.wakes(),0); f.hints.close();
  }
  {
    const f=hintsFixture();await f.send({state:'Active'});
    assert.equal(f.wakes(),0);assert(f.requests[0].cancelled,'Require initial subscription acknowledgement');f.hints.close();
  }
  {
    const f=hintsFixture();await f.send(good('Active Standby'));
    await f.send({state:'Active'});assert.equal(f.wakes(),1,'Accept compact changes only on an acknowledged subscription');
    await f.send({state:'Suspend',returnValue:true});await f.send({state:'Active',subscribed:true});assert.equal(f.wakes(),2);
    await f.send({state:'Active',subscribed:false});assert(f.requests[0].cancelled);assert.equal(f.wakes(),2);f.hints.close();
  }
  {
    const timers=clock(); let resolve, polls=0, wakes=0, active=0, maximum=0;
    const wait = () => { active++;maximum=Math.max(maximum,active);return new Promise(r=>{resolve=value=>{active--;r(value);};}); };
    const observer=createPowerObserver({timers,enqueue:fn=>fn(),poll:()=>{polls++;return wait();},wake:()=>{wakes++;return wait();}});
    await timers.step(); observer.notifyActive();observer.notifyActive();
    assert.equal(polls,1);assert.equal(wakes,0);assert.equal(timers.pending.size,0);
    resolve({pollAfterMs:150});await flush(); assert.equal([...timers.pending.values()][0].delay,150);
    observer.notifyActive(); assert.equal([...timers.pending.values()][0].delay,150);
    await timers.step();resolve();await flush();
    assert.equal([...timers.pending.values()][0].delay,2000);
    observer.notifyActive();observer.notifyActive();assert.equal(timers.pending.size,1);
    await timers.step();assert.equal(wakes,1);assert.equal(maximum,1);
    observer.close();resolve();await flush();assert.equal(timers.pending.size,0);
  }
  for (const mode of ['normal','stale','disabled','busy','missing-notification']) {
    const timers=clock();let state=null,starts=0,stops=0,reads=0,power='Active Standby';
    const store={read:()=>state&&structuredClone(state),write:s=>{state=structuredClone(s);}};
    const startup=createStartup({store,activity:()=>{},boot:()=> '11111111-1111-1111-1111-111111111111',now:timers.now,token:()=> 'a'.repeat(48)});
    const p=startup.prepare();startup.bind({token:p.token,activityId:1});
    let tail=Promise.resolve();
    const deps={power:async()=>{reads++;return {state:power};},status:async()=>({returnValue:true,processes:{controller:[],receiver:[],legacy:[],ui:mode==='busy'?[{}]:[]}}),start:async()=>{starts++;return {returnValue:true,status:'starting'};},stop:async()=>{stops++;}};
    const observer=createPowerObserver({timers,enqueue:fn=>tail=tail.then(fn,fn),poll:()=>startup.poll(deps),wake:()=>startup.wake(deps)});
    await timers.step(); // First standby sample. Next periodic read is 2s away.
    if(mode==='disabled')startup.disable();
    if(mode!=='stale')power='Active';
    if(mode!=='missing-notification')observer.notifyActive();
    await timers.step();
    if(mode==='normal'||mode==='missing-notification') {
      assert.equal(starts,0);await timers.step();assert.equal(starts,1);
      assert.equal(timers.now(),mode==='normal'?150:2150);
      await timers.step();assert.equal(starts,1,'An event cannot reset the durable start attempt');
    } else {
      assert.equal(starts,0);assert.equal(stops,0,'A stale Active hint must not accelerate a standby stop');
    }
    assert(reads>=1);observer.close();assert.equal(timers.pending.size,0);
  }
  console.log('Power notifications: fresh recheck, 150ms confirmation, periodic fallback, stale/duplicate events, maintenance, conflicts and cleanup passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
