'use strict';
// One scoped operation through the TV's existing browser/LS2 capabilities.
// No model allowlist, root SSH server, persistent service, or downloaded payload.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const http = require('node:http'), dgram = require('node:dgram'), net = require('node:net'), zlib = require('node:zlib');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const quote = value => "'" + String(value).replace(/'/g, "'\\''") + "'";
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const address = value => value.replace(/^::ffff:/, '');

async function localAddress(ip) {
  const socket = dgram.createSocket(net.isIP(ip) === 6 ? 'udp6' : 'udp4');
  try {
    await new Promise((resolve, reject) => {
      socket.once('error', reject); socket.connect(9922, ip, resolve);
    });
    return socket.address().address;
  } finally { socket.close(); }
}
function config(run = crypto.randomBytes(12).toString('hex')) {
  if (!/^[a-f0-9]{24}$/.test(run)) throw Error('Invalid temporary service identifier.');
  return {run, token:crypto.randomBytes(24).toString('hex'),
    dir:'/media/developer/temp/magic-sirimote-root-'+run,
    service:'org.magicsirimote.maintenance.r'+run};
}
function payload(root, action) {
  if (!['inspect','remove','apply'].includes(action)) throw Error('Unknown TV-side operation.');
  const guard = fs.readFileSync(path.join(root,'tools/installer/guard_remove.py'),'utf8');
  if (action !== 'apply') return guard+'\nresult=dispatch('+JSON.stringify(action)+')\n';
  const directory = path.join(root,'tools/hid-guard');
  const manifest = fs.readFileSync(path.join(directory,'SHA256SUMS'),'utf8');
  const files = {'SHA256SUMS':Buffer.from(manifest).toString('base64')};
  for (const line of manifest.trim().split('\n')) {
    const match = /^([a-f0-9]{64})  ([a-zA-Z0-9][a-zA-Z0-9_.-]*)$/.exec(line);
    if (!match) throw Error('Invalid TV-side fix manifest.');
    const data = fs.readFileSync(path.join(directory,match[2]));
    if (hash(data) !== match[1]) throw Error('TV-side fix download verification failed.');
    files[match[2]] = data.toString('base64');
  }
  return guard+`
import base64,tempfile
result=dispatch('inspect')
if result['state']=='absent':
 with tempfile.TemporaryDirectory(prefix='sirimote-guard-') as temp:
  folder=Path(temp)
  for name,value in json.loads(${JSON.stringify(JSON.stringify(files))}).items():
   (folder/name).write_bytes(base64.b64decode(value,validate=True))
  (folder/'guard_probe_arm').chmod(0o755)
  for option in ('--check','--apply'):
   subprocess.run([sys.executable,'-I','-B',str(folder/'install.py'),option],capture_output=True,text=True,timeout=45,check=True)
  result=dispatch('inspect')
  if result['state']!='installed':raise RuntimeError('TV-side fix installation was not confirmed')
  result['applied']=True
else:
 result['alreadyInstalled']=True
`;
}
class TemporaryRoot {
  constructor(installer, {route = localAddress, wait = sleep, now = Date.now} = {}) {
    this.installer=installer; this.root=installer.root; this.route=route; this.wait=wait; this.now=now;
  }
  remote(request) {
    const code = fs.readFileSync(path.join(this.root,'tools/installer/temporary_tv.py'),'utf8')+
      '\ntry:\n print(json.dumps(dispatch(json.loads('+JSON.stringify(JSON.stringify(request))+'))))'+
      '\nexcept Exception as error:\n print(json.dumps({"error":str(error)}))\n';
    // Avoid argv limits for the bundled fix. No tar or Mac resource forks.
    const packed = zlib.deflateSync(Buffer.from(code)).toString('base64');
    const command = '/usr/bin/python3 -I -B -c '+quote("import base64,zlib;exec(zlib.decompress(base64.b64decode('"+packed+"')))");
    const output = this.installer.cli('ares-novacom',['--device',this.installer.device,'--run',command],{timeout:15000}).output;
    let result;
    for (const line of String(output).trim().split('\n').reverse()) { try { result=JSON.parse(line); break; } catch {} }
    if (!result || result.error) throw Error(result?.error || 'Temporary service returned an unreadable reply.');
    return result;
  }
  assets(c, action) {
    const runner=fs.readFileSync(path.join(this.root,'tools/installer/temporary_runner.py'),'utf8')+
      '\nexecute('+JSON.stringify(c.dir)+','+JSON.stringify(c.run)+')\n';
    return {'runner.py':runner,'operation.py':payload(this.root,action),
      'probe.service':`[D-BUS Service]\nName=${c.service}\nExec=/usr/bin/python3 -I -B ${c.dir}/runner.py\nType=dynamic\n`,
      'manifests/probe.json':JSON.stringify({id:c.service+'.manifest',version:'1.0.0',serviceFiles:['probe.service']})+'\n'};
  }
  async run(action) {
    if (!['inspect','remove','apply'].includes(action)) throw Error('Unknown TV-side operation.');
    this.installer.log('Using temporary TV access. Keep this computer reachable from the TV; allow local network access if macOS asks.');
    const local=await this.route(this.installer.ip);
    // Resolve an interrupted previous operation first. This only unregisters it.
    const previous=this.remote({action:'list'});
    if (!Array.isArray(previous.runs) || previous.runs.length>10) throw Error('Unexpected temporary service inventory.');
    for (const run of previous.runs) {
      this.installer.log('Cleaning up an interrupted temporary operation...');
      await this.session({...config(run),cleanupOnly:true},local);
    }
    const c=config(), files=this.assets(c,action);
    const staged=this.remote({action:'stage',run:c.run,
      files:Object.fromEntries(Object.entries(files).map(([name,data])=>[name,Buffer.from(data).toString('base64')]))});
    if (JSON.stringify(staged.hashes)!==JSON.stringify(Object.fromEntries(Object.entries(files).map(([name,data])=>[name,hash(data)])))) {
      this.remote({action:'cleanup',run:c.run});
      throw Error('Temporary service transfer verification failed.');
    }
    return this.session(c,local);
  }
  async session(c, local) {
    let served=false, removed=false, finish=!!c.cleanupOnly, receipt=null, cancelled=false, error=null;
    const events=[], deadline=this.now()+85000;
    const page=fs.readFileSync(path.join(this.root,'tools/installer/temporary-root-page.html'),'utf8').replace('__CONFIG__',JSON.stringify(c));
    const server=http.createServer((req,res)=>{
      const send=(code,value,type='application/json')=>{res.writeHead(code,{'Content-Type':type,'Cache-Control':'no-store'});res.end(value);};
      if (address(req.socket.remoteAddress || '')!==address(this.installer.ip) || this.now()>deadline)
        return send(404,'');
      if (req.method==='GET' && req.url===`/${c.token}/index.html`) {
        served=true; return send(200,page,'text/html; charset=utf-8');
      }
      if (req.method==='GET' && req.url===`/${c.token}/status`) return send(200,JSON.stringify({finish}));
      if (req.method!=='POST' || req.url!==`/${c.token}/event`) return send(404,'');
      let body=''; req.setTimeout(3000,()=>req.destroy());
      req.on('data',chunk=>{body+=chunk;if (body.length>8192) req.destroy();});
      req.on('end',()=>{
        try {
          const event=JSON.parse(body);
          if (event.run!==c.run || events.length>=40) return send(400,'');
          events.push(event);
          if (event.kind==='removed' && event.detail?.returnValue===true) removed=true;
          if (event.kind==='not-registered' && events.some(e=>e.kind==='preflight' && e.detail?.returnValue===false)) removed=true;
          if (['error','remove-failed'].includes(event.kind) ||
              (['preflight','registered'].includes(event.kind) && event.detail?.returnValue!==true)) finish=true;
          send(200,'{}');
        } catch { send(400,''); }
      });
    });
    server.requestTimeout=5000; server.headersTimeout=5000;
    const cancel=()=>{cancelled=true;this.installer.log('Cancelling; waiting for the bounded operation and temporary-service cleanup...');};
    process.on('SIGINT',cancel); process.on('SIGTERM',cancel);
    try {
      await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,local,resolve);});
      const host=net.isIP(local)===6?'['+local+']':local;
      this.installer.cli('ares-launch',['--device',this.installer.device,'com.webos.app.tinybrowser','--params',
        JSON.stringify({contentTarget:`http://${host}:${server.address().port}/${c.token}/index.html`})],{timeout:20000});
      while (this.now()<deadline && !removed) {
        await this.wait(500);
        if (!c.cleanupOnly && !receipt && events.some(e=>e.kind==='registered' && e.detail?.returnValue===true)) {
          try {
            const value=this.remote({action:'report',run:c.run});
            if (!value.pending) {receipt=value;finish=true;}
          } catch (e) {error=e;}
        }
        if (!served && this.now()>deadline-60000) {error=Error('The TV could not open the setup page. Check the Mac firewall and local network.');break;}
      }
    } catch (e) {
      error=e;
      // A failed launcher can still have opened the page. Give its independent
      // cleanup timer and HTTP callbacks time to finish before deleting files.
      while (server.listening && this.now()<deadline && !removed) await this.wait(500);
    } finally {
      process.removeListener('SIGINT',cancel); process.removeListener('SIGTERM',cancel);
      await new Promise(resolve=>{server.closeAllConnections();server.close(resolve);});
    }
    if (!removed && served) throw Error('Temporary-service cleanup could not be confirmed. Keep Developer Mode enabled and rerun the installer to finish cleanup. No success is reported.');
    this.remote({action:'cleanup',run:c.run});
    if (cancelled) throw Error('Cancelled; temporary files and registration were removed.');
    if (error) throw error;
    if (c.cleanupOnly) return {cleaned:true};
    if (!receipt || receipt.owner!==0 || receipt.report?.rootUid!==0 || receipt.report?.run!==c.run || receipt.report?.sameBoot!==true)
      throw Error('Temporary root is unavailable on this TV. Check the setup screen/network, or choose an existing root SSH connection when rerunning.');
    if (receipt.report.error) throw Error(receipt.report.error);
    if (!['absent','installed','removed'].includes(receipt.report.result?.state)) throw Error('Temporary operation did not confirm the TV-side fix state.');
    return receipt.report.result;
  }
}
module.exports={TemporaryRoot,config,payload,localAddress};
