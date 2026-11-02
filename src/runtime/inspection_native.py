"""One-shot, read-only native-context inspection candidate.

Apart from its bounded result receipt, performs no TV or remote mutations.
It never connects, opens a HID endpoint or invokes an Activity method.
"""
import json,os,re,stat,time
from pathlib import Path
import local_attestation,native_app_identity,receiver_package_attestation
from takeover_prepare import _lease_for
from maintenance_native import ROOT,PKG,A,B,boot_unchanged,profiles_idle
from recovery_evidence import verify as verify_recovery
from maintenance_request import write_record
NAME='maintenance-inspection-request.json'

def request(state,*,clock=time.time,developer_uid=5415,state_uid=5999,group=5000):
 d=os.open(Path(state),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  ds=os.fstat(d)
  if not stat.S_ISDIR(ds.st_mode) or (ds.st_uid,ds.st_gid)!=(state_uid,group) or stat.S_IMODE(ds.st_mode) not in (0o770,0o775):raise RuntimeError('unsafe request directory')
  try:f=os.open(NAME,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=d)
  except FileNotFoundError:return None
  try:
   s=os.fstat(f);raw=os.read(f,1025);end=os.fstat(f);named=os.stat(NAME,dir_fd=d,follow_symlinks=False)
   ident=lambda x:(x.st_dev,x.st_ino,x.st_uid,x.st_gid,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
   if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or ((s.st_uid,s.st_gid)!=(developer_uid,group) or stat.S_IMODE(s.st_mode) not in (0o640,0o775)) or s.st_size>1024 or len(raw)!=s.st_size or ident(s)!=ident(end) or ident(s)!=ident(named):raise RuntimeError('unsafe inspection request')
  finally:os.close(f)
  def unique(pairs):
   out={}
   for k,v in pairs:
    if k in out:raise ValueError('duplicate key')
    out[k]=v
   return out
  q=json.loads(raw,object_pairs_hook=unique)
  if type(q) is not dict or set(q)!={'schema','operation','expiresEpochMs'} or type(q['schema']) is not int or q['schema']!=1 or type(q['operation']) is not str or re.fullmatch('[a-f0-9]{32}',q['operation']) is None or type(q['expiresEpochMs']) is not int:raise RuntimeError('invalid inspection request')
  remaining=q['expiresEpochMs']-int(clock()*1000)
  if remaining<=0:return None
  # A widened, expired request is inert after a TV boot. Never execute it.
  if stat.S_IMODE(s.st_mode)!=0o640:raise RuntimeError("live request permissions changed")
  if remaining>90000:raise RuntimeError('invalid inspection expiry')
  return q
 finally:os.close(d)

def inspect(*,state,lease,pin,check_self=native_app_identity.verify_self,clock=time.monotonic):
 checks={
  'nativeIdentity':check_self,
  'leaseBinding':lambda:_lease_for(lease,state),
  'controllerOnly':lambda:local_attestation.candidate_pids(ROOT/A)==[os.getpid()],
  'receiverAbsent':lambda:local_attestation.candidate_pids(ROOT/B)==[],
  'receiverPackage':lambda:receiver_package_attestation.package_matches(ROOT/B,PKG/B,pin),
  'boot':boot_unchanged,
  'profilesIdle':profiles_idle,
  'recoveryEvidence':lambda:verify_recovery(ROOT/B/'state'),
 }
 out={}
 for name,fn in checks.items():
  before=clock()
  try:value=fn();out[name]={'result':value is True,'elapsedMs':max(0,round((clock()-before)*1000))}
  except Exception as exc:out[name]={'result':False,'errorType':type(exc).__name__ if type(exc).__name__ in ('OSError','PermissionError','RuntimeError','ValueError','TypeError') else 'other','elapsedMs':max(0,round((clock()-before)*1000))}
 return out

def run_if_requested(*,lease,pin,state=None,reader=request,writer=write_record):
 state=ROOT/A/'state' if state is None else Path(state)
 q=reader(state)
 if q is None:return None
 if native_app_identity.verify_self() is not True or _lease_for(lease,state) is not True:raise RuntimeError('inspection identity or lease unavailable')
 checks=inspect(state=state,lease=lease,pin=pin)
 result={'schema':1,'operation':q['operation'],'checks':checks,'noDeviceWrites':True}
 writer(state,'maintenance-inspection-result-'+q['operation']+'.json',result)
 return result
