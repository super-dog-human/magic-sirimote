"""Verify this process is the pinned, unprivileged TV-native app entrypoint."""
import os,stat
from pathlib import Path

APP='org.codex.siriremote.hidgattroutera20261029u'
APP_PATH='/media/developer/apps/usr/palm/applications/'+APP

def verify_self(*,proc='/proc/self',python='/usr/bin/python3',uid=None,gid=None):
 try:
  uid=os.getuid() if uid is None else uid;gid=os.getgid() if gid is None else gid
  if type(uid) is not int or uid<=0 or gid!=5000:return False
  root=Path(proc);args=(root/'cmdline').read_bytes().split(b'\0');args=[a for a in args if a]
  if args!=[python.encode(),b'-I',b'-B',(APP_PATH+'/native_probe.py').encode()]:return False
  vals={}
  for line in (root/'status').read_text().splitlines():
   if ':' in line:
    k,v=line.split(':',1)
    if k in ('Uid','Gid','CapEff'):
     if k in vals:return False
     vals[k]=v.split()
  if vals.get('Uid')!=[str(uid)]*4 or vals.get('Gid')!=['5000']*4 or vals.get('CapEff')!=['0000000000000000']:return False
  expected=os.stat(python);actual=os.stat(root/'exe')
  return stat.S_ISREG(actual.st_mode) and (actual.st_dev,actual.st_ino)==(expected.st_dev,expected.st_ino)
 except (OSError,UnicodeError,ValueError):return False
