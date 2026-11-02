"""Read-only package and process attestation for a future TV-local controller.

Inputs are a pinned package record and trusted paths. Inaccessible /proc or
package metadata is unknown and raises; no process or filesystem mutation.
"""
import hashlib,json,os,re,stat
from pathlib import Path
def _directory(path):
 s=Path(path).lstat()
 if not stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode):raise RuntimeError('unsafe-directory')
 return s
def _read_file(root,relative,limit=524288):
 if not isinstance(relative,str) or relative.startswith('/') or any(x in ('','.','..') for x in relative.split('/')):raise RuntimeError('unsafe-name')
 p=Path(root)
 for part in relative.split('/')[:-1]:p=p/part;_directory(p)
 p=p/relative.split('/')[-1];before=p.lstat()
 if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_size>limit:raise RuntimeError('unsafe-file')
 fd=os.open(str(p),os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  s=os.fstat(fd)
  if (s.st_dev,s.st_ino,s.st_size)!=(before.st_dev,before.st_ino,before.st_size):raise RuntimeError('file-changed')
  with os.fdopen(fd,'rb') as f:fd=None;raw=f.read(limit+1)
 finally:
  if fd is not None:os.close(fd)
 if len(raw)>limit:raise RuntimeError('oversize-file')
 return raw
def package_matches(app_path,pkg_path,record):
 if not isinstance(record,dict) or not isinstance(record.get('files'),dict) or not 1<=len(record['files'])<=64:raise RuntimeError('invalid-pinned-package')
 _directory(app_path);_directory(pkg_path)
 for name,digest in record['files'].items():
  if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest) or hashlib.sha256(_read_file(app_path,name)).hexdigest()!=digest:return False
 info=json.loads(_read_file(app_path,'appinfo.json'));pkg=_read_file(pkg_path,'packageinfo.json')
 return info.get('id')==record.get('appId') and hashlib.sha256(pkg).hexdigest()==record.get('packageInfoSha256') and json.loads(pkg).get('id')==record.get('appId')
def _start_ticks(path):
 value=path.read_text();end=value.rfind(')')
 if end<0:raise RuntimeError('proc-stat-invalid')
 fields=value[end+2:].split()
 if len(fields)<20 or not fields[19].isdigit():raise RuntimeError('proc-stat-invalid')
 return int(fields[19])
def candidate_pids(app_path,proc_path='/proc'):
 proc=Path(proc_path);_directory(proc);expected=['/usr/bin/python3','-I','-B',str(Path(app_path)/'native_probe.py')];found=[]
 for p in proc.iterdir():
  if not p.name.isdecimal():continue
  try:args=[x.decode('utf8') for x in (p/'cmdline').read_bytes().split(b'\0') if x]
  except FileNotFoundError:continue
  except (OSError,UnicodeError):raise RuntimeError('process-scan-incomplete')
  if args==expected:found.append(int(p.name))
 return found
