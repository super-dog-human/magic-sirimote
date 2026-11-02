"""Native entry for generic pre-sensor archive; explicit requests only."""
import os,time
from pathlib import Path
import local_attestation,native_app_identity,receiver_package_attestation
from takeover_prepare import _lease_for
from tv_bluetooth import profiles
from connected_status_watch import ConnectedStatusWatch
from generic_profile_stable import make_check
from generic_request import read_request,run_requested
ROOT=Path('/media/developer/apps/usr/palm/applications')
PKG=Path('/media/developer/apps/usr/palm/packages')
A='org.codex.siriremote.autocoord20261029v'
B='org.codex.siriremote.hidgattrouterb20261029u'

def run_if_requested(*,lease,pin):
 state=ROOT/A/'state';receiver_state=ROOT/B/'state'
 if read_request(state) is None:return None
 if native_app_identity.verify_self() is not True or _lease_for(lease,state) is not True:raise RuntimeError('generic identity or lease unavailable')
 if type(pin) is not dict or pin.get('appId')!=B:raise RuntimeError('receiver pin unavailable')
 def context_for(q):
  def boot():
   try:
    boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    times=[int(x.split()[1]) for x in Path('/proc/stat').read_text().splitlines() if x.startswith('btime ')]
    return boot_id==q['boot']['bootId'] and times==[q['boot']['btime']]
   except (OSError,ValueError,IndexError):return False
  def processes():
   try:return (native_app_identity.verify_self() is True and _lease_for(lease,state) is True and local_attestation.candidate_pids(ROOT/A)==[os.getpid()] and local_attestation.candidate_pids(ROOT/B)==[] and receiver_package_attestation.package_matches(ROOT/B,PKG/B,pin) is True)
   except Exception:return False
  stable=make_check(profiles=profiles,valid=ConnectedStatusWatch.valid,guard=lambda:_lease_for(lease,state) is True and boot() is True)
  return {'controller_state':state,'receiver_state':receiver_state,'gate':{'processes_exclusive':processes,'profiles_idle':stable,'boot_unchanged':boot}}
 return run_requested(state=state,lease=lease,context_for=context_for,clock=time.time)
