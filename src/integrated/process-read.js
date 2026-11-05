'use strict';
// Read the same process identities used by control.py, without spawning Python.
const fs = require('fs'), path = require('path');
const APP = 'org.magicsirimote.app';
const LEGACY = ['org.codex.siriremote.autocoord20261029v', 'org.codex.siriremote.hidgattrouterb20261029u'];
function processes(serviceDirectory, {procDirectory = '/proc', appDirectory = '/media/developer/apps/usr/palm/applications', io = fs} = {}) {
  const targets = new Map(['controller', 'receiver'].map(role => [path.join(serviceDirectory, 'roles', role, 'native_probe.py'), role]));
  for (const app of LEGACY) targets.set(path.join(appDirectory, app, 'native_probe.py'), 'legacy');
  targets.set(path.join(appDirectory, APP, 'native_probe.py'), 'ui');
  const result = {controller: [], receiver: [], legacy: [], ui: []};
  for (const name of io.readdirSync(procDirectory)) {
    if (!/^[0-9]+$/.test(name)) continue;
    const directory = path.join(procDirectory, name);
    try {
      const raw = io.readFileSync(path.join(directory, 'cmdline'));
      if (raw.length > 32768) throw Error('Process command exceeds limit');
      let end = raw.length;
      while (end && raw[end - 1] === 0) end--;
      const args = []; let start = 0;
      for (let i = 0; i < end; i++) if (raw[i] === 0) { args.push(raw.subarray(start, i)); start = i + 1; }
      args.push(raw.subarray(start, end));
      if (args.length !== 4 || !args.slice(0, 3).every((value, i) => value.equals(Buffer.from(['/usr/bin/python3', '-I', '-B'][i])))) continue;
      const script = args[3].toString('utf8');
      if (!Buffer.from(script, 'utf8').equals(args[3])) throw Error('Invalid process command');
      const role = targets.get(script);
      if (!role) continue;
      const ticks = () => {
        const text = io.readFileSync(path.join(directory, 'stat'), 'utf8'), end = text.lastIndexOf(')');
        const raw = end < 0 ? '' : text.slice(end + 2).trim().split(/\s+/)[19];
        if (!/^[0-9]+$/.test(raw || '') || !Number.isSafeInteger(Number(raw)) || Number(raw) <= 0) throw Error('Process identity unavailable');
        return Number(raw);
      };
      const startTicks = ticks(), status = {};
      for (const line of io.readFileSync(path.join(directory, 'status'), 'utf8').split('\n')) {
        const colon = line.indexOf(':');
        if (colon >= 0) status[line.slice(0, colon)] = line.slice(colon + 1).trim();
      }
      if (ticks() !== startTicks) throw Error('Process identity changed');
      const uids = (status.Uid || '').split(/\s+/), gids = (status.Gid || '').split(/\s+/), pid = Number(name);
      if (uids.length !== 4 || new Set(uids).size !== 1 || !/^[0-9]+$/.test(uids[0])
          || !Number.isSafeInteger(Number(uids[0])) || Number(uids[0]) <= 0
          || gids.length !== 4 || !gids.every(value => value === '5000')
          || status.CapEff !== '0000000000000000' || !Number.isSafeInteger(pid) || pid <= 0) throw Error('Unexpected runtime privileges');
      result[role].push({pid, startTicks, uid: Number(uids[0])});
    } catch (error) {
      if (error.code === 'ENOENT') continue;
      throw error;
    }
  }
  return result;
}
module.exports = {processes};
