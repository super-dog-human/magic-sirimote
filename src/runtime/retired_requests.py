"""Retired development requests require reconciliation, never silent replay."""
import os,re
RETIRED=frozenset((
 'handoff-diagnostic-request.json','owner-mode-repair-request.json',
 'serial-zero-archive-request.json','serial-zero-archive-v2-request.json',
 'serial-zero-archive-next-request.json','serial-zero-archive-next-v2-request.json',
 'maintenance-inspection-request.json'))
GENERIC=re.compile(r'generic-presensor-request-[a-f0-9]{32}(?:-[a-f0-9]{32})?\.json')

def reject_retired_requests(state):
 """Read names only. Include symlinks; leave all records untouched."""
 for name in os.listdir(state):
  if name in RETIRED or GENERIC.fullmatch(name):
   raise RuntimeError('retired-maintenance-request-retained: '+name)
