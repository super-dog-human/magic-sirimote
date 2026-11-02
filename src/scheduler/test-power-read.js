'use strict';
const assert=require('assert'),{EventEmitter}=require('events'),{readPower}=require('./standby-resume');
(async()=>{
 let fallback=0,cancels=0;
 const handle=v=>({call(uri,body){assert.equal(uri,'luna://com.webos.service.tvpower/power/getPowerState');assert.deepEqual(JSON.parse(body),{subscribe:false});const req=new EventEmitter();req.cancel=()=>{cancels++;};queueMicrotask(()=>req.emit('response',{payload:()=>JSON.stringify(v)}));return req;}});
 const exec=(file,args,opts,cb)=>{fallback++;assert.equal(file,'/usr/bin/python3');assert(args[2].endsWith('/power-read.py'));assert.equal(opts.timeout,5000);cb(null,'{"state":"Active"}');};
 assert.equal((await readPower(handle({returnValue:true,state:'Active'}),globalThis,exec)).state,'Active');assert.equal(fallback,0);
 assert.equal((await readPower(handle({returnValue:true,state:'Screen Off'}),globalThis,exec)).state,'Screen Off');assert.equal(fallback,0);
 assert.equal((await readPower(handle({returnValue:false,errorCode:-1,errorText:'Denied'}),globalThis,exec)).state,'Active');assert.equal(fallback,1);
 const fail=(_f,_a,_o,cb)=>cb(Error('failed'));
 assert.equal((await readPower(handle({returnValue:false,errorCode:-1}),globalThis,fail)).state,'Unavailable');
 assert.equal(cancels,4);console.log('PASS power read: exact read-only URI; direct Active/Screen Off respected; bounded anonymous fallback; failures remain unavailable; requests canceled');
})().catch(e=>{console.error(e);process.exitCode=1;});