def matching_processes(app_path,process_record,proc_path='/proc',python_path='/usr/bin/python3',allow_exe_permission_denied=False):
 if not isinstance(process_record,dict):raise ValueError('missing-process-record')
 proc=Path(proc_path);_directory(proc);py=os.stat(python_path);matches=[]
 expected=['/usr/bin/python3','-I','-B',str(Path(app_path)/'native_probe.py')]
 for p in proc.iterdir():
  if not p.name.isdecimal():continue
  try:
   args=(p/'cmdline').read_bytes().split(b'\0');args=[x.decode('utf8') for x in args if x]
  except FileNotFoundError:continue
  except (OSError,UnicodeError):raise RuntimeError('process-scan-incomplete')
  if args!=expected:continue
  try:start=_start_ticks(p/'stat')
  except (OSError,ValueError,RuntimeError):raise RuntimeError('process-stat-unavailable')
  exe_verified=True
  try:exe=os.stat(p/'exe')
  except PermissionError:
   if not allow_exe_permission_denied:raise RuntimeError('process-exe-unavailable')
   exe=None;exe_verified=False
  except OSError:raise RuntimeError('process-exe-unavailable')
  try:
   lines=(p/'status').read_text().splitlines();values={k:v.strip() for line in lines if ':' in line for k,v in [line.split(':',1)] if k in ('Uid','Gid','Groups','CapEff')};end=_start_ticks(p/'stat')
  except (OSError,ValueError,RuntimeError):raise RuntimeError('process-status-unavailable')
  if start!=end or (exe is not None and (exe.st_dev,exe.st_ino)!=(py.st_dev,py.st_ino)):raise RuntimeError('process-identity-changed')
  if any(values.get(k)!=process_record.get(k) for k in ('Uid','Gid','Groups','CapEff')):raise RuntimeError('process-record-mismatch')
  u=values.get('Uid','').split();g=values.get('Gid','').split()
  if len(u)!=4 or len(set(u))!=1 or u[0]=='0' or len(g)!=4 or set(g)!={'5000'} or values.get('CapEff')!='0000000000000000':raise RuntimeError('process-privilege-mismatch')
  row={'pid':int(p.name),'startTicks':start}
  if not exe_verified:row['exeVerified']=False
  matches.append(row)
 return matches
def attest_pair(config,process_records,store,proc_path='/proc',python_path='/usr/bin/python3',allow_exe_permission_denied=False):
 """Return explicit false for every missing or inaccessible piece of evidence."""
 out={'aPackageVerified':False,'bPackageVerified':False,'aSingleLiveProcess':False,'bSingleLiveProcess':False,'noResultsYet':False}
 if not isinstance(config,dict) or set(config)!={'A','B'} or not isinstance(process_records,dict):return out
 for role,prefix in (('A','a'),('B','b')):
  try:
   c=config[role];app=c['appPath'];pkg=c['packagePath'];record=c['record']
   out[prefix+'PackageVerified']=package_matches(app,pkg,record) is True
   if out[prefix+'PackageVerified']:
    matches=matching_processes(app,process_records.get(role),proc_path,python_path,allow_exe_permission_denied=allow_exe_permission_denied)
    out[prefix+'SingleLiveProcess']=len(matches)==1
    if len(matches)==1:out[prefix+'ExecutableVerified']=matches[0].get('exeVerified') is not False
  except (OSError,ValueError,TypeError,KeyError,RuntimeError):pass
 try:out['noResultsYet']=store.read('a-result') is None and store.read('b-result') is None
 except (OSError,ValueError,TypeError,KeyError,RuntimeError):pass
 return out

def diagnose_pair(config,process_records,proc_path='/proc',python_path='/usr/bin/python3'):
 """Bounded reason categories; never converts unavailable evidence to success."""
 result={}
 for role in ('A','B'):
  c=config.get(role) if isinstance(config,dict) else None
  if not isinstance(c,dict):result[role]='configuration-invalid';continue
  try:
   if not package_matches(c['appPath'],c['packagePath'],c['record']):result[role]='package-mismatch';continue
  except (OSError,ValueError,TypeError,KeyError,RuntimeError):result[role]='package-unavailable';continue
  if not isinstance(process_records,dict) or not isinstance(process_records.get(role),dict):result[role]='process-record-missing';continue
  try:
   found=matching_processes(c['appPath'],process_records[role],proc_path,python_path)
   result[role]='verified' if len(found)==1 else ('process-absent' if not found else 'process-ambiguous')
  except RuntimeError as e:
   result[role]=str(e) if str(e) in ('process-scan-incomplete','process-identity-unavailable','process-stat-unavailable','process-exe-unavailable','process-status-unavailable','process-identity-changed','process-record-mismatch','process-privilege-mismatch') else 'process-unavailable'
  except (OSError,ValueError,TypeError,KeyError):result[role]='process-unavailable'
 return result
