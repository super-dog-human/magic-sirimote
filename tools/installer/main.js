'use strict';
// The shell entry point downloads one revision; this driver uses only Node built-ins.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const cp = require('node:child_process'), net = require('node:net'), os = require('node:os');
const readline = require('node:readline/promises');
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
  constructor({root = ROOT, prompt = ask, execute = run, find = executable, log = console.log, wait = sleep} = {}) {
    Object.assign(this, {root, prompt, execute, find, log, wait});
    this.device = null; this.ip = null; this.rootConnection = null;
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
      const state = this.remote({action:'status'});
      if (state.returnValue && state.cleanStop && state.startup?.enabled === false) { stopped = true; break; }
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
  async tvFix(action) {
    const args = await this.rootAccess();
    if (action === 'remove') {
      this.execute(this.find('ssh'), [...args, 'if [ -f /var/lib/magic-sirimote-hid-guard/rollback.py ]; then /usr/bin/python3 -I -B /var/lib/magic-sirimote-hid-guard/rollback.py; else printf "%s\\n" "No TV-side fix is installed."; fi'], {interactive:true, timeout:120000});
      return;
    }
    const directory = path.join(this.root, 'tools/hid-guard');
    verifyFiles(directory);
    const files = fs.readFileSync(path.join(directory,'SHA256SUMS'),'utf8').trim().split('\n').map(line => line.slice(66));
    const packed = this.execute(this.find('tar'), ['-czf','-','-C',directory,'SHA256SUMS',...files], {binary:true}).output;
    const command = 'set -eu; umask 077; d=$(mktemp -d /tmp/sirimote-guard.XXXXXX); trap \'rm -rf "$d"\' EXIT; tar -xzf - -C "$d"; /usr/bin/python3 -I -B "$d/install.py" --check; /usr/bin/python3 -I -B "$d/install.py" --apply';
    // Authentication was checked interactively; fail instead of hiding another password prompt behind the pipe.
    this.execute(this.find('ssh'), ['-o','BatchMode=yes',...args,command], {input:packed, timeout:120000});
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
    this.log('Magic Sirimote installer\n');
    await this.prerequisites();
    mode = mode || await this.prompt('1: Install/update app   2: Remove app   3: Remove TV-side fix only', '1');
    if (!['1','2','3','check'].includes(mode)) throw Error('Choose 1, 2, or 3.');
    await this.connect();
    if (mode === '3') { await this.tvFix('remove'); this.log('TV-side cleanup complete. The TV was not rebooted.'); return; }
    const info = this.remote({action:'probe'});
    if (['1','check'].includes(mode) && info.missing?.length) throw Error('The TV is missing capabilities needed by this package:\n- '+info.missing.join('\n- ')+'\nNo model or firmware allowlist is used.');
    if (mode === 'check') { this.log('Required runtime libraries and architecture are available. No app or TV-side fix was changed.'); return; }
    if (mode === '2') {
      this.log('Removing the app keeps its TV pairing and remote IR assignments. Use Reset app on the TV first if you also want to erase those.');
      if (!await this.yes('Remove Magic Sirimote from this TV?')) return;
      if (info.appPresent) await this.stopInstalledApp();
      if (await this.yes('Remove the optional TV-side fix using root SSH too?')) await this.tvFix('remove');
      if (info.appPresent) this.cli('ares-install', ['--device',this.device,'--remove',APP], {interactive:true,timeout:120000});
      this.log('App removal complete. If you skipped TV-side cleanup, an installed TV-side fix remains active.');
      return;
    }
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
    if (await this.yes('Apply the TV-side fix using an existing root SSH connection?')) {
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
  if (args.includes('--help')) { console.log('Usage: sh install.sh [--check]\nRun without options to install/update or remove. --check checks the connection and TV runtime only.'); }
  else if (args.some(arg => arg !== '--check')) { console.error('Unknown option. Use sh install.sh --help.'); process.exitCode = 1; }
  else if (!process.stdin.isTTY) { console.error('Run this interactive installer in Terminal: sh install.sh'); process.exitCode = 1; }
  else new Installer().run(args.includes('--check') ? 'check' : undefined).catch(error => { console.error('\n'+error.message); process.exitCode = 1; });
}
module.exports = {Installer, executable, shellQuote, jsonReply, validPort, verifyFiles, run};
