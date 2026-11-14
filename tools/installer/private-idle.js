'use strict';
// Scoped maintenance fallback for the installed app's unresponsive status method.
const fs = require('node:fs'), path = require('node:path');
const {TemporaryRoot} = require('./temporary-root');
class IdleInspection extends TemporaryRoot {
  assets(config, action) {
    if (action !== 'inspect') throw Error('Scoped maintenance inspection required.');
    const files = super.assets(config, action);
    files['operation.py'] += '\n' + fs.readFileSync(path.join(this.root,'tools/installer/private_idle.py'),'utf8') +
      '\nresult["idleProof"] = prepare_idle()\n';
    return files;
  }
}
class SharedStateRepair extends TemporaryRoot {
  assets(config, action) {
    if (action !== 'inspect') throw Error('Scoped state repair required.');
    const files = super.assets(config, action);
    files['operation.py'] += '\n' + fs.readFileSync(path.join(this.root,'tools/installer/private_idle.py'),'utf8') +
      '\nresult["stateDirectories"] = normalize_shared_state()\n';
    return files;
  }
}
async function normalizeStateDirectories(installer, repair = () => new SharedStateRepair(installer).run('inspect')) {
  const before = installer.remote({action:'state-directories'}).directories;
  if (!Array.isArray(before) || before.length !== 5 || new Set(before.map(row=>row.path)).size !== 5 ||
      before.some(row=>![0o770,0o775,0o777].includes(row.mode))) throw Error('Shared state inventory is incomplete.');
  if (before.every(row=>row.mode===0o770 || row.mode===0o775)) return;
  installer.log('Restoring the five package-owned state directories to 0770. Saved settings, pairing and reset records are retained.');
  const report = await repair();
  if (!Array.isArray(report.stateDirectories) || report.stateDirectories.length !== 5 ||
      before.some(row=>report.stateDirectories.filter(item=>item.path===row.path && item.after==='0o770').length!==1))
    throw Error('State permission repair was not confirmed. App was not launched.');
  const after = installer.remote({action:'state-directories'}).directories;
  if (!Array.isArray(after) || after.length!==5 ||
      before.some(row=>after.filter(item=>item.path===row.path && item.mode===0o770).length!==1))
    throw Error('State directory permissions changed after repair.');
  installer.log('Shared state directory permissions verified.');
}
async function stopWithPrivateVerification(installer, inspect = () => new IdleInspection(installer).run('inspect')) {
  try { await installer.stopInstalledApp(); return; }
  catch (error) {
    const message = String(error.message);
    if (!message.endsWith('The app did not answer its status check') &&
        !message.startsWith('The app could not stop: Application request outcome is unknown;')) throw error;
    installer.log('The installed status service did not answer. Checking private runtime state through temporary access; automatic startup may be disabled only after input is confirmed stopped.');
  }
  // This asks the app to close normally. The native UI defers closing while
  // programming. Never signal/kill a process or clear an uncertain marker.
  installer.cli('ares-launch',['--device',installer.device,'--close','org.magicsirimote.app'],{allowFailure:true});
  const report = await inspect();
  const proof = report?.idleProof;
  if (proof?.idle !== true || proof.startupDisabled !== true ||
      !Array.isArray(proof.processes) || proof.processes.length ||
      !Array.isArray(proof.cleanupMarkers) || proof.cleanupMarkers.length)
    throw Error('Independent stop proof is incomplete. No package was changed.');
  installer.log('Confirmed: automatic startup disabled, no app/input processes, no pending cleanup markers.');
}
module.exports = {IdleInspection, SharedStateRepair, normalizeStateDirectories, stopWithPrivateVerification};
