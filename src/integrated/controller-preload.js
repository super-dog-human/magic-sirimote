'use strict';
const crypto = require('crypto');
function createControllerPreloader({spawn, uid = process.getuid(), timers = globalThis}) {
  let session = null, attempted = false;
  function pending(s) {return s && ['loading','ready'].includes(s.state);}
  function identity(s, found) {
    const rows = found.controller;
    if (!pending(s) || s.child.exitCode !== null || !Array.isArray(rows) || rows.length !== 1) return false;
    const p = rows[0];
    if (p.pid !== s.child.pid || p.uid !== uid || !Number.isSafeInteger(p.startTicks) || p.startTicks <= 0) return false;
    if (s.ticks !== null && s.ticks !== p.startTicks) return false;
    s.ticks = p.startTicks;return true;
  }
  function notify(s) {for (const f of [...s.listeners]) f();}
  function stopPending(s) {
    if (!pending(s)) return;
    s.state = 'cancelling';
    try {s.child.stdin.end();} catch (_) {}
    notify(s);
  }
  function prepare() {
    if (attempted) return;attempted=true;
    const token = crypto.randomBytes(16).toString('hex');
    let child;
    try {child=spawn(token);} catch (_) {return;}
    const s = {child,token,ticks:null,state:'loading',buffer:'',listeners:new Set()};session=s;
    function ended() {s.state='ended';notify(s);}
    child.once('exit',ended);
    child.once('close',ended);
    child.once('error',()=>{if (!child.pid) ended();else stopPending(s);});
    child.stdin.on('error',()=>stopPending(s));
    child.stdout.on('data',raw=>{
      if (!pending(s)) return;
      s.buffer+=raw.toString('utf8');
      if (Buffer.byteLength(s.buffer)>8192) {stopPending(s);return;}
      let end;
      while ((end=s.buffer.indexOf('\n'))>=0) {
        const line=s.buffer.slice(0,end);s.buffer=s.buffer.slice(end+1);
        try {
          const value=JSON.parse(line);
          if (value.stage!=='controller-preloaded') continue;
          if (s.state!=='loading' || value.token!==token || value.pid!==child.pid
              || !Number.isSafeInteger(value.startTicks) || value.startTicks<=0
              || (s.ticks!==null && s.ticks!==value.startTicks)) throw Error('Prepared identity differs');
          s.ticks=value.startTicks;s.state='ready';notify(s);
        } catch (_) {stopPending(s);return;}
      }
    });
    child.stdout.once('end',()=>stopPending(s));
    child.stdout.once('error',()=>stopPending(s));
  }
  function filter(found) {
    return identity(session,found) ? {...found,controller:[]} : found;
  }
  function wait(s, predicate, timeout) {
    if (predicate()) return Promise.resolve(true);
    return new Promise(resolve=>{
      let timer;
      function finish(value) {s.listeners.delete(check);timers.clearTimeout(timer);resolve(value);}
      function check() {if (predicate()) finish(true);}
      s.listeners.add(check);timer=timers.setTimeout(()=>finish(false),timeout);check();
    });
  }
  async function activate(found) {
    const s=session;
    if (!s || s.state==='ended') return null;
    if (!identity(s,found) || ['receiver','legacy','ui'].some(role=>!Array.isArray(found[role]) || found[role].length))
      return {returnValue:false,status:'prepared-process-changed'};
    const settled=await wait(s,()=>s.state!=='loading',10000);
    // EOF/exit before the release means this child never acquired input. The
    // normal launcher may proceed, but an unconfirmed exit must still block it.
    if (s.state==='ended') return null;
    if (!settled || s.state!=='ready' || s.child.exitCode !== null) {
      stopPending(s);return {returnValue:false,status:'preparation-unavailable'};
    }
    // No retry once bytes may have reached the child. Its own gate rechecks
    // package, settings and process conflicts before it can touch Bluetooth.
    s.state='active';
    try {s.child.stdin.end(JSON.stringify({action:'start',token:s.token})+'\n');}
    catch (_) {return {returnValue:false,status:'prepared-release-unconfirmed'};}
    return {returnValue:true,status:'starting',pid:s.child.pid};
  }
  async function cancel() {
    const s=session;
    if (!s || ['ended','active'].includes(s.state)) return true;
    stopPending(s);
    return wait(s,()=>s.state==='ended',10000);
  }
  return {prepare,filter,activate,cancel};
}
module.exports={createControllerPreloader};
