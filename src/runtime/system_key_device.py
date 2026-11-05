"""Verified LGE RCU discovery and reopen; no opens occur on import.

The caller owns the returned FD and must close it. Identity and capability
checks do not establish exclusive access to the TV's shared input device.
"""
import errno,fcntl,os,stat,struct,time
from system_key_sink import SystemKeySink,identity_matches,KEYS,EVIOCGBIT_KEY

EVIOCGID=0x80084502
EVIOCGNAME=(2<<30)|(256<<16)|(ord('E')<<8)|0x06
def _same(a,b):return (a.st_dev,a.st_ino,a.st_rdev,a.st_mode,a.st_uid,a.st_gid)==(b.st_dev,b.st_ino,b.st_rdev,b.st_mode,b.st_uid,b.st_gid)
def _identity(fd,st,ioctl):
 name=bytearray(256);ioctl(fd,EVIOCGNAME,name,True)
 raw=bytearray(8);ioctl(fd,EVIOCGID,raw,True);bus,vendor,product,version=struct.unpack('=HHHH',raw)
 return {'name':bytes(name).split(b'\0',1)[0].decode('utf8','strict'),'characterDevice':stat.S_ISCHR(st.st_mode),'major':os.major(st.st_rdev),'uid':st.st_uid,'gid':st.st_gid,'mode':stat.S_IMODE(st.st_mode),'bus':bus,'vendor':vendor,'product':product,'version':version}
def _supported(fd,ioctl):
 bits=bytearray(160);ioctl(fd,EVIOCGBIT_KEY,bits,True)
 return all(bits[code//8]&(1<<(code%8)) for code in KEYS.values())

def open_verified_system_key(root='/dev/input',*,lstat=os.lstat,open_fn=os.open,fstat=os.fstat,ioctl=fcntl.ioctl,close=os.close,write=os.write,clock=time.monotonic,timeout=20):
 if type(timeout) not in (int,float) or not 0<timeout<=30:raise ValueError('invalid timeout')
 end=clock()+timeout;candidates=[];complete=True
 for index in range(128):
  if clock()>end:raise TimeoutError('system input inventory timed out')
  path=os.path.join(root,'event'+str(index))
  try:before=lstat(path)
  except OSError as e:
   if e.errno!=errno.ENOENT:complete=False
   continue
  if stat.S_ISLNK(before.st_mode) or not stat.S_ISCHR(before.st_mode):complete=False;continue
  try:fd=open_fn(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC)
  except OSError as e:
   if e.errno==errno.ENXIO and os.major(before.st_rdev)==13 and os.minor(before.st_rdev)==64+index:
    try:
     if not _same(before,lstat(path)):complete=False
    except OSError:complete=False
   else:complete=False
   continue
  try:
   opened=fstat(fd);after=lstat(path)
   if not _same(before,opened) or not _same(opened,after):complete=False;continue
   meta=_identity(fd,opened,ioctl)
   if meta['name']=='LGE RCU':
    if not identity_matches(meta) or not _supported(fd,ioctl):complete=False
    else:candidates.append((path,opened))
  except (OSError,ValueError,UnicodeError):complete=False
  finally:close(fd)
 if not complete or len(candidates)!=1:raise RuntimeError('system input inventory incomplete or nonunique')
 path,expected=candidates[0]
 return _open_system_key(path,expected,end=end,lstat=lstat,open_fn=open_fn,fstat=fstat,ioctl=ioctl,close=close,write=write,clock=clock)

def _open_system_key(path,expected,*,end,lstat,open_fn,fstat,ioctl,close,write,clock):
 fd=open_fn(path,os.O_RDWR|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  def verify(open_fd):
   if open_fd!=fd:return False
   try:
    current=fstat(fd);named=lstat(path)
    return _same(expected,current) and _same(current,named) and identity_matches(_identity(fd,current,ioctl)) and _supported(fd,ioctl)
   except (OSError,ValueError,UnicodeError):return False
  if clock()>end or not verify(fd):raise RuntimeError('system input changed on reopen')
  sink=SystemKeySink(fd,identity_check=verify,ioctl=ioctl,write=write)
  return sink,fd
 except BaseException:close(fd);raise


def open_system_key_from_record(record,*,root='/dev/input',lstat=os.lstat,open_fn=os.open,
                                fstat=os.fstat,ioctl=fcntl.ioctl,close=os.close,
                                write=os.write,clock=time.monotonic):
 """Use this setup's verified output selection; reverify the reopened FD.

 The caller must obtain the record from a fresh validated output open in
 the same setup attempt; a stale inventory record alone is insufficient.
 """
 import re
 if (type(record) is not dict or record.get('name')!='LGE RCU'
     or record.get('capabilitiesVerified') is not True
     or type(record.get('path')) is not str
     or not re.fullmatch(re.escape(root)+r'/event(?:[0-9]|[1-9][0-9]|1[01][0-9]|12[0-7])',record['path'])):
  raise ValueError('invalid shared system input record')
 expected=lstat(record['path'])
 fields={'dev':expected.st_dev,'inode':expected.st_ino,'rdev':expected.st_rdev,
         'uid':expected.st_uid,'gid':expected.st_gid}
 if (not stat.S_ISCHR(expected.st_mode) or
     any(type(record.get(k)) is not int or record[k]!=v for k,v in fields.items())
     or record.get('mode')!=oct(stat.S_IMODE(expected.st_mode))):
  raise RuntimeError('shared system input changed before reopen')
 return _open_system_key(record['path'],expected,end=clock()+5,lstat=lstat,open_fn=open_fn,
                         fstat=fstat,ioctl=ioctl,close=close,write=write,clock=clock)
