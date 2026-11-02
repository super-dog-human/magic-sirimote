'use strict';
const assert=require('assert'),service=require('./service'),pins=require('./pins');let listener,calls=0,registered=[];
class Handle{registerMethod(cat,m){registered.push([cat,m]);}addListener(_,f){listener=f;}call(){calls++;throw Error('unexpected external call');}unregister(){}}
const runtime=service.createService({expiryRun:async()=>({status:"test-disabled"}),Handle,processExit:()=>{}});
function send(payload,subscription=false){let reply;listener({category:()=> '/',method:()=> 'receiverPin',isSubscription:()=>subscription,payload:()=>payload,respond:raw=>reply=JSON.parse(raw)});return reply;}
try{
 assert(registered.some(x=>x[1]==='receiverPin'));
 assert.deepStrictEqual(send('{}'),{returnValue:true,pin:pins.receiver});
 assert.deepStrictEqual(send('{"write":true}'),{returnValue:false,status:'rejected'});
 assert.deepStrictEqual(send('{}',true),{returnValue:false,status:'rejected'});
 assert.equal(calls,0);console.log('PASS public pin response without modifying activity or state');
}finally{runtime.close();}
