"""Run-specific maintenance entry candidate; not yet built or installed."""
import os,time
from pathlib import Path
import local_attestation
import native_app_identity
import receiver_package_attestation
from connected_status_watch import ConnectedStatusWatch
from takeover_prepare import _lease_for
from tv_bluetooth import profiles
from next_retry_request import read_request,run_requested
from next_evidence import verify as verify_recovery
from next_prior import verify as verify_prior
from profile_idle_retry import idle as idle_with_retry
from next_guard import RUN

ROOT=Path('/media/developer/apps/usr/palm/applications')
PKG=Path('/media/developer/apps/usr/palm/packages')
A='org.codex.siriremote.autocoord20261029v'
B='org.codex.siriremote.hidgattrouterb20261029u'
BOOT='ceb8a8ee-909c-49ea-9f82-f67c47860d07'
BTIME=1793503823
EXPECTED={
 'receiver-launch-intent.json':'2a5293ceffb0529c198c08f5eab3164c5d3480020532024f6124e1736d2eaba8',
 'controller-start.json':'7dd1d1116f5109f39bac38a03a6ba768dddcc5d04572979e0dbafe5bfb49d32a',
 'request.json':'9fce72fd91411264d9b043cb5862e840dc0ecc1a86eceadd500f8f31507c0c4b',
 'recovery-request.json':'41f4298c398019da7ea1e94b41e5d05557065dc8ff46119ad04d86e289e05ac0',
 'journal':{
  'borrowed-'+RUN+'-01.json':'c84b19b987beece62bbab73809811884acd1ad3bafe1b8917acd183ff9393bb8',
  'borrowed-'+RUN+'-02.json':'32805a883dd9de7204014faf52e5fae8136fdf7de688da26e858e61ae71be42c'}}

def boot_unchanged():
 try:
  boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
  times=[int(x.split()[1]) for x in Path('/proc/stat').read_text().splitlines() if x.startswith('btime ')]
  return boot==BOOT and times==[BTIME]
 except (OSError,ValueError,IndexError):return False

def profiles_idle():
 try:
  all_profiles=profiles()
  for role in ('hid','gatt'):
   reply=all_profiles.get(role,{}).get('reply')
   if not ConnectedStatusWatch.valid(reply) or any(reply.get(k) is not False for k in ('connected','connecting','connectRequest')):return False
  return True
 except Exception:return False

def run_if_requested(*,lease,pin):
 state=ROOT/A/'state';receiver_state=ROOT/B/'state'
 if read_request(state) is None:return None
 if native_app_identity.verify_self() is not True or _lease_for(lease,state) is not True:raise RuntimeError('maintenance identity or lease unavailable')
 if type(pin) is not dict or pin.get('appId')!=B:raise RuntimeError('receiver pin unavailable')
 class ProcessCheck:
  last_failure=None
  def __call__(self):
   self.last_failure=None
   try:
    if native_app_identity.verify_self() is not True:self.last_failure='native-identity';return False
    if _lease_for(lease,state) is not True:self.last_failure='lease-binding';return False
    if local_attestation.candidate_pids(ROOT/A)!=[os.getpid()]:self.last_failure='controller-processes';return False
    if local_attestation.candidate_pids(ROOT/B)!=[]:self.last_failure='receiver-processes';return False
    if receiver_package_attestation.package_matches(ROOT/B,PKG/B,pin) is not True:self.last_failure='receiver-package';return False
    return True
   except Exception:
    self.last_failure='process-check-error';return False
 processes_exclusive=ProcessCheck()
 def profiles_retry():return idle_with_retry(profiles=profiles,valid=ConnectedStatusWatch.valid,guard=lambda:_lease_for(lease,state) is True and boot_unchanged() is True)
 def evidence():return verify_prior(state) is True and verify_recovery(receiver_state) is True
 context={'controller_state':state,'receiver_state':receiver_state,'expected':EXPECTED,
          'processes_exclusive':processes_exclusive,'profiles_idle':profiles_retry,
          'boot_unchanged':boot_unchanged,'recovery_evidence_valid':evidence}
 return run_requested(state=state,lease=lease,context=context,clock=time.time)
