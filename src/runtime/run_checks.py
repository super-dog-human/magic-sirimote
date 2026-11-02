"""Exercise only host tests, with this overlay before immutable extracted v16 modules."""
import os,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'resident-continuous-stop-packaged-offline-v1'
APP=BASE/'extracted/controller/usr/palm/applications/org.codex.siriremote.autocoord20261029v'
NAMES=['test_permission_continuity','test_postconnect_supervisor_cycle','test_stop_loop','test_stop_ipc','test_local_attestation','test_receiver_process_observer','test_postconnect_receiver_entry','test_postconnect_receiver_app']
env=dict(os.environ,PYTHONPATH=os.pathsep.join(map(str,(HERE,APP,BASE/'tests'))))
result=subprocess.run([sys.executable,'-B','-m','unittest','-v',*NAMES],cwd=HERE,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
(HERE/'verification.txt').write_text(result.stdout)
print(result.stdout,end='')
raise SystemExit(result.returncode)
