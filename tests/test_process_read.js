'use strict';
const assert = require('assert'), fs = require('fs'), os = require('os'), path = require('path'), cp = require('child_process');
const {processes} = require('../src/integrated/process-read');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'sirimote-process-'));
const service = path.join(root, 'service'), apps = path.join(root, 'apps'), proc = path.join(root, 'proc');
fs.mkdirSync(proc);
function put(pid, script, uid = '5999', ticks = 1234) {
  const dir = path.join(proc, String(pid)); fs.mkdirSync(dir, {recursive: true});
  fs.writeFileSync(path.join(dir, 'cmdline'), ['/usr/bin/python3', '-I', '-B', script, ''].join('\0'));
  fs.writeFileSync(path.join(dir, 'stat'), pid + ' (python with ) space) ' + ['S', ...Array(18).fill('0'), String(ticks), '0'].join(' '));
  fs.writeFileSync(path.join(dir, 'status'), 'Uid:\t' + Array(4).fill(uid).join('\t') + '\nGid:\t5000 5000 5000 5000\nCapEff:\t0000000000000000\n');
}
const options = {procDirectory: proc, appDirectory: apps};
try {
  put(1, path.join(service, 'roles/controller/native_probe.py'));
  put(2, path.join(service, 'roles/receiver/native_probe.py'), '5001', 1235);
  put(3, path.join(apps, 'org.magicsirimote.app/native_probe.py'), '5001');
  put(4, path.join(apps, 'org.codex.siriremote.autocoord20261029v/native_probe.py'), '5002');
  put(5, path.join(apps, 'org.codex.siriremote.hidgattrouterb20261029u/native_probe.py'), '5003');
  put(6, path.join(service, 'control.py'));
  put(7, path.join(service, 'roles/controller/native_probe.py.backup'));
  put(8, path.join(service, 'roles/controller/native_probe.py'));
  const found = processes(service, options);
  assert.deepEqual(found.controller.map(v => v.pid), [1, 8]);
  assert.deepEqual(found.receiver, [{pid: 2, startTicks: 1235, uid: 5001}]);
  assert.deepEqual(found.ui.map(v => v.pid), [3]); assert.deepEqual(found.legacy.map(v => v.pid), [4, 5]);
  // Compare against the existing Python observer using exactly the same /proc fixture.
  const python = cp.spawnSync('python3', ['-c', `import json,sys
from pathlib import Path
sys.path[:0]=sys.argv[1:3]
import control_processes as p
p.bundle.ROOT=Path(sys.argv[3]);p.APP_ROOT=Path(sys.argv[4])
print(json.dumps(p.processes(sys.argv[5])))`, path.resolve(__dirname, '../src/runtime'), path.resolve(__dirname, '../src/integrated'), service, apps, proc], {encoding: 'utf8'});
  assert.equal(python.status, 0, python.stderr); assert.deepEqual(found, JSON.parse(python.stdout));
  const statusPath = path.join(proc, '1/status'), validStatus = fs.readFileSync(statusPath, 'utf8');
  for (const invalid of [validStatus.replace(/5999/g, '0'), validStatus.replace('5999', '5001'), validStatus.replace(/5000/g, '0'), validStatus.replace('0000000000000000', '0000000000000001'), 'Uid: invalid']) {
    fs.writeFileSync(statusPath, invalid); assert.throws(() => processes(service, options), /privileges/);
  }
  fs.writeFileSync(statusPath, validStatus);
  const cmdPath = path.join(proc, '1/cmdline'), validCommand = fs.readFileSync(cmdPath);
  fs.writeFileSync(cmdPath, Buffer.alloc(32769)); assert.throws(() => processes(service, options), /limit/);
  fs.writeFileSync(cmdPath, validCommand);
  for (const code of ['EACCES', 'EIO']) {
    const io = {...fs, readFileSync(file, encoding) { if (file === cmdPath) throw Object.assign(Error('unavailable'), {code}); return fs.readFileSync(file, encoding); }};
    assert.throws(() => processes(service, {...options, io}), /unavailable/);
  }
  const missing = {...fs, readFileSync(file, encoding) { if (file === cmdPath) throw Object.assign(Error('gone'), {code: 'ENOENT'}); return fs.readFileSync(file, encoding); }};
  assert.deepEqual(processes(service, {...options, io: missing}).controller.map(v => v.pid), [8]);
  let reads = 0;
  const changing = {...fs, readFileSync(file, encoding) { const data = fs.readFileSync(file, encoding); return file === path.join(proc, '1/stat') && ++reads === 2 ? data.replace('1234', '9999') : data; }};
  assert.throws(() => processes(service, {...options, io: changing}), /identity changed/);
  assert.throws(() => processes(service, {...options, procDirectory: path.join(root, 'absent')}));
  console.log('Process read: parity with Python; duplicate, privilege, identity and incomplete-read guards passed');
} finally { fs.rmSync(root, {recursive: true, force: true}); }
