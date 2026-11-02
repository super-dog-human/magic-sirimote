"""Opt-in, explicitly limited feature serialization for an owned remote.

This proves only the cooperating project lock is held. It does not exclude TV
system software or other applications and cannot prove the true remote state.
It is an experimental assumption, not a system-wide lock or permission grant.
"""
class CooperativeFeatureAssumption:
 def __init__(self,lease,*,explicit_cooperative_only):
  if explicit_cooperative_only is not True or not callable(getattr(lease,'held',None)):raise ValueError('explicit cooperative-only policy required')
  self.lease=lease;self.system_wide_exclusive=False
 def __call__(self):
  try:return self.lease.held() is True
  except Exception:return False
