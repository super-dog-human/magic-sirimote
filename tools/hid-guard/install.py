"""Apply the authorized persistent, service-specific guard; retain exact rollback.

No shell/root login listener, firmware writes, boot hook, Bluetooth reset, or TV reboot.
Uses the vendor unit's existing EnvironmentFile on persistent /var.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

FIX_DIR=Path('/var/lib/magic-sirimote-hid-guard')
FIX_LIB=FIX_DIR/'libsirimote-hid-guard.so'
ENV_FILE=Path('/var/systemd/system/env/bthidmanager.env')
ENV_CONTENT='LD_PRELOAD='+str(FIX_LIB)+'\n'
BINARY_SHA='c1cd44fa5ea7d3a22cf4d05472021622e223762fab0722e9bd28824879e56272'
UNIT_SHA='8f36be4849018e2566275c76325ae7537b2fc76a45671d3f5fd0696fcca0b1a4'
UNIT='bthidmanager.service'
LIBRARY_SHA='bdab4c27472e3c7a0f07e262d2190b4e39e75a596ec7a5b9e159812cf6071fff'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def props():
    fields=['MainPID','ActiveState','SubState','PartOf','BoundBy','ConsistsOf',
            'PropagatesStopTo','EnvironmentFiles','DropInPaths']
    p=subprocess.run(['/bin/systemctl','show',UNIT]+['--property='+x for x in fields],
                     capture_output=True,text=True,timeout=5,check=True)
    return dict(x.split('=',1) for x in p.stdout.splitlines() if '=' in x)


def validate_properties(p):
    if p.get('ActiveState')!='active' or not p.get('MainPID','').isdigit() or int(p['MainPID'])<=1:
        raise RuntimeError('Service is not active')
    if any(p.get(k) for k in ['PartOf','BoundBy','ConsistsOf','PropagatesStopTo','DropInPaths']):
        raise RuntimeError('Unexpected restart dependencies or overrides')
    if p.get('EnvironmentFiles')!=str(ENV_FILE)+' (ignore_errors=yes)':
        raise RuntimeError('Vendor EnvironmentFile changed')


def persistent_var(mountinfo):
    matches=[line.split() for line in mountinfo.splitlines() if len(line.split())>6 and line.split()[4]=='/var']
    # /var may have the original overlay and a later persistent bind mount stacked on it.
    if not matches:raise RuntimeError('/var mount missing')
    row=matches[-1]; sep=row.index('-')
    if row[sep+1]!='ext4' or 'rw' not in row[5].split(','):
        raise RuntimeError('/var is not persistent writable ext4')
    for line in mountinfo.splitlines():
        fields=line.split()
        if len(fields)<6:continue
        path=fields[4]
        if path in ('/var/lib',str(FIX_DIR),'/var/systemd') or path.startswith(str(FIX_DIR)+'/') or path.startswith('/var/systemd/'):
            raise RuntimeError('Unexpected nested mount below target persistence path')
    return {'device':row[2],'root':row[3],'filesystem':row[sep+1]}


def secure_dirs(path, created):
    parts=list(path.parents)[::-1]+[path]
    for item in parts:
        try:st=item.lstat()
        except FileNotFoundError:
            item.mkdir(mode=0o755);created.append(str(item));st=item.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode & 0o022:
            raise RuntimeError('Unsafe directory: '+str(item))


def write_new(path,data,mode):
    pending=path.with_name(path.name+'.pending')
    fd=os.open(str(pending),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(data);out.flush();os.fsync(out.fileno())
        os.chmod(pending,mode)
        # Publish a complete file atomically, while refusing to overwrite a target.
        os.link(pending,path)
    finally:
        pending.unlink()


def restart():
    p=subprocess.run(['/bin/systemctl','restart',UNIT],capture_output=True,text=True,timeout=15)
    if p.returncode:raise RuntimeError('Service restart failed: '+p.stderr[-500:])


def preflight():
    if os.geteuid()!=0:raise RuntimeError('TV root required')
    if digest('/usr/sbin/bthidmanager')!=BINARY_SHA:raise RuntimeError('Firmware executable changed')
    if digest('/etc/systemd/system/bthidmanager.service')!=UNIT_SHA:raise RuntimeError('Vendor unit changed')
    persistence=persistent_var(Path('/proc/self/mountinfo').read_text())
    before=props();validate_properties(before)
    if os.path.realpath('/proc/'+before['MainPID']+'/exe')!='/usr/sbin/bthidmanager':
        raise RuntimeError('Unexpected service executable')
    return before,persistence


def install_fix(bundle, report):
    before,persistence=preflight()
    report.update({'status':'preflight','restartRequested':False,'createdDirectories':[],
                   'beforeProperties':before,'persistence':persistence,
                   'bootId':Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
    if ENV_FILE.exists() or ENV_FILE.is_symlink() or FIX_DIR.exists() or FIX_DIR.is_symlink():
        raise RuntimeError('Existing configuration: refusing to overwrite')
    data=base64.b64decode(bundle['libraryBase64'],validate=True)
    if hashlib.sha256(data).hexdigest()!=bundle['librarySha256']:raise RuntimeError('Bundle mismatch')
    # This bundle contains the exact library previously tested on the reviewed TV.
    report['librarySha256']=bundle['librarySha256']
    activated=False
    created_files=[]
    try:
        secure_dirs(FIX_DIR,report['createdDirectories'])
        secure_dirs(ENV_FILE.parent,report['createdDirectories'])
        write_new(FIX_LIB,data,0o644);created_files.append(str(FIX_LIB))
        write_new(FIX_DIR/'rollback.py',bundle['rollbackSource'].encode(),0o600)
        created_files.append(str(FIX_DIR/'rollback.py'))
        # Atomic create, never replace an existing service environment.
        write_new(ENV_FILE,ENV_CONTENT.encode(),0o600);created_files.append(str(ENV_FILE));activated=True
        report['restartRequested']=True
        restart();time.sleep(3)
        after=props();validate_properties(after)
        if after['MainPID']==before['MainPID']:raise RuntimeError('Service did not restart')
        maps=Path('/proc/'+after['MainPID']+'/maps').read_text()
        if str(FIX_LIB) not in maps:raise RuntimeError('Guard not loaded')
        report['afterProperties']=after;report['libraryMapped']=True
        time.sleep(2)
        stable=props()
        if stable['MainPID']!=after['MainPID'] or stable.get('ActiveState')!='active':
            raise RuntimeError('Service not stable')
        report['sameBoot']=Path('/proc/sys/kernel/random/boot_id').read_text().strip()==report['bootId']
        record={'version':1,'librarySha256':bundle['librarySha256'],'binarySha256':BINARY_SHA,
                'unitSha256':UNIT_SHA,'environmentFile':str(ENV_FILE),'environmentContent':ENV_CONTENT,
                'createdDirectories':report['createdDirectories'],'rollbackSha256':hashlib.sha256(bundle['rollbackSource'].encode()).hexdigest()}
        write_new(FIX_DIR/'installed.json',(json.dumps(record,indent=2)+'\n').encode(),0o600)
        report['status']='installed';report['persistentFiles']=[str(FIX_LIB),str(ENV_FILE),str(FIX_DIR/'rollback.py'),str(FIX_DIR/'installed.json')]
    except BaseException as e:
        report['installError']=type(e).__name__+': '+str(e)
        if activated:
            # Remove only our exact environment, then put the original service back.
            if ENV_FILE.read_text()!=ENV_CONTENT:raise RuntimeError('Environment changed during rollback') from e
            ENV_FILE.unlink()
            report['rollbackRequested']=True
            restart();time.sleep(2)
            report['rollbackProperties']=props()
            report['status']='rolled-back'
        for name in reversed(created_files):
            p=Path(name)
            if p.exists():p.unlink()
        for name in reversed(report['createdDirectories']):
            try:Path(name).rmdir()
            except OSError:pass
        raise


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Optional TV-root workaround for reviewed LG G3 firmware 43.21.96.')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true',help='Validate compatibility without changing the TV')
    mode.add_argument('--apply',action='store_true',help='Install and restart only bthidmanager')
    args=parser.parse_args()
    here=Path(__file__).resolve().parent
    data=(here/'libsirimote-hid-guard.so').read_bytes()
    if hashlib.sha256(data).hexdigest()!=LIBRARY_SHA:
        raise RuntimeError('Library differs from the hardware-tested release')
    before,_=preflight()
    if FIX_DIR.exists() or FIX_DIR.is_symlink() or ENV_FILE.exists() or ENV_FILE.is_symlink():
        record=json.loads((FIX_DIR/'installed.json').read_text())
        if (digest(FIX_LIB)!=LIBRARY_SHA or ENV_FILE.read_text()!=ENV_CONTENT
                or record['librarySha256']!=LIBRARY_SHA
                or record['binarySha256']!=BINARY_SHA or record['unitSha256']!=UNIT_SHA
                or digest(FIX_DIR/'rollback.py')!=record['rollbackSha256']
                or str(FIX_LIB) not in Path('/proc/'+before['MainPID']+'/maps').read_text()):
            raise RuntimeError('Existing configuration differs or guard is not loaded; inspect before continuing')
        print('Already installed and loaded; no changes made.')
        return
    if args.check:
        print('Compatible with the reviewed release; no changes made.')
        return
    report={}
    install_fix({'libraryBase64':base64.b64encode(data).decode(),
                 'librarySha256':LIBRARY_SHA,'rollbackSource':(here/'rollback.py').read_text()},report)
    print('Installed and loaded. Only bthidmanager was restarted. TV was not rebooted.')


if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit(str(error))
