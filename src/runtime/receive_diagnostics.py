"""Bounded diagnostic metadata only: never persist HID payloads or coordinates."""
LIMIT=100000000
KINDS=('no-touch','one-touch','two-touch','rejected')
POINTER=('reports','validPose','blocked','calibrationResets','jumps','geometryRejected','renderTicks','motionFrames','gaps')
TRANSPORT_REASONS=(None,'clock-invalid','deadline','write-uncertain','queue-overflow','queue-age-exceeded','reentrant-call','motion-encoding-rejected','semantic-dispatch-uncertain','semantic-dispatch-rejected','stopped')
ENDS=(None,'stop-requested','control-or-policy-ended','duration-ended','receive-exception')
STOPS=(None,'requested','control-lost','clock-invalid','drain-deadline-without-neutral','receiver-failed','receive-aborted','receive-ended','receiver-ended','combined-output-error')
FAILURES=(None,'closed','lease','snapshot','clock','age','identity','hid','gatt','external','exception','session-inactive')
WATCH=(None,'closed','missing','stale','clock-invalid','generation-changed','current')
STAGES=('tick','abort','read','feed','wait','clock')
ERRORS=('OSError','RuntimeError','ValueError','TypeError','TimeoutError','KeyboardInterrupt','SystemExit','other')

FAILURE_CODES={
 'managed system key already held':'system-key-held',
 'key release unconfirmed':'system-key-release-unconfirmed',
 'short key press':'system-key-short-press',
 'short key release':'system-key-short-release',
 'device identity unverified':'system-key-identity-unverified',
 'output disabled':'system-key-disabled',
 'receiver continuity lost':'receiver-continuity-lost',
 'screen-worker-stop-unconfirmed':'screen-worker-stop-unconfirmed',
 'media-worker-stop-unconfirmed':'media-worker-stop-unconfirmed',
 'invalid receive diagnostics':'receive-diagnostics-invalid',
}
CLEANUP_ERRORS={
 'resource-close-unverified':('system-key-release-unverified','system-key-release-error','system-key-close-error','output-release-unverified','output-release-error','output-close-error','target-close-error'),
 'app-cleanup-unverified':('status-pump-stop-unverified','status-pump-stop-error','session-archive-unverified','session-archive-error','empty-session-discard-unverified','empty-session-discard-error','journal-close-error','lease-close-error'),
}

def diagnostic_result(result):
 # Only known wrappers are traversed. Never promote nested success or stop proof.
 current=result;cleanup=[]
 for _ in range(2):
  if type(current) is not dict:break
  reason=current.get('reason');child=current.get('sessionResult')
  if reason not in CLEANUP_ERRORS or type(child) is not dict:break
  errors=current.get('errors')
  known=[] if type(errors) is not list else [e for e in errors if type(e) is str and e in CLEANUP_ERRORS[reason]]
  cleanup.append({'stage':reason,'errors':list(dict.fromkeys(known))})
  current=child
 return current,cleanup

def valid_cleanup(value):
 if type(value) is not list or not 1<=len(value)<=2:return False
 for item in value:
  if type(item) is not dict or set(item)!={'stage','errors'} or item.get('stage') not in CLEANUP_ERRORS:return False
  errors=item['errors']
  if type(errors) is not list or len(errors)>8 or any(type(e) is not str or e not in CLEANUP_ERRORS[item['stage']] for e in errors):return False
  if len(set(errors))!=len(errors):return False
 return True

def record_failure(stats,stage,exc):
 # Keep the original failure even if output cleanup raises a second exception.
 # No exception text, filenames, HID payloads or output coordinates are saved.
 if 'receiveFailure' in stats:return
 kind='OSError' if isinstance(exc,OSError) else type(exc).__name__
 number=getattr(exc,'errno',None) if isinstance(exc,OSError) else None
 stats['receiveFailure']={'stage':stage,'type':kind if kind in ERRORS else 'other',
   'errno':number if type(number) is int and 0<=number<=4095 else None,
   'code':FAILURE_CODES.get(str(exc))}

