"""Bounded diagnostic metadata only: never persist HID payloads or coordinates."""
LIMIT=100000000
KINDS=('no-touch','one-touch','two-touch','rejected')
POINTER=('reports','validPose','blocked','calibrationResets','jumps','geometryRejected','renderTicks','motionFrames','gaps')
ENDS=(None,'stop-requested','control-or-policy-ended','duration-ended','receive-exception')
STOPS=(None,'requested','control-lost','clock-invalid','drain-deadline-without-neutral','receiver-failed','receive-aborted','receive-ended','receiver-ended','combined-output-error')
FAILURES=(None,'closed','lease','snapshot','clock','age','identity','hid','gatt','external','exception','session-inactive')
WATCH=(None,'closed','missing','stale','clock-invalid','generation-changed','current')
STAGES=('tick','abort','read','feed','wait','clock')
ERRORS=('OSError','RuntimeError','ValueError','TypeError','TimeoutError','KeyboardInterrupt','SystemExit','other')

def record_failure(stats,stage,exc):
 # Keep the original failure even if output cleanup raises a second exception.
 # No exception text, filenames, HID payloads or output coordinates are saved.
 if 'receiveFailure' in stats:return
 kind='OSError' if isinstance(exc,OSError) else type(exc).__name__
 number=getattr(exc,'errno',None) if isinstance(exc,OSError) else None
 stats['receiveFailure']={'stage':stage,'type':kind if kind in ERRORS else 'other',
   'errno':number if type(number) is int and 0<=number<=4095 else None}

def valid_failure(value):
 return (type(value) is dict and set(value)=={'stage','type','errno'} and
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
    'neutralWrites':min(LIMIT,transport.get('neutralWrites',0))}
 if not valid(value):raise ValueError('invalid receive diagnostics')
 stats['receiveDiagnostics']=value

def valid(value):
 keys={'endReason','receiverStopReason','controlFailure','watchState','watchAgeMs','reportShapes','shapeOverflow','decodedKinds','pointer','pointerCalibrated'}
 if type(value) is not dict or not keys<=set(value)<=keys|{'receiveFailure','motionTransport'}:return False
 if 'receiveFailure' in value and not valid_failure(value['receiveFailure']):return False
 if 'motionTransport' in value:
  t=value['motionTransport']
  if type(t) is not dict or set(t)!={'budgetDrops','bodyWrites','neutralWrites'} or not all(count(v) for v in t.values()):return False
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
