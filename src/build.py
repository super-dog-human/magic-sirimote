#!/usr/bin/env python3
"""Build three local IPKs; never contact, install on, or change a TV."""
import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
import build_support as pkg

ROOT = Path(__file__).resolve().parent
A = 'org.codex.siriremote.autocoord20261029v'
B = 'org.codex.siriremote.hidgattrouterb20261029u'
S = 'org.codex.siriremote.v20scheduler20261031a'
PAIR_VERSION = '0.9.102'
SCHEDULER_VERSION = '0.0.95'
APP_ROOT = '/media/developer/apps/usr/palm/applications/'
EXAMPLES = {'remoteAddress':'02:00:00:00:00:01', 'adapterAddress':'02:00:00:00:00:02',
            'remoteName':'EXAMPLE_REMOTE_SERIAL'}
BASE_UIDS = {'developerUid':5415, 'controllerUid':6959, 'receiverUid':5636}
SERVICE_FILES = ('service.js','callback-admission.js','runtime-bridge.js','callback.js',
 'rotation-store.js','strict-json.js','transport.js','boot-claim-store.js','boot-evidence.js',
 'continuity-marker.js','coordinator-launcher.js','pins.js','private-directory.js','service-entry.js',
 'expiry.js','expiry-query.py','expiry-policy.js','standby-resume.js','resume-evidence.py','creator.js',
 'state-summary.js','native-checker.js','wake-checker.js','power-read.py')
