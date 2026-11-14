"""A cooperative, process-bound stop request for the resident controller.

The producer must publish a complete file atomically in the controller state
folder. This reads only; the caller owns cleanup and must prove safe exit.
"""
import state_permissions
import json, os, re, stat, threading

def request_name(instance):
    if type(instance) is not str or re.fullmatch('[0-9a-f]{32}', instance) is None: raise ValueError('invalid controller instance')
    return 'developer-stop-'+instance+'.json'
MAX = 512

def check_request(dirfd, *, pid, start_ticks, instance, owner_uid=5415, group_gid=5000):
    if type(pid) is not int or pid <= 0 or type(start_ticks) is not int or start_ticks < 0:
        raise ValueError('invalid controller identity')
    if type(instance) is not str or re.fullmatch('[0-9a-f]{32}', instance) is None: raise ValueError('invalid controller instance')
    try:
        fd = os.open(request_name(instance), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dirfd)
    except OSError:
        return False
    try:
        a = os.fstat(fd)
        if not stat.S_ISREG(a.st_mode) or a.st_nlink != 1 or a.st_uid != owner_uid or a.st_gid != group_gid or stat.S_IMODE(a.st_mode) != 0o640 or not 0 < a.st_size <= MAX:
            return False
        raw = os.read(fd, MAX + 1)
        b = os.fstat(fd)
        if len(raw) != a.st_size or (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns) != (b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns):
            return False
        def unique(pairs):
            result = {}
            for k,v in pairs:
                if k in result: raise ValueError('duplicate key')
                result[k] = v
            return result
        data = json.loads(raw, object_pairs_hook=unique)
        return (type(data) is dict and set(data) == {'schema','action','pid','startTicks','instance'}
                and type(data['schema']) is int and data['schema'] == 1
                and data['action'] == 'stop' and type(data['pid']) is int and data['pid'] == pid
                and type(data['startTicks']) is int and data['startTicks'] == start_ticks and data['instance'] == instance)
    except (ValueError, OSError, UnicodeError):
        return False
    finally:
        os.close(fd)

class StopMonitor:
    def __init__(self, dirfd, event, *, pid, start_ticks, instance, owner_uid=5415, group_gid=5000, period=.25):
        if not 0 < period <= 1: raise ValueError('invalid period')
        self.dirfd = os.dup(dirfd); self.event = event; self.closed = threading.Event()
        self.kwargs = dict(pid=pid, start_ticks=start_ticks, instance=instance, owner_uid=owner_uid, group_gid=group_gid)
        self.period = period; self.thread = threading.Thread(target=self._run, daemon=True)
    def start(self): self.thread.start()
    def _run(self):
        try:
            while not self.closed.is_set() and not self.event.is_set():
                if check_request(self.dirfd, **self.kwargs): self.event.set(); return
                self.closed.wait(self.period)
        finally: os.close(self.dirfd)
    def close(self):
        self.closed.set(); self.thread.join(timeout=2)
        if self.thread.is_alive(): raise RuntimeError('stop monitor did not exit')

def publish_request(dirfd, *, pid, start_ticks, instance, owner_uid=5415, group_gid=5000):
    """Publish once without replacing an existing request; caller validates live identity."""
    import secrets
    if os.getuid() != owner_uid or type(pid) is not int or pid <= 0 or type(start_ticks) is not int or start_ticks < 0 or type(instance) is not str or re.fullmatch('[0-9a-f]{32}', instance) is None:
        raise ValueError('invalid publisher or identity')
    d = os.fstat(dirfd)
    if not stat.S_ISDIR(d.st_mode) or d.st_gid != group_gid or stat.S_IMODE(d.st_mode) not in state_permissions.directory_modes():
        raise ValueError('invalid state directory')
    name = '.developer-stop-'+secrets.token_hex(16)+'.tmp'
    raw = (json.dumps({'schema':1,'action':'stop','pid':pid,'startTicks':start_ticks,'instance':instance},separators=(',',':'))+'\n').encode()
    fd = os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=dirfd)
    try:
        os.fchmod(fd,0o640)
        s=os.fstat(fd)
        if s.st_uid != owner_uid or s.st_gid != group_gid or s.st_nlink != 1: raise RuntimeError('publisher identity mismatch')
        with os.fdopen(fd,'wb',closefd=False) as stream: stream.write(raw);stream.flush();os.fsync(stream.fileno())
    finally: os.close(fd)
    # A pre-existing or uncertain destination is never replaced.
    os.link(name, request_name(instance), src_dir_fd=dirfd, dst_dir_fd=dirfd, follow_symlinks=False)
    os.unlink(name,dir_fd=dirfd)
    os.fsync(dirfd)

def publish_instance(dirfd, *, pid, start_ticks, instance, group_gid=5000):
    """Expose this controller generation; no liveness is implied by this record alone."""
    if type(pid) is not int or pid != os.getpid() or type(start_ticks) is not int or start_ticks < 0 or type(instance) is not str or re.fullmatch('[0-9a-f]{32}',instance) is None:
        raise ValueError('invalid current instance')
    name='controller-instance-'+instance+'.json'
    raw=(json.dumps({'schema':1,'pid':pid,'startTicks':start_ticks,'instance':instance},separators=(',',':'))+'\n').encode()
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=dirfd)
    try:
        os.fchmod(fd,0o640); s=os.fstat(fd)
        if s.st_uid != os.getuid() or s.st_gid != group_gid or s.st_nlink != 1: raise RuntimeError('invalid instance owner')
        with os.fdopen(fd,'wb',closefd=False) as stream: stream.write(raw);stream.flush();os.fsync(stream.fileno())
    finally: os.close(fd)
    os.fsync(dirfd)
    return name
