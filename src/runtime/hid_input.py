"""Validated HID identity, bounded discovery, and the shared input read loop."""
import errno,fcntl,os,stat,struct,time
TARGET='02:00:00:00:00:01';NAME='EXAMPLE_REMOTE_SERIAL';MAX=32
READ_BACKOFF_SECONDS=0.01
READ_SUCCESS_YIELD_SECONDS=0.001

def ioctl(fd,request,b):fcntl.ioctl(fd,request,b,True);return b

def cstr(b):return bytes(b).split(b'\0',1)[0].decode('utf-8','replace')

def ordinary():
 p={}
 for l in open('/proc/self/status'):
  k,_,v=l.partition(':')
  if k in ('Uid','Gid','Groups','CapEff'):p[k]=v.strip()
 u=p.get('Uid','').split();g=p.get('Gid','').split()
 if len(u)!=4 or len(set(u))!=1 or u[0]=='0' or len(g)!=4 or len(set(g))!=1 or g[0]!='5000' or p.get('CapEff')!='0000000000000000':raise RuntimeError('ordinary-uid-gid-capability-gate-failed')
 return p

def identity(fd):
 info=ioctl(fd,(2<<30)|(8<<16)|(ord('H')<<8)|3,bytearray(8));bus,vid,pid=struct.unpack('=IHH',info)
 name=ioctl(fd,(2<<30)|(256<<16)|(ord('H')<<8)|4,bytearray(256));uniq=ioctl(fd,(2<<30)|(256<<16)|(ord('H')<<8)|8,bytearray(256))
 return {'matches':(bus,vid,pid)==(5,0x004c,0x0266) and cstr(name)==NAME and cstr(uniq).lower()==TARGET,'bus':bus,'vendor':vid,'product':pid,'name':cstr(name),'uniq':cstr(uniq).lower()}

def scan_devices(root='/dev',lstat_fn=None,open_fn=None,fstat_fn=None,identity_fn=None,close_fn=None,clock=time.monotonic,timeout=10):
 lstat_fn=os.lstat if lstat_fn is None else lstat_fn;open_fn=os.open if open_fn is None else open_fn;fstat_fn=os.fstat if fstat_fn is None else fstat_fn;identity_fn=identity if identity_fn is None else identity_fn;close_fn=os.close if close_fn is None else close_fn
 nodes=[];errors={};matches=[];complete=True;deadline=clock()+timeout
 for i in range(MAX):
  if clock()>deadline:complete=False;break
  p=os.path.join(root,'hidraw'+str(i))
  try:st=lstat_fn(p)
  except OSError as e:
   k=errno.errorcode.get(e.errno,'OTHER');errors[k]=errors.get(k,0)+1
   if e.errno!=errno.ENOENT:complete=False
   continue
  if stat.S_ISLNK(st.st_mode) or not stat.S_ISCHR(st.st_mode):
   nodes.append({'index':i,'fileType':'other','mode':oct(stat.S_IMODE(st.st_mode))});complete=False;continue
  entry={'index':i,'mode':oct(stat.S_IMODE(st.st_mode)),'uid':st.st_uid,'gid':st.st_gid,'rdevMajor':os.major(st.st_rdev),'rdevMinor':os.minor(st.st_rdev),'identityChecked':False,'openedReadOnly':False,'fdClosed':False};fd=None
  try:
   fd=open_fn(p,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC);entry['openedReadOnly']=True;opened=fstat_fn(fd);after=lstat_fn(p)
   if (st.st_ino,st.st_dev,st.st_rdev)!=(opened.st_ino,opened.st_dev,opened.st_rdev) or (opened.st_ino,opened.st_dev,opened.st_rdev)!=(after.st_ino,after.st_dev,after.st_rdev):entry['inspectionError']='node-identity-raced';complete=False
   else:
    x=identity_fn(fd);entry['identityChecked']=True;entry['targetIdentity']=x
    if x.get('matches') is True:matches.append(i)
    if clock()>deadline:entry['inspectionError']='inventory-deadline';complete=False
  except OSError as e:
   k=errno.errorcode.get(e.errno,'OTHER');entry['inspectionErrno']=k;complete=False
  except Exception as e:
   entry['inspectionError']=type(e).__name__;complete=False
  finally:
   if fd is not None:
    try:close_fn(fd);entry['fdClosed']=True
    except OSError as e:entry['closeErrno']=errno.errorcode.get(e.errno,'OTHER');complete=False
  if entry['openedReadOnly'] and (not entry['identityChecked'] or not entry['fdClosed']):complete=False
  nodes.append(entry)
 return {'nodes':nodes,'errnoBuckets':errors,'targetCandidateIndexes':matches,'inventoryComplete':complete,'range':[0,MAX-1],'allOpenedFdsClosed':all(not n.get('openedReadOnly') or n.get('fdClosed') for n in nodes)}

def receive_actions(fd,pipeline,generation=1,duration=60,read_fn=None,clock=None,sleep_fn=None,abort_fn=None,stats=None):
 from receive_diagnostics import record_shape,record_failure
 read_fn=os.read if read_fn is None else read_fn;clock=time.monotonic if clock is None else clock;sleep_fn=time.sleep if sleep_fn is None else sleep_fn
 started=clock();deadline=None if duration is None else started+duration
 def remaining(limit):return limit if deadline is None else min(limit,max(0,deadline-clock()))
 if stats is None:stats={}
 stats.update({'readCalls':0,'bytesReceived':0,'nonemptyReads':0,'emptyReads':0,'wouldBlockReads':0,'interruptedReads':0,'rawReportsPersisted':False,'aborted':False,'elapsedMs':0})
 stats['reportShapes']=[];stats['shapeOverflow']=0
 stats.pop('receiveFailure',None)
 stage='clock'
 def wait(limit):
  nonlocal stage
  stage='wait';sleep_fn(remaining(limit))
 try:
  while deadline is None or clock()<deadline:
   stage='tick'
   pipeline.tick()
   stage='abort'
   if abort_fn is not None and abort_fn():stats['aborted']=True;break
   stats['readCalls']+=1
   stage='read'
   try:data=read_fn(fd,4096)
   except BlockingIOError:
    stats['wouldBlockReads']+=1;wait(READ_BACKOFF_SECONDS);stage='clock';continue
   except InterruptedError:
    stats['interruptedReads']+=1;wait(READ_BACKOFF_SECONDS);stage='clock';continue
   except OSError as e:
    if e.errno==errno.EAGAIN:stats['wouldBlockReads']+=1;wait(READ_BACKOFF_SECONDS);stage='clock';continue
    if e.errno==errno.EINTR:stats['interruptedReads']+=1;wait(READ_BACKOFF_SECONDS);stage='clock';continue
    raise
   if not data:
    stats['emptyReads']+=1;wait(READ_BACKOFF_SECONDS);stage='clock';continue
   stats['nonemptyReads']+=1;stats['bytesReceived']+=len(data)
   record_shape(stats,data)
   stage='feed'
   try:pipeline.feed_raw(generation,data)
   finally:del data
   wait(READ_SUCCESS_YIELD_SECONDS);stage='clock'
 except BaseException as exc:
  record_failure(stats,stage,exc)
  raise
 finally:
  stats['elapsedMs']=int((clock()-started)*1000)
 return stats
