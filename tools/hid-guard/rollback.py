"""Restore stock bthidmanager. Requires TV root; does not reboot the TV."""
import hashlib,json,os
from pathlib import Path
import subprocess,time
BASE=Path('/var/lib/magic-sirimote-hid-guard')
ENV=Path('/var/systemd/system/env/bthidmanager.env')
if os.geteuid()!=0:raise SystemExit('TV root required')
r=json.loads((BASE/'installed.json').read_text())
lib=BASE/'libsirimote-hid-guard.so'
if hashlib.sha256(lib.read_bytes()).hexdigest()!=r['librarySha256']:raise SystemExit('Library changed; stopped')
if ENV.read_text()!=r['environmentContent']:raise SystemExit('Environment changed; stopped')
ENV.unlink()
p=subprocess.run(['/bin/systemctl','restart','bthidmanager.service'],timeout=20)
if p.returncode:raise SystemExit('Environment removed; service restart failed; library retained for inspection')
time.sleep(2)
p=subprocess.run(['/bin/systemctl','is-active','bthidmanager.service'],capture_output=True,text=True,timeout=5)
if p.returncode:raise SystemExit('Environment removed; service not active; library retained')
for name in ['libsirimote-hid-guard.so','installed.json','rollback.py']:(BASE/name).unlink()
for name in reversed(r['createdDirectories']):
 try:Path(name).rmdir()
 except OSError:pass
print(json.dumps({'stockServiceRestored':True,'tvRebooted':False}))