APP_FILES = ('main.js','creator.js','strict-json.js','pins.js','private-directory.js',
 'public-status.js','diagnose.js','rearm.js','rearm-request.js','expiry-request.js',
 'native-checker.js','resume-evidence.py','standby-resume.js')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def js(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode()


def load_config(path, example=False):
    def unique(pairs):
        out = {}
        for k,v in pairs:
            if k in out: raise ValueError('Duplicate configuration key: '+k)
            out[k] = v
        return out
    q = json.loads(Path(path).read_text(), object_pairs_hook=unique)
    fields = {'schema', *EXAMPLES, *BASE_UIDS, 'devmodeMaintenance'}
    if type(q) is not dict or set(q) != fields or type(q['schema']) is not int or q['schema'] != 1:
        raise ValueError('Configuration must have exactly the fields in config.example.json')
    for k in ('remoteAddress','adapterAddress'):
        if type(q[k]) is not str or not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', q[k]):
            raise ValueError(k+' must be a lowercase Bluetooth address')
        if int(q[k][:2],16)&1 or q[k]=='00:00:00:00:00:00':
            raise ValueError(k+' must be a nonzero unicast address')
    if q['remoteAddress']==q['adapterAddress']: raise ValueError('Remote and adapter must differ')
    if type(q['remoteName']) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',q['remoteName']):
        raise ValueError('remoteName must be the exact observed name/serial (ASCII letters, digits, _ or -)')
    if not example and any(q[k]==v for k,v in EXAMPLES.items()):
        raise ValueError('Replace all example device identities, or use --example for offline inspection')
    if any(type(q[k]) is not int or not 1<=q[k]<=65535 for k in BASE_UIDS):
        raise ValueError('UIDs must be measured positive integers')
    if len({q[k] for k in BASE_UIDS})!=3: raise ValueError('Three distinct role UIDs are required')
    if q['devmodeMaintenance'] not in ('disabled','check-only','extend'):
        raise ValueError('Invalid devmodeMaintenance setting')
    return q


def configured(text, config):
    for key, old in EXAMPLES.items(): text=text.replace(old,config[key])
    # Substitute whole integer literals simultaneously, never substrings of hashes.
    mapping={str(v):str(config[k]) for k,v in BASE_UIDS.items()}
    pattern=r'(?<![A-Za-z0-9_])(?:'+ '|'.join(mapping) + r')(?![A-Za-z0-9_])'
    return re.sub(pattern,lambda m:mapping[m.group()],text).encode()


def package(out, app, version, files, service=None):
    root='usr/palm/applications/'+app
    info_root='usr/palm/packages/'+app
    info=js({'id':app,'version':version,'app':app,'services':[app+'.service'] if service else []})
    content={root+'/'+n:v for n,v in files.items()}
    content[info_root+'/packageinfo.json']=info
    if service:
        content.update({'usr/palm/services/'+app+'.service/'+n:v for n,v in service.items()})
    dirs=set()
    for name in content:
        dirs.update(str(p) for p in Path(name).parents if str(p)!='.')
    modes={p:(0o755 if p==root+'/entry' else 0o666 if p==info_root+'/packageinfo.json' else 0o644) for p in content}
    modes.update({p:0o755 for p in dirs}); modes[root+'/state']=0o770
    owners={p:(5999,5000) for p in content}
    owners[info_root+'/packageinfo.json']=(501,20)
    owners.update({p:(501,20) for p in dirs}); owners[root]=owners[root+'/state']=(5999,5000)
    control=(f'Package: {app}\nVersion: {version}\nArchitecture: arm\n'
             'Maintainer: magic-sirimote contributors\nDescription: Experimental TV-local Siri Remote runtime\n').encode()
    raw=pkg.make_ar({'debian-binary':b'2.0\n',
        'control.tar.gz':pkg.tar_gz({'control':control},set(),{'control':0o644},{'control':(0,0)}),
        'data.tar.gz':pkg.tar_gz(content,dirs,modes,owners)})
    parts=pkg.read_ar(raw); inventory=pkg.inspect_tgz(parts['data.tar.gz'])
    if {i['path'] for i in inventory}!=set(content)|dirs: raise ValueError('Package inventory mismatch')
    name=f'{app}_{version}_arm.ipk'; (out/name).write_bytes(raw)
    return {'appId':app,'package':name,'packageSha256':digest(raw),
            'pin':{'appId':app,'files':{k:digest(v) for k,v in files.items()},'packageInfoSha256':digest(info)},
            'files':{k:digest(v) for k,v in content.items()}}


def appinfo(app,version,acg):
    return js({'id':app,'version':version,'type':'native','main':'entry','title':'Magic Sirimote',
        'icon':'icon.png','noWindow':True,'noSplashOnLaunch':True,'spinnerOnLaunch':False,'requiredACG':acg})


def launcher(out,app,node=False):
    directory=out/('launcher-'+app); (directory/'app').mkdir(parents=True)
    pkg.APP_PATH=APP_ROOT+app
    (pkg.node_launcher if node else pkg.arm_launcher)(directory)
    return (directory/'app/entry').read_bytes()


def build(config,out,example=False):
    out=Path(out).resolve()
    if out.exists(): raise ValueError('Output already exists; choose a new directory')
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.magic-build-',dir=out.parent) as temp:
        dest=Path(temp)/'result';dest.mkdir()
        names=json.loads((ROOT/'runtime-files.json').read_text())
        if (not isinstance(names,list) or not names or len(set(names))!=len(names) or
            any(type(n) is not str or re.fullmatch(r'[a-z][a-z0-9_]*\.py',n) is None for n in names)):
            raise ValueError('Invalid runtime source inventory')
        if set(names)!={p.name for p in (ROOT/'runtime').glob('*.py')}:
            raise ValueError('Runtime source inventory differs from checkout')
        sources={name:configured((ROOT/'runtime'/name).read_text(),config) for name in names}
        def pair(app,entry,extra=None):
            files=dict(sources)
            identity=b'org.codex.siriremote.hidgattroutera20261029u'
            if files['native_app_identity.py'].count(identity)!=1:raise ValueError('Native identity changed')
            files['native_app_identity.py']=files['native_app_identity.py'].replace(identity,app.encode())
            wrapper=("import os,sys,traceback\nroot=os.path.dirname(os.path.realpath(__file__))\nsys.path.insert(0,root)\ntry:\n"
                f" from {entry} import main\n code=main()\n"
                "except Exception:\n text=traceback.format_exc()[-4000:]\n try:\n"
                "  p=os.path.join(root,'state','startup-error.txt')\n"
                "  fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o640)\n"
                "  os.write(fd,text.encode());os.close(fd)\n except Exception: pass\n raise\nraise SystemExit(code)\n")
            compile(wrapper,'native_probe.py','exec')
            files.update({'native_probe.py':wrapper.encode(),'entry':launcher(dest,app),'icon.png':pkg.icon_png(),
                'appinfo.json':appinfo(app,PAIR_VERSION,['bluetooth.query','application.launcher'] if app==A else ['bluetooth.query']),
                'state/README.txt':b'Runtime state. Never commit, reset, or copy between TVs.\n'})
            if extra: files.update(extra)
            return package(dest,app,PAIR_VERSION,files)
        a=pair(A,'resident_controller_entry')
        b=pair(B,'postconnect_receiver_native_entry',{'controller-pin.json':js(a['pin'])})
        pins=b"'use strict';module.exports="+js({'controller':a['pin'],'receiver':b['pin']}).rstrip()+b';\n'
        def scheduler_file(name):
            if name=='pins.js':return pins
            text=(ROOT/'scheduler'/name).read_text()
            if name=='expiry-policy.js':text=text.replace("'disabled'",repr(config['devmodeMaintenance']),1)
            return configured(text,config)
        files={n:scheduler_file(n) for n in APP_FILES}
        files.update({'entry':launcher(dest,S,node=True),'icon.png':pkg.icon_png(),
            'appinfo.json':appinfo(S,SCHEDULER_VERSION,['activity.operation','application.launcher','configurator.callbacks']),
            'state/README.txt':b'Initial provisioning requires explicit intent. Retain creator receipts.\n'})
        service={n:scheduler_file(n) for n in SERVICE_FILES}
        service['package.json']=js({'name':S+'.service','version':SCHEDULER_VERSION,'main':'service-entry.js'})
        service['services.json']=js({'id':S+'.service','services':[{'name':S+'.service'}],
            'requiredACG':['activity.operation','application.launcher','configurator.callbacks']})
        s=package(dest,S,SCHEDULER_VERSION,files,service)
        manifest={'schema':1,'exampleOnly':example,'hardwareValidatedPublicBuild':False,
            'configuration':config,'controller':a,'receiver':b,'scheduler':s,
            'note':'Build only. See README and docs/PORTING.md before any device operation.'}
        (dest/'manifest.json').write_bytes(js(manifest))
        (dest/'SHA256SUMS').write_text(''.join(f"{v['packageSha256']}  {v['package']}\n" for v in (a,b,s)))
        dest.rename(out)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--example',action='store_true',help='Allow fake device identities; never install this output')
    args=parser.parse_args()
    try:
        q=load_config(args.config,args.example);m=build(q,args.out,args.example)
    except (ValueError,OSError) as e:parser.exit(2,str(e)+'\n')
    print('Built three IPKs at',args.out)
    print('Example-only.' if args.example else 'Configured build; hardware validation still required.')
    print('No TV contacted. No software installed. No startup Activity registered.')

if __name__=='__main__':main()
