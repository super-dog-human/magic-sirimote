'use strict';
const assert = require('assert');
const {createStartup, APP, NAME} = require('../src/integrated/startup');
function reservation() {
 return {activityId:155,name:NAME,creator:{serviceId:APP},state:'failed',adopters:[],subscribers:[],
 callback:{method:'luna://'+APP+'.service/startupTick',params:{token:'b'.repeat(48)}}};
}
function fixture(a, race=false) {
 let state=null, calls=[];
 const store={read:()=>state && JSON.parse(JSON.stringify(state)),write:v=>state=JSON.parse(JSON.stringify(v))};
 const s=createStartup({store,token:()=> 'a'.repeat(48),boot:()=> '11111111-1111-1111-1111-111111111111',
 activity:async(method,params)=>{calls.push([method,params]);if(race)state.phase='ready';return {value:{returnValue:true,activity:a}};}});
 s.prepare(); return {s,store,calls};
}
(async()=>{
 const f=fixture(reservation());const reply=await f.s.repair();
 assert.equal(reply.status,'cancel-required');assert.equal(reply.activityId,155);
 assert.equal(f.store.read().phase,'cancel-pending');
 assert.deepEqual(f.calls,[['getDetails',{activityName:NAME,internal:false,current:false}]]);
 assert.throws(()=>f.s.cancelled({activityId:156,resetToken:reply.resetToken}));
 f.s.cancelled({activityId:155,resetToken:reply.resetToken});
 assert.equal(f.s.prepare().status,'create-required');
 for(const change of [{creator:{serviceId:'other'}},{name:'other'}, {state:'running'},
   {adopters:[{}]}, {subscribers:[{}]}, {subscribers:null}, {activityId:true},
   {callback:{}}, {callback:{method:'other',params:{token:'b'.repeat(48)}}}]) {
  const f=fixture({...reservation(),...change});assert.equal((await f.s.repair()).returnValue,false);
  assert.equal(f.store.read().phase,'prepared');assert.equal(f.calls.length,1);
 }
 const race=fixture(reservation(),true);await assert.rejects(race.s.repair(),/changed/);
 console.log('Reinstall startup: exact terminal own reservation, active/foreign/malformed rejection and state-race guard passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
