'use strict';
// The shell entry point downloads one revision; this driver uses only Node built-ins.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const cp = require('node:child_process'), net = require('node:net'), os = require('node:os');
const readline = require('node:readline/promises');
const {TemporaryRoot} = require('./temporary-root');
const ROOT = path.resolve(__dirname, '../..');
const APP = 'org.magicsirimote.app';
const CLI = ['ares-config', 'ares-setup-device', 'ares-novacom', 'ares-device', 'ares-install', 'ares-launch'];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function executable(name, env = process.env) {
  for (const directory of (env.PATH || '').split(path.delimiter)) {
    if (!directory) continue;
    const file = path.join(directory, name);
    try { fs.accessSync(file, fs.constants.X_OK); if (fs.statSync(file).isFile()) return file; } catch {}
  }
  return null;
}
function shellQuote(value) { return "'" + String(value).replace(/'/g, "'\\''") + "'"; }
function jsonReply(output) {
  for (const line of String(output).trim().split('\n').reverse()) {
    try { return JSON.parse(line); } catch {}
  }
  throw Error('The TV returned an unreadable reply. Check the connection and try again.');
}
function validPort(value) { return /^[0-9]+$/.test(value) && Number(value) > 0 && Number(value) <= 65535; }
function checksum(file) { return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'); }
function verifyFiles(directory) {
  const lines = fs.readFileSync(path.join(directory, 'SHA256SUMS'), 'utf8').trim().split('\n');
  for (const line of lines) {
    const match = /^([a-f0-9]{64})  ([a-zA-Z0-9][a-zA-Z0-9_.-]*)$/.exec(line);
    if (!match || checksum(path.join(directory, match[2])) !== match[1]) throw Error('Download verification failed. Download the installer again before continuing.');
  }
  return lines.length;
}
async function ask(question, fallback = '') {
  const rl = readline.createInterface({input: process.stdin, output: process.stdout});
  try {
    const value = await Promise.race([
      rl.question(question + (fallback ? ` [${fallback}]` : '') + ': '),
      new Promise((_, reject) => rl.once('SIGINT', () => reject(Error('Cancelled.')))),
    ]);
    return value.trim() || fallback;
  } finally { rl.close(); }
}
function run(program, args, {interactive = false, allowFailure = false, timeout = 60000, input, binary = false} = {}) {
  const result = cp.spawnSync(program, args, {
    stdio: interactive ? 'inherit' : ['pipe', 'pipe', 'pipe'], encoding: binary ? undefined : 'utf8', timeout,
    maxBuffer: 8 * 1024 * 1024, ...(input === undefined ? {} : {input}),
  });
  if (result.error || result.status !== 0) {
    const detail = result.error?.code === 'ETIMEDOUT' ? 'The command timed out.' :
      String(result.stderr || result.stdout || result.error?.message || 'Command failed.').trim().slice(-1400);
    if (!allowFailure) throw Error(detail);
    return {ok: false, output: '', error: detail};
  }
  return {ok: true, output: result.stdout || ''};
}
class Installer {
  constructor({root = ROOT, prompt = ask, execute = run, find = executable, log = console.log, wait = sleep,
    temporary = installer => new TemporaryRoot(installer)} = {}) {
    Object.assign(this, {root, prompt, execute, find, log, wait});
    this.device = null; this.ip = null; this.rootConnection = null;
    this.temporary = temporary; this.rootMethod = null;
  }
  async yes(question, fallback = 'n') {
    for (;;) {
      const answer = (await this.prompt(question + ' (y/n)', fallback)).toLowerCase();
      if (['y','yes'].includes(answer)) return true;
      if (['n','no'].includes(answer)) return false;
      this.log('Please enter y or n.');
    }
  }
  cli(tool, args, options) {
    const program = this.find(tool);
    if (!program) throw Error(`Missing ${tool}. Install @webos-tools/cli, then run this installer again.`);
    return this.execute(program, args, options);
  }
  async prerequisites() {
    const missing = CLI.filter(name => !this.find(name));
    if (missing.length) {
      this.log('The LG webOS command-line tools are missing or incomplete.');
      this.log('They can be installed with: npm install --global @webos-tools/cli');
      if (!await this.yes('Install these tools now?', 'y')) throw Error('Install the webOS tools, then run this installer again.');
      const npm = this.find('npm');
      if (!npm) throw Error('npm is missing. Reinstall Node.js LTS with npm from https://nodejs.org/en/download.');
      const result = this.execute(npm, ['install', '--global', '@webos-tools/cli'], {interactive:true, allowFailure:true, timeout:300000});
      if (!result.ok || CLI.some(name => !this.find(name))) throw Error('The webOS tools could not be installed. For npm permission errors, follow https://docs.npmjs.com/resolving-eacces-permissions-errors-when-installing-packages-globally . Reopen Terminal after installation.');
    }
    this.cli('ares-config', ['--profile', 'tv']);
  }
  async connect() {
    this.log('\nKeep the TV on and connect this computer to the same local network.');
    this.log('On the TV, sign in to Developer Mode and turn Dev Mode Status and Key Server on.');
    this.log('If Developer Mode is already enabled, leave it enabled.');
    for (;;) {
      this.ip = await this.prompt('TV IP address (shown in Developer Mode)');
      if (net.isIP(this.ip)) break;
      this.log('Enter an IPv4 or IPv6 address, for example 192.168.1.20.');
    }
    let port;
    do { port = await this.prompt('Developer Mode SSH port', '9922'); if (!validPort(port)) this.log('Enter a port number from 1 to 65535.'); } while (!validPort(port));
    const devices = JSON.parse(this.cli('ares-setup-device', ['--listfull']).output);
    if (!Array.isArray(devices)) throw Error('Unable to read saved webOS device connections. Run ares-setup-device to inspect them.');
    const existing = devices.find(d => d.deviceinfo?.ip === this.ip && Number(d.deviceinfo?.port) === Number(port) && d.deviceinfo?.user === 'prisoner');
    if (existing) { this.device = existing.name; this.log(`Using the saved connection: ${this.device}`); }
    else {
      const stem = 'sirimote-' + this.ip.replace(/[^a-zA-Z0-9]/g, '-');
      this.device = stem;
      for (let n = 2; devices.some(d => d.name === this.device); n++) this.device = stem + '-' + n;
      this.cli('ares-setup-device', ['--add', this.device, '--info', JSON.stringify({host:this.ip, port:String(Number(port)), username:'prisoner', description:'Magic Sirimote TV'})]);
    }
    for (let attempt = 0; attempt < 3; attempt++) {
      const result = this.cli('ares-device', ['--system-info', '--device', this.device], {allowFailure:true, timeout:20000});
      if (result.ok) { this.log('Connected to the TV.'); return; }
      this.log('The TV connection is not ready. Check its IP address, Developer Mode session, and network.');
      this.log('Turn Key Server ON in the TV Developer Mode app. The next prompt asks for the passphrase displayed there, not your LG account password.');
      if (!await this.yes('Get the connection key and retry?', 'y')) throw Error('Connection cancelled. Run the installer again when the TV is ready.');
      const key = this.cli('ares-novacom', ['--device', this.device, '--getkey'], {interactive:true, allowFailure:true, timeout:120000});
      if (!key.ok) this.log('Key retrieval failed. Recheck Key Server and the displayed passphrase.');
    }
    throw Error('Could not connect after three attempts. Check Developer Mode and the network, then run the installer again.');
  }
  remote(request) {
    const source = fs.readFileSync(path.join(this.root, 'tools/installer/tv.py'), 'utf8') +
      '\ntry:\n print(json.dumps(dispatch(json.loads(' + JSON.stringify(JSON.stringify(request)) + '))))' +
      '\nexcept Exception as error:\n print(json.dumps({"installerError":str(error)}))\n';
    const command = 'test -x /usr/bin/python3 || { echo "Python 3 is missing on this TV; this package needs Python 3.10 or newer." >&2; exit 1; }; /usr/bin/python3 -I -B -c ' + shellQuote(source);
    const reply = jsonReply(this.cli('ares-novacom', ['--device', this.device, '--run', command], {timeout:30000}).output);
    if (reply?.installerError) throw Error('TV: '+reply.installerError);
    return reply;
  }

  async stopInstalledApp() {
    this.log('Preparing the installed app for maintenance. Close any unsaved settings and wake Siri Remote.');
    await this.prompt('Press Return when ready');
    const nonce = crypto.randomBytes(16).toString('hex');
    this.remote({action:'maintenance', operation:'stop', nonce});
    this.cli('ares-launch', ['--device',this.device,APP,'--params',JSON.stringify({installerRequest:nonce})]);
    let stopped = false;
    for (let i = 0; i < 15; i++) {
      const receipt = this.remote({action:'maintenance-result', nonce});
      if (receipt.status === 'attention') throw Error('The app could not stop: '+(receipt.errorText || 'check its screen')+'. No package was changed.');
      // The app consumes installer requests on relaunch, not initial startup.
      // Retry only an unreceived request, with the same nonce so it executes once.
      if (receipt.status === 'not-received' && i > 0)
        this.cli('ares-launch', ['--device',this.device,APP,'--params',JSON.stringify({installerRequest:nonce})]);
      const state = this.remote({action:'status'});
      if (receipt.status === 'accepted' && receipt.action === 'stop' && state.returnValue && state.cleanStop && state.startup?.enabled === false) { stopped = true; break; }
      await this.wait(2000);
    }
    if (!stopped) throw Error('The app has not finished stopping. Wake Siri Remote and try again. No package was replaced.');
    this.cli('ares-launch', ['--device',this.device,'--close',APP]);
    for (let i = 0; i < 10; i++) {
      const state = this.remote({action:'status'});
      if (state.returnValue && state.cleanStop && state.startup?.enabled === false &&
          state.processes && Object.values(state.processes).every(rows => Array.isArray(rows) && rows.length === 0)) return;
      await this.wait(1000);
    }
    throw Error('An app process is still active. No package was replaced; wait and try again.');
  }
  async rootAccess() {
    if (this.rootConnection) return this.rootConnection;
    if (!this.find('ssh')) throw Error('OpenSSH is missing. Install the SSH client to use the optional TV-side fix.');
    this.log('This option requires an existing root SSH connection to the TV. It does not create root access.');
    let port;
    do { port = await this.prompt('Root SSH port (not the Developer Mode port)', '22'); if (!validPort(port)) this.log('Enter a valid SSH port.'); } while (!validPort(port));
    const key = await this.prompt('SSH private-key file, or Return for your usual SSH key/password');
    this.sshTemp = fs.mkdtempSync(path.join(os.tmpdir(), 'sirimote-ssh-'));
    const args = ['-S',path.join(this.sshTemp,'connection'),'-o','ControlMaster=auto','-o','ControlPersist=120',
      '-p',String(Number(port)),'-o','ConnectTimeout=15'];
    if (key) {
      const expanded = key.startsWith('~/') ? path.join(os.homedir(), key.slice(2)) : path.resolve(key);
      if (!fs.existsSync(expanded) || !fs.statSync(expanded).isFile()) throw Error('The SSH private-key file was not found.');
      args.push('-i', expanded);
    }
    args.push('root@'+this.ip);
    this.rootConnection = args;
    this.log('SSH may ask you to confirm the TV host key or enter its root password.');
    const result = this.execute(this.find('ssh'), [...args, 'test "$(id -u)" = 0'], {interactive:true, allowFailure:true, timeout:120000});
    if (!result.ok) throw Error('Root SSH connection failed. Check the port and credentials; the Developer Mode passphrase is not a root password.');
    this.rootConnection = args;
    return args;
  }
  async rootMode() {
    if (this.rootMethod) return this.rootMethod;
    this.log('1: Temporary access through Developer Mode (no root SSH setup).');
    this.log('2: Use an existing root SSH connection.');
    this.log('Temporary access depends on TV capabilities and may be blocked by a firmware update. It does not install permanent root access.');
    for (;;) {
      const choice = await this.prompt('TV access method', '1');
      if (['1','2'].includes(choice)) return this.rootMethod = choice === '1' ? 'temporary' : 'ssh';
      this.log('Choose 1 or 2.');
    }
  }
  async tvFix(action) {
    if (action === 'remove') {
      const result = await this.guard('remove');
      if (result.state === 'installed') throw Error('TV-side fix is still installed.');
      return result;
    }
    if (await this.rootMode() === 'temporary') return this.temporary(this).run('apply');
    const args = await this.rootAccess();
    const directory = path.join(this.root, 'tools/hid-guard');
    verifyFiles(directory);
    const files = fs.readFileSync(path.join(directory,'SHA256SUMS'),'utf8').trim().split('\n').map(line => line.slice(66));
    const packed = this.execute(this.find('tar'), ['-czf','-','-C',directory,'SHA256SUMS',...files], {binary:true}).output;
    const command = 'set -eu; umask 077; d=$(mktemp -d /tmp/sirimote-guard.XXXXXX); trap \'rm -rf "$d"\' EXIT; tar -xzf - -C "$d"; /usr/bin/python3 -I -B "$d/install.py" --check; /usr/bin/python3 -I -B "$d/install.py" --apply';
    // Authentication was checked interactively; fail instead of hiding another password prompt behind the pipe.
    this.execute(this.find('ssh'), ['-o','BatchMode=yes',...args,command], {input:packed, timeout:120000});
  }
  async guard(action) {
    if (await this.rootMode() === 'temporary') return this.temporary(this).run(action);
    const args = await this.rootAccess();
    const source = fs.readFileSync(path.join(this.root,'tools/installer/guard_remove.py'),'utf8') +
      '\ntry:\n print(json.dumps(dispatch('+JSON.stringify(action)+')))'+
      '\nexcept Exception as error:\n print(json.dumps({"error":str(error)+" "+(getattr(error,"stderr","") or "")[-600:]}))\n';
    const result = this.execute(this.find('ssh'), ['-o','BatchMode=yes',...args,'/usr/bin/python3 -I -B -'], {input:source,timeout:65000});
    const reply = jsonReply(result.output);
    if (reply.error) throw Error(reply.error);
    if (!['absent','installed','removed'].includes(reply.state)) throw Error('Could not verify the TV-side fix state.');
    return reply;
  }
  appRegistered() {
    const listing = this.cli('ares-install',['--device',this.device,'--list']).output;
    return String(listing).split(/\r?\n/).some(line => line.trim().split(/\s/)[0] === APP);
  }
  async uninstall() {
    this.log('This removes Magic Sirimote and its TV-side input-device fix if installed. Remote pairing and IR assignments are kept; use Reset app first to erase them.');
    if (!await this.yes('Remove the app and its TV-side fix from this TV?')) return;
    this.log('Developer Mode can hide TV-side system files. Temporary root access or existing root SSH is needed to check and remove the fix reliably.');
    let guard;
    try {
      if (!await this.yes('Check and clean up the TV-side fix with root access?', 'y')) throw Error('TV-side fix was not checked.');
      guard = await this.guard('inspect');
    } catch (error) {
      this.log('TV-side cleanup could not be prepared: '+error.message);
      if (!await this.yes('Remove only the app and leave TV-side cleanup incomplete?')) throw Error('Uninstall cancelled; the app was not removed. '+error.message);
    }
    const info = this.remote({action:'removal-info'});
    const present = info.appPresent || this.appRegistered();
    if (info.appPresent) await this.stopInstalledApp();
    if (guard?.state === 'installed') {
      this.log('TV-side fix found. Removing it and restoring the input service...');
      let removed;
      try { removed = await this.guard('remove'); }
      catch (error) { throw Error('TV-side cleanup failed; the app has not been removed. '+error.message); }
      if (!['removed','absent'].includes(removed.state)) throw Error('TV-side fix remains installed. The app was not removed.');
    } else if (guard) this.log('No TV-side fix is installed.');
    if (present) this.cli('ares-install',['--device',this.device,'--remove',APP],{interactive:true,timeout:120000});
    for (let attempt=0; attempt<15; attempt++) {
      if (!this.appRegistered() && !this.remote({action:'removal-info'}).appPresent) {
        if (!guard) throw Error('App removed. TV-side cleanup is INCOMPLETE: its presence could not be verified. Run sh uninstall.sh again when temporary root or root SSH is available.');
        this.log('Uninstall complete: app removed; TV-side fix removed or confirmed absent. The TV was not rebooted.');
        return;
      }
      await this.wait(1000);
    }
    throw Error('App removal is not yet confirmed. Wait for the TV to finish, then run sh uninstall.sh again.');
  }
  cleanup() {
    try {
      if (this.rootConnection) this.execute(this.find('ssh'), ['-O','exit',...this.rootConnection], {allowFailure:true,timeout:5000});
    } catch { /* ControlPersist also bounds the SSH session if cleanup fails. */ }
    if (this.sshTemp) fs.rmSync(this.sshTemp,{recursive:true,force:true});
    this.rootConnection = null; this.sshTemp = null;
  }
  async run(mode) {
    try { return await this.steps(mode); } finally { this.cleanup(); }
  }
  async steps(mode) {
    this.log(mode === '2' ? 'Magic Sirimote uninstaller\n' : 'Magic Sirimote installer\n');
    await this.prerequisites();
    mode = mode || await this.prompt('1: Install/update app   2: Remove app and TV-side fix   3: Remove TV-side fix only', '1');
    if (!['1','2','3','check'].includes(mode)) throw Error('Choose 1, 2, or 3.');
    await this.connect();
    if (mode === '3') { await this.tvFix('remove'); this.log('TV-side cleanup complete. The TV was not rebooted.'); return; }
    if (mode === '2') return this.uninstall();
    const info = this.remote({action:'probe'});
    if (['1','check'].includes(mode) && info.missing?.length) throw Error('The TV is missing capabilities needed by this package:\n- '+info.missing.join('\n- ')+'\nNo model or firmware allowlist is used.');
    if (mode === 'check') { this.log('Required runtime libraries and architecture are available. No app or TV-side fix was changed.'); return; }
    verifyFiles(path.join(this.root,'releases'));
    const manifest = JSON.parse(fs.readFileSync(path.join(this.root,'releases/manifest.json'),'utf8'));
    if (checksum(path.join(this.root,'releases/org.magicsirimote.app_arm.ipk')) !== manifest.package.packageSha256) throw Error('The package and manifest do not match. Download again.');
    this.log('Package download verified.');
    if (info.appPresent) await this.stopInstalledApp();
    this.cli('ares-install', ['--device',this.device,path.join(this.root,'releases/org.magicsirimote.app_arm.ipk')], {interactive:true, timeout:120000});
    const verified = this.remote({action:'verify', files:manifest.package.files});
    if (!Array.isArray(verified.mismatch) || verified.mismatch.length || verified.verifiedFiles !== Object.keys(manifest.package.files).length) throw Error('Installed-file verification failed. Run the installer again; the app was not launched.');
    this.log('App installed and verified.');
    this.log('\nOptional: prevent input loss after repeated Bluetooth reconnections. This changes LG\'s handling of A1513/A1962 outside the app and briefly restarts the input service, not the TV.');
    let fix = 'not requested (an existing fix, if any, was left unchanged)';
    if (await this.yes('Apply the TV-side fix?')) {
      try { await this.tvFix('apply'); fix = 'applied'; }
      catch (error) { fix = 'not completed'; this.log('The app is installed, but the optional TV-side fix failed:\n'+error.message+'\nYou can rerun this installer later.'); }
    }
    this.cli('ares-launch', ['--device',this.device,APP], {interactive:true});
    this.log('\nInstallation complete. TV-side fix: '+fix+'.');
    this.log('On the TV choose Start pairing, then hold Siri Remote MENU + Volume Up for about 5 seconds.');
    this.log('Pairing starts automatically. If settings open instead, the app found your saved pairing.');
    this.log('Choose your button assignments and Save and restart. This installer does not reboot the TV.');
  }
}
if (require.main === module) {
  const args = process.argv.slice(2);
  if (args.includes('--help')) { console.log(args.includes('--uninstall') ? 'Usage: sh uninstall.sh\nInteractively remove the app and its TV-side fix if installed.' : 'Usage: sh install.sh [--check | --uninstall]\nRun without options to install/update or remove. --check checks the connection and TV runtime only.'); }
  else if (args.some(arg => !['--check','--uninstall'].includes(arg)) || (args.includes('--check') && args.includes('--uninstall'))) { console.error('Unknown option. Use sh install.sh --help.'); process.exitCode = 1; }
  else if (!process.stdin.isTTY) { console.error('Run this interactive tool in Terminal: sh '+(args.includes('--uninstall')?'uninstall.sh':'install.sh')); process.exitCode = 1; }
  else new Installer().run(args.includes('--uninstall') ? '2' : args.includes('--check') ? 'check' : undefined).catch(error => { console.error('\n'+error.message); process.exitCode = 1; });
}
module.exports = {Installer, executable, shellQuote, jsonReply, validPort, verifyFiles, run};
