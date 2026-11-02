"""Read-only eligibility for one restart of a clean, non-manual completed run."""
import hashlib,json,os,re,stat,time
from pathlib import Path
A='org.codex.siriremote.autocoord20261029v';B='org.codex.siriremote.hidgattrouterb20261029u'
RUN=re.compile(r'^[a-f0-9]{32}$')
def strict(raw):
 def pairs(rows):
  result={}
  for k,v in rows:
   if k in result:raise ValueError('duplicate key')
   result[k]=v
  return result
 return json.loads(raw,object_pairs_hook=pairs)
def read(p,uid,modes=(0o640,),limit=16384):
 before=p.lstat()
 if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=uid or before.st_gid!=5000 or stat.S_IMODE(before.st_mode) not in modes or before.st_size>limit:raise ValueError('record metadata')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  st=os.fstat(fd);raw=os.read(fd,limit+1);end=os.fstat(fd);named=p.lstat()
  key=lambda s:(s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
  if key(before)!=key(st) or key(st)!=key(end) or key(end)!=key(named) or len(raw)!=st.st_size:raise ValueError('record changed')
  return strict(raw),hashlib.sha256(raw).hexdigest()
 finally:os.close(fd)
def no_apps(root,proc):
 names=list(proc.iterdir())
 if len(names)>8192:raise ValueError('process bound')
 for p in names:
  if not p.name.isdecimal():continue
  try:raw=(p/'cmdline').read_bytes()
  except FileNotFoundError:continue
  if len(raw)>131072:raise ValueError('cmdline bound')
  if any(arg.startswith(str(root/app).encode()+b'/') for arg in raw.split(b'\0') for app in (A,B)):return False
 return True
def inspect(root=Path('/media/developer/apps/usr/palm/applications'),proc=Path('/proc'),now=time.time):
 root=Path(root);proc=Path(proc);a=root/A/'state';b=root/B/'state'
 if not no_apps(root,proc):return {'eligible':False,'reason':'input-program-live'}
 epoch=int(now()*1000);uptime=float((proc/'uptime').read_text().split()[0]);boot_start=epoch-int(uptime*1000)
 if uptime<0:raise ValueError('invalid uptime')
 names=list(b.iterdir())
 if len(names)>4096:raise ValueError('state bound')
 candidates=[]
 for p in names:
  match=re.fullmatch('receiver-ready-([a-f0-9]{32})\\.json',p.name)
  if not match:continue
  v,h=read(p,5636,(0o640,0o775),2048)
  if v.get('appId')!=B or v.get('run')!=match[1] or v.get('stage')!='receiver-ready':raise ValueError('ready mismatch')
  when=v.get('epochMs')
  if type(when) is not int:raise ValueError('ready time')
  # A previous boot's completed run cannot reopen this boot's launch claim.
  if boot_start+2000<=when<=epoch:candidates.append((when,v,h))
 if not candidates:return {'eligible':False,'reason':'no-current-boot-ready-run'}
 candidates.sort(key=lambda x:x[0]);when,ready,ready_hash=candidates[-1]
 if len(candidates)>1 and candidates[-2][0]==when:raise ValueError('ambiguous latest run')
 run=ready['run']
 if (b/'borrowed-active').exists() or (b/'recovery-request.json').exists():return {'eligible':False,'reason':'unfinished-input-state'}
 try:result,result_hash=read(b/('receiver-result-'+run+'.json'),5636)
 except FileNotFoundError:return {'eligible':False,'reason':'result-unavailable'}
 if (result.get('run')!=run or result.get('appId')!=B or result.get('status')!='complete' or result.get('sensorStopVerified') is not True or result.get('journalArchived') is not True):return {'eligible':False,'reason':'clean-sensor-stop-unconfirmed'}
 receiver=result.get('process',{})
 if receiver.get('pid')!=ready.get('pid') or receiver.get('startTicks')!=ready.get('startTicks'):raise ValueError('receiver identity mismatch')
 controller=None;controller_hash=None
 for name in ('controller-start.json','controller-start-complete-'+run+'.json'):
  try:v,h=read(b/name,6959,(0o660,0o775))
  except FileNotFoundError:continue
  if v.get('run')==run:
   if controller is not None:raise ValueError('duplicate controller record')
   controller=v;controller_hash=h
 if controller is None or controller.get('appId')!=A:raise ValueError('controller missing')
 cp=controller['process'];rp=receiver
 for p,uid in ((cp,6959),(rp,5636)):
  if type(p.get('pid')) is not int or p['pid']<=0 or type(p.get('startTicks')) is not int or not 0<p['startTicks']<=uptime*100+100 or p.get('status',{}).get('Uid','').split()!=[str(uid)]*4:raise ValueError('process metadata')
  try:fields=(proc/str(p['pid'])/'stat').read_text();fields=fields[fields.rfind(')')+2:].split()
  except FileNotFoundError:continue
  if int(fields[19])==p['startTicks']:return {'eligible':False,'reason':'original-process-present'}
 instances=[];anames=list(a.iterdir())
 if len(anames)>4096:raise ValueError('controller state bound')
 for p in anames:
  if not re.fullmatch('controller-instance-[a-f0-9]{32}\\.json',p.name):continue
  v,h=read(p,6959,(0o640,0o775),1024)
  if v.get('pid')==cp['pid'] and v.get('startTicks')==cp['startTicks']:instances.append(v)
 if len(instances)!=1 or not RUN.fullmatch(instances[0].get('instance','')):raise ValueError('controller instance ambiguous')
 instance=instances[0]['instance']
 if (a/('developer-stop-'+instance+'.json')).exists():return {'eligible':False,'reason':'manual-stop-retained'}
 try:intent,_=read(a/'receiver-launch-intent.json',6959)
 except FileNotFoundError:intent=None
 if intent is not None and intent.get('run')!=run:return {'eligible':False,'reason':'different-launch-intent'}
 journal=b/('borrowed-complete-'+run)
 js=journal.lstat()
 if not stat.S_ISDIR(js.st_mode) or js.st_uid!=5636 or js.st_gid!=5000:raise ValueError('journal directory')
 rows=list(journal.iterdir())
 if not 1<=len(rows)<=16:raise ValueError('journal bound')
 records=[read(p,5636)[0] for p in sorted(rows)]
 if any(v.get('run')!=run for v in records) or records[-1].get('stage')!='sensor-zero-confirmed':raise ValueError('journal sensor stop')
 if not no_apps(root,proc):return {'eligible':False,'reason':'input-program-started'}
 proof={'run':run,'controllerPid':cp['pid'],'controllerStartTicks':cp['startTicks'],'receiverPid':rp['pid'],'receiverStartTicks':rp['startTicks'],'instance':instance,'readySha256':ready_hash,'resultSha256':result_hash,'controllerSha256':controller_hash}
 return {'eligible':True,'run':run,'fingerprint':hashlib.sha256(json.dumps(proof,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
if __name__=='__main__':
 try:result=inspect()
 except Exception as error:
  labels={'/proc/uptime':'process-uptime','/media/developer/apps/usr/palm/applications/'+A+'/state':'controller-state','/media/developer/apps/usr/palm/applications/'+B+'/state':'receiver-state'}
  filename=getattr(error,'filename',None)
  result={'eligible':False,'reason':'evidence-unavailable-'+type(error).__name__,'component':labels.get(filename,Path(filename).name if filename and len(filename)<512 else None)}
 print(json.dumps(result,separators=(',',':')))