def valid_failure(value):
 return (type(value) is dict and {'stage','type','errno'}<=set(value)<={'stage','type','errno','code'} and value.get('code') in (None,*FAILURE_CODES.values()) and
   value['stage'] in STAGES and value['type'] in ERRORS and
   (value['errno'] is None or (value['type']=='OSError' and type(value['errno']) is int and 0<=value['errno']<=4095)))

def count(value):return type(value) is int and 0<=value<=LIMIT

def record_shape(stats,data):
 # Only the report ID and total length, with at most twelve distinct shapes.
 shape=(data[0],len(data))
 for row in stats['reportShapes']:
  if (row['id'],row['length'])==shape:
   row['count']=min(LIMIT,row['count']+1);return
 if len(stats['reportShapes'])<12:
  stats['reportShapes'].append({'id':shape[0],'length':shape[1],'count':1})
 else:stats['shapeOverflow']=min(LIMIT,stats['shapeOverflow']+1)

def capture(stats,summary,end_reason,control):
 current=summary.get('current') or {}
 pointer=(current.get('router') or {}).get('pointer') or {}
 value={'endReason':end_reason,'receiverStopReason':summary.get('stopReason'),
        'controlFailure':control.get('failure'),'watchState':control.get('watchState'),
        'watchAgeMs':control.get('watchAgeMs'),'reportShapes':stats.get('reportShapes',[]),
        'shapeOverflow':stats.get('shapeOverflow',0),'decodedKinds':summary['decodedKinds'],
        'pointer':{k:min(LIMIT,pointer.get(k,0)) for k in POINTER},
        'pointerCalibrated':pointer.get('calibrated') is True}
 if 'receiveFailure' in stats:value['receiveFailure']=stats['receiveFailure']
 if 'motionBudgetDrops' in current:
  transport=current.get('transport') or {}
  value['motionTransport']={'budgetDrops':min(LIMIT,current['motionBudgetDrops']),
    'bodyWrites':min(LIMIT,transport.get('bodyWrites',0)),
    'neutralWrites':min(LIMIT,transport.get('neutralWrites',0)),
    'reason':transport.get('reason') if transport.get('reason') in TRANSPORT_REASONS else None}
 if not valid(value):raise ValueError('invalid receive diagnostics')
 stats['receiveDiagnostics']=value

def valid(value):
 keys={'endReason','receiverStopReason','controlFailure','watchState','watchAgeMs','reportShapes','shapeOverflow','decodedKinds','pointer','pointerCalibrated'}
 if type(value) is not dict or not keys<=set(value)<=keys|{'receiveFailure','motionTransport'}:return False
 if 'receiveFailure' in value and not valid_failure(value['receiveFailure']):return False
 if 'motionTransport' in value:
  t=value['motionTransport']
  keys={'budgetDrops','bodyWrites','neutralWrites'}
  if type(t) is not dict or not keys<=set(t)<=keys|{'reason'} or not all(count(t[k]) for k in keys):return False
  if t.get('reason') not in TRANSPORT_REASONS:return False
 if value['endReason'] not in ENDS or value['receiverStopReason'] not in STOPS or value['controlFailure'] not in FAILURES or value['watchState'] not in WATCH:return False
 if value['watchAgeMs'] is not None and not count(value['watchAgeMs']):return False
 if type(value['pointerCalibrated']) is not bool or not count(value['shapeOverflow']):return False
 shapes=value['reportShapes']
 if type(shapes) is not list or len(shapes)>12:return False
 seen=set()
 for row in shapes:
  if type(row) is not dict or set(row)!={'id','length','count'} or not all(count(row[k]) for k in row) or not 0<=row['id']<=255 or not 1<=row['length']<=4096 or row['count']==0:return False
  shape=(row['id'],row['length'])
  if shape in seen:return False
  seen.add(shape)
 for name,expected in (('decodedKinds',KINDS),('pointer',POINTER)):
  values=value[name]
  if type(values) is not dict or set(values)!=set(expected) or not all(count(v) for v in values.values()):return False
 return True
