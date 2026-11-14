'use strict';
const assert=require('node:assert/strict');
const {IdleInspection,normalizeStateDirectories,stopWithPrivateVerification}=require('../tools/installer/private-idle');
const path=require('node:path');
async function main() {
  const operation=new IdleInspection({root:path.resolve(__dirname,'..')}).assets(
    {dir:'/media/developer/temp/test',run:'a'.repeat(24),service:'test'},'inspect')['operation.py'];
  assert.ok(operation.endsWith('result["idleProof"] = prepare_idle()\n'));
  const calls=[];
  const installer={device:'lg-g3',log:()=>{},cli:(...args)=>calls.push(args),stopInstalledApp:async()=>{}};
  let inspected=0;
  const proof={idle:true,startupDisabled:true,processes:[],cleanupMarkers:[]};
  const inspect=async()=>{inspected++;return {idleProof:proof};};
  await stopWithPrivateVerification(installer,inspect);assert.equal(inspected,0);assert.equal(calls.length,0);
  installer.stopInstalledApp=async()=>{throw Error('TV: The app did not answer its status check');};
  await stopWithPrivateVerification(installer,inspect);assert.equal(inspected,1);
  assert.deepEqual(calls[0],['ares-launch',['--device','lg-g3','--close','org.magicsirimote.app'],{allowFailure:true}]);
  for (const bad of [undefined,{...proof,idle:false},{...proof,startupDisabled:true,processes:[{pid:123}]},
                     {...proof,startupDisabled:false},{...proof,cleanupMarkers:['request']},{...proof,processes:null}]) {
    await assert.rejects(stopWithPrivateVerification(installer,async()=>({idleProof:bad})),/proof is incomplete/);
  }
  installer.stopInstalledApp=async()=>{throw Error('Finish the pending infrared operation');};
  await assert.rejects(stopWithPrivateVerification(installer,inspect),/pending infrared/);assert.equal(inspected,1);
  installer.stopInstalledApp=async()=>{throw Error('TV: The app did not answer its status check');};
  await assert.rejects(stopWithPrivateVerification(installer,async()=>{throw Error('Temporary cleanup failed');}),/cleanup failed/);
  assert.ok(calls.every(call=>call[0]==='ares-launch')); // No install or kill on failure.
  const directories=['app/state','service/state','service/state/sessions','controller/state','receiver/state'].map(path=>({path,mode:0o777}));
  let repaired=0,reads=0;
  const stateInstaller={log:()=>{},remote:()=>({directories:directories.map(row=>({...row,mode:++reads>5?0o770:row.mode}))})};
  await normalizeStateDirectories(stateInstaller,async()=>{repaired++;return {stateDirectories:directories.map(row=>({path:row.path,after:'0o770'}))};});
  assert.equal(repaired,1);
  await normalizeStateDirectories(stateInstaller,async()=>{throw Error('Already normal: must not request root');});
  stateInstaller.remote=()=>({directories});
  await assert.rejects(normalizeStateDirectories(stateInstaller,async()=>({stateDirectories:[]})),/not confirmed/);
  console.log('PASS: private stop fallback, complete proof required, unrelated failures retained.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
