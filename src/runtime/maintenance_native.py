"""Run-specific maintenance entry candidate; not yet built or installed."""
import os,time
from pathlib import Path
import local_attestation
import native_app_identity
import receiver_package_attestation
from connected_status_watch import ConnectedStatusWatch
from takeover_prepare import _lease_for
from tv_bluetooth import profiles
from maintenance_request import read_request,run_requested
from recovery_evidence import verify as verify_recovery
from maintenance_guard import RUN

ROOT=Path('/media/developer/apps/usr/palm/applications')
PKG=Path('/media/developer/apps/usr/palm/packages')
A='org.codex.siriremote.autocoord20261029v'
B='org.codex.siriremote.hidgattrouterb20261029u'
BOOT='ceb8a8ee-909c-49ea-9f82-f67c47860d07'
BTIME=1793503823
EXPECTED={
 'receiver-launch-intent.json':'321518d6f4da7150bd2df1ab6425ecafeae3274ac033ff39a0b31e10534e38f3',
 'controller-start.json':'baa33409142157153c04686119d44b70e1850907f3fb435beec13046deba5654',
 'request.json':'dcc5232d62d0762c4e90190add04b1f60876c6e203eb64bea164fdec230ae44d',
 'recovery-request.json':'f001449f300aaadeba019197bd8aacb3b6a737dfc57aedae11b79be992d4d202',
 'journal':{
  'borrowed-'+RUN+'-01.json':'ae30f6966771c45bc83ccc5017f6fdb458816cf74a3df0358744e3bbbc917d68',
  'borrowed-'+RUN+'-02.json':'5aec5fac63a11e2f47594c5d36b2316714c0dfe3e1424ee07e7ff0a050cfbac8'}}

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
 context={'controller_state':state,'receiver_state':receiver_state,'expected':EXPECTED,
          'processes_exclusive':processes_exclusive,'profiles_idle':profiles_idle,
          'boot_unchanged':boot_unchanged,'recovery_evidence_valid':lambda:verify_recovery(receiver_state)}
 return run_requested(state=state,lease=lease,context=context,clock=time.time)
