"""Local candidate composition; not a TV entry point or deployment script."""
from archive import archive
from maintenance_guard import RUN,build_guard

def execute(*,controller_state,receiver_state,expected,lease,processes_exclusive,
            profiles_idle,boot_unchanged,sensor_observation,clock,
            recovery_evidence_valid,archive_options=None):
    if not callable(recovery_evidence_valid):raise ValueError('missing recovery verifier')
    gate=build_guard(lease=lease,processes_exclusive=processes_exclusive,
                     profiles_idle=profiles_idle,boot_unchanged=boot_unchanged,
                     sensor_observation=sensor_observation,clock=clock)
    def guard():
        guard.last_failure=None
        if gate() is not True:
            guard.last_failure=gate.last_failure;return False
        if recovery_evidence_valid() is not True:
            guard.last_failure='recovery-evidence';return False
        if gate() is not True:
            guard.last_failure=gate.last_failure;return False
        return True
    guard.last_failure=None
    if guard() is not True:raise RuntimeError('maintenance-precondition-'+str(guard.last_failure))
    return archive(controller_state,receiver_state,run=RUN,expected=expected,
                   guard=guard,**(archive_options or {}))
