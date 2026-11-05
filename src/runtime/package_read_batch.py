"""Fresh package reads sharing directory handles within one verification pass."""
import os,stat


def fingerprint(s):
    return (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_size,
            s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)


class PackageReadBatch:
    def __init__(self,root):
        self.root=os.fspath(root);self.directories={};self.closed=False

    def __enter__(self):
        try:
            self._directory(())
            return self
        except BaseException:
            self.close();raise

    def _directory(self,parts):
        if self.closed:raise RuntimeError('package read batch closed')
        if parts in self.directories:return self.directories[parts][0]
        if len(self.directories)>=384:raise RuntimeError('package directory limit')
        parent=self._directory(parts[:-1]) if parts else None
        name=parts[-1] if parts else self.root
        before=os.stat(name,dir_fd=parent,follow_symlinks=False)
        if not stat.S_ISDIR(before.st_mode):raise RuntimeError('unsafe-directory')
        fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
        # Retain the descriptor before checking so all error paths close it.
        self.directories[parts]=(fd,fingerprint(before))
        if fingerprint(os.fstat(fd))!=fingerprint(before):raise RuntimeError('package directory changed')
        return fd

    def read(self,relative,limit=524288):
        if (type(relative) is not str or relative.startswith('/')
                or any(p in ('','.','..') for p in relative.split('/'))):
            raise RuntimeError('unsafe-name')
        parts=tuple(relative.split('/'));parent=self._directory(parts[:-1]);name=parts[-1]
        before=os.stat(name,dir_fd=parent,follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size>limit:raise RuntimeError('unsafe-file')
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=parent)
        try:
            if fingerprint(os.fstat(fd))!=fingerprint(before):raise RuntimeError('file-changed')
            chunks=[];total=0
            while total<=limit:
                chunk=os.read(fd,min(65536,limit+1-total))
                if not chunk:break
                chunks.append(chunk);total+=len(chunk)
            if total>limit:raise RuntimeError('oversize-file')
            if (total!=before.st_size or fingerprint(os.fstat(fd))!=fingerprint(before)
                    or fingerprint(os.stat(name,dir_fd=parent,follow_symlinks=False))!=fingerprint(before)):
                raise RuntimeError('file-changed')
            return b''.join(chunks)
        finally:os.close(fd)

    def verify_directories(self):
        if self.closed:raise RuntimeError('package read batch closed')
        for parts,(fd,expected) in self.directories.items():
            parent=self.directories[parts[:-1]][0] if parts else None
            name=parts[-1] if parts else self.root
            if (fingerprint(os.fstat(fd))!=expected
                    or fingerprint(os.stat(name,dir_fd=parent,follow_symlinks=False))!=expected):
                raise RuntimeError('package directory changed')

    def close(self):
        if self.closed:return
        self.closed=True;failed=False
        for fd,_ in reversed(list(self.directories.values())):
            try:os.close(fd)
            except OSError:failed=True
        self.directories.clear()
        if failed:raise RuntimeError('package directory close unconfirmed')

    def __exit__(self,kind,value,trace):
        try:
            if kind is None:self.verify_directories()
        finally:self.close()
