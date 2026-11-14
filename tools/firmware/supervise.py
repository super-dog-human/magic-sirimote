#!/usr/bin/env python3
"""Bound the updater lifetime and preserve its result; invoked with sudo by the launcher."""
import subprocess,sys,json,os,datetime
from pathlib import Path
print('Updater supervisor effective UID:',os.geteuid(),flush=True)
started=datetime.datetime.now().astimezone()-datetime.timedelta(seconds=1)
process=subprocess.Popen([sys.argv[1],'--apply',sys.argv[2],sys.argv[3]])
try:
    result=process.wait(timeout=900)
except (subprocess.TimeoutExpired,KeyboardInterrupt):
    process.kill()
    process.wait()
    print('STOP: updater interrupted or exceeded 15 minutes. No automatic retry or recovery.',flush=True)
    print('Do not rerun the updater. Retain the log and check the remote before further writes.',flush=True)
    result=124
if Path(sys.argv[3]).exists():
    try: print('Last journal phase:',json.loads(Path(sys.argv[3]).read_text()).get('phase'),flush=True)
    except (OSError,ValueError): print('Could not read final journal; retain the file.',flush=True)
    # Keep this single generated journal accessible to the initiating user.
    if os.geteuid()==0 and os.environ.get('SUDO_UID','').isdigit() and os.environ.get('SUDO_GID','').isdigit():
        try: os.chown(sys.argv[3],int(os.environ['SUDO_UID']),int(os.environ['SUDO_GID']),follow_symlinks=False)
        except OSError as e: print('Journal ownership could not be restored:',e,flush=True)
if result:
    print('Relevant OS diagnostics for this attempt:',flush=True)
    predicate='(process == "kernel" AND eventMessage CONTAINS "IOHIDLibUserClient" AND (eventMessage CONTAINS[c] "privileg" OR eventMessage CONTAINS[c] "setReport failed")) OR (process == "bluetoothd" AND eventMessage CONTAINS[c] "setReportWithKeyhole" AND eventMessage CONTAINS[c] "0xb0")'
    try:
        logs=subprocess.run(['/usr/bin/log','show','--start',started.strftime('%Y-%m-%d %H:%M:%S'),'--style','compact','--info','--debug','--predicate',predicate],capture_output=True,text=True,timeout=20)
        print('\n'.join((logs.stdout+logs.stderr).splitlines()[-60:]),flush=True)
    except subprocess.TimeoutExpired: print('OS log query timed out.',flush=True)
sys.exit(result)
