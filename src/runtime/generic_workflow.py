"""Pre-sensor recovery composition; external guard must prove fresh zero/lease."""
from generic_archive import archive
from generic_evidence import verify,no_recovery

def execute(*,controller_state,receiver_state,run,expected,guard,options=None):
 if not callable(guard):raise ValueError('missing independent guard')
 options=options or {}
 state_uid=options.get('state_uid',5999);group=options.get('group',5000)
 def guarded():
  guarded.last_failure=None
  try:
   if guard() is not True:guarded.last_failure=getattr(guard,'last_failure',None) or 'guard';return False
   if no_recovery(receiver_state,run=run,state_uid=state_uid,group=group) is not True:guarded.last_failure='recovery-present';return False
   if guard() is not True:guarded.last_failure=getattr(guard,'last_failure',None) or 'guard';return False
   return True
  except Exception:guarded.last_failure='guard-error';return False
 guarded.last_failure=None
 if guarded() is not True:raise RuntimeError('generic-precondition-'+str(guarded.last_failure))
 try:
  if verify(controller_state,receiver_state,run=run,expected=expected,state_uid=state_uid,controller_uid=options.get('controller_uid',6959),receiver_uid=options.get('receiver_uid',5636),group=group) is not True:raise RuntimeError('unverified')
 except Exception as exc:raise RuntimeError('generic-evidence-invalid') from exc
 names=('receiver-launch-intent.json','controller-start.json','request.json')
 archive_expected={**{n:expected[n] for n in names},'journal':expected['journal']}
 return archive(controller_state,receiver_state,run=run,expected=archive_expected,guard=guarded,**options)
