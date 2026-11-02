"""Offline candidate for a lease-held, run-bound maintenance gate.

The sensor observation is an external assertion from the host that performed
an independent diagnostic read. It is not itself a hardware proof on the TV;
the production caller must authenticate and bind the one-shot request.
"""
import math

import re
RUN=re.compile(r'^[0-9a-f]{32}$')

def build_guard(*,lease,processes_exclusive,profiles_idle,boot_unchanged,
                sensor_observation,clock,run,max_age_seconds=45):
    if not all(callable(x) for x in (processes_exclusive,profiles_idle,boot_unchanged,clock)):
        raise ValueError('invalid guard dependencies')
    if not callable(getattr(lease,'held',None)) or type(sensor_observation) is not dict:
        raise ValueError('invalid guard inputs')
    if set(sensor_observation)!={'run','mode','identityVerified','savedPeer','checkedEpochMs'}:
        raise ValueError('invalid sensor observation shape')
    if (type(run) is not str or RUN.fullmatch(run) is None or sensor_observation['run']!=run or type(sensor_observation['mode']) is not int
        or sensor_observation['mode']!=0 or sensor_observation['identityVerified'] is not True
        or sensor_observation['savedPeer'] not in ('expected','none')
        or type(sensor_observation['checkedEpochMs']) is not int):
        raise ValueError('sensor observation not suitable')
    if type(max_age_seconds) not in (int,float) or not math.isfinite(max_age_seconds) or not 0<max_age_seconds<=45:
        raise ValueError('invalid freshness bound')
    checked=sensor_observation['checkedEpochMs']/1000
    def guard():
        guard.last_failure=None
        try:
            now=clock()
            if type(now) not in (int,float) or not math.isfinite(now) or not 0<=now-checked<=max_age_seconds:
                guard.last_failure='sensor-age';return False
            if lease.held() is not True:
                guard.last_failure='lease';return False
            if processes_exclusive() is not True:
                guard.last_failure=getattr(processes_exclusive,'last_failure',None) or 'process-or-package';return False
            if boot_unchanged() is not True:
                guard.last_failure='boot';return False
            if profiles_idle() is not True:
                guard.last_failure='profiles';return False
            if processes_exclusive() is not True:
                guard.last_failure=getattr(processes_exclusive,'last_failure',None) or 'process-or-package';return False
            if boot_unchanged() is not True:
                guard.last_failure='boot';return False
            if lease.held() is not True:
                guard.last_failure='lease';return False
            now=clock()
            if type(now) not in (int,float) or not math.isfinite(now) or not 0<=now-checked<=max_age_seconds:
                guard.last_failure='sensor-age';return False
            return True
        except Exception:
            guard.last_failure='guard-error';return False
    guard.last_failure=None
    return guard
