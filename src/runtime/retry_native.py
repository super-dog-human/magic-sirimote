"""Run-bound retry after verifying retained, non-archiving prior evidence."""
import os,time
import native_app_identity,local_attestation,receiver_package_attestation
from takeover_prepare import _lease_for
from maintenance_native import ROOT,PKG,A,B,EXPECTED,boot_unchanged,profiles_idle
from maintenance_retry import read_request,run_requested
from recovery_evidence import verify as verify_recovery
from prior_attempt import verify as verify_prior

def run_if_requested(*,lease,pin):
 state=ROOT/A/'state';receiver_state=ROOT/B/'state'
 if read_request(state) is None:return None
 if native_app_identity.verify_self() is not True or _lease_for(lease,state) is not True:raise RuntimeError('retry identity or lease unavailable')
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
   except Exception:self.last_failure='process-check-error';return False
 def evidence():return verify_prior(state) is True and verify_recovery(receiver_state) is True
 context={'controller_state':state,'receiver_state':receiver_state,'expected':EXPECTED,
          'processes_exclusive':ProcessCheck(),'profiles_idle':profiles_idle,
          'boot_unchanged':boot_unchanged,'recovery_evidence_valid':evidence}
 return run_requested(state=state,lease=lease,context=context,clock=time.time)
