import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from package_read_batch import PackageReadBatch


class PackageReadBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'runtime').mkdir()
        (self.root/'runtime/a.py').write_bytes(b'first');(self.root/'runtime/b.py').write_bytes(b'second')
    def test_reads_every_file_with_one_handle_per_directory(self):
        with patch('package_read_batch.os.open',wraps=os.open) as opened:
            with PackageReadBatch(self.root) as batch:
                self.assertEqual(batch.read('runtime/a.py'),b'first')
                self.assertEqual(batch.read('runtime/b.py'),b'second')
                self.assertEqual(batch.read('runtime/a.py'),b'first')
                fds=[x[0] for x in batch.directories.values()]
        self.assertEqual(sum(bool(c.args[1]&os.O_DIRECTORY) for c in opened.call_args_list),2)
        self.assertEqual(opened.call_count,5)
        for fd in fds:
            with self.assertRaises(OSError):os.fstat(fd)
    def test_file_and_directory_symlinks_are_rejected(self):
        (self.root/'alias').symlink_to(self.root/'runtime',target_is_directory=True)
        (self.root/'runtime/link.py').symlink_to(self.root/'runtime/a.py')
        for name in ('alias/a.py','runtime/link.py'):
            with self.assertRaises(RuntimeError):
                with PackageReadBatch(self.root) as batch:batch.read(name)
    def test_root_symlink_is_rejected(self):
        alias=self.root/'alias';alias.symlink_to(self.root/'runtime',target_is_directory=True)
        with self.assertRaises(RuntimeError):
            with PackageReadBatch(alias):pass
    def test_replaced_directory_rejects_completed_reads(self):
        with self.assertRaises(RuntimeError):
            with PackageReadBatch(self.root) as batch:
                self.assertEqual(batch.read('runtime/a.py'),b'first')
                (self.root/'runtime').rename(self.root/'old')
                (self.root/'runtime').mkdir();(self.root/'runtime/a.py').write_bytes(b'first')
    def test_replaced_root_rejects_completed_reads(self):
        # Keep replacement within the temporary directory for automatic cleanup.
        root=self.root/'runtime'
        with self.assertRaises(RuntimeError):
            with PackageReadBatch(root) as batch:
                batch.read('a.py');root.rename(self.root/'old');root.mkdir()
    def test_same_size_file_write_during_read_is_rejected(self):
        original=os.read;changed=False
        def read(fd,n):
            nonlocal changed
            result=original(fd,n)
            if not changed:
                changed=True;(self.root/'runtime/a.py').write_bytes(b'other')
            return result
        with self.assertRaises(RuntimeError),patch('package_read_batch.os.read',side_effect=read):
            with PackageReadBatch(self.root) as batch:batch.read('runtime/a.py')
    def test_replaced_file_during_read_is_rejected(self):
        original=os.read;changed=False
        def read(fd,n):
            nonlocal changed
            result=original(fd,n)
            if not changed:
                changed=True;p=self.root/'runtime/a.py';p.unlink();p.write_bytes(b'first')
            return result
        with self.assertRaises(RuntimeError),patch('package_read_batch.os.read',side_effect=read):
            with PackageReadBatch(self.root) as batch:batch.read('runtime/a.py')
    def test_short_reads_are_assembled(self):
        original=os.read
        with patch('package_read_batch.os.read',side_effect=lambda fd,n:original(fd,min(2,n))):
            with PackageReadBatch(self.root) as batch:self.assertEqual(batch.read('runtime/b.py'),b'second')
    def test_invalid_paths_and_oversized_file_rejected(self):
        for name in ('../x','/etc/passwd','runtime//a.py','runtime/./a.py',''):
            with self.assertRaises(RuntimeError):
                with PackageReadBatch(self.root) as batch:batch.read(name)
        with self.assertRaises(RuntimeError):
            with PackageReadBatch(self.root) as batch:batch.read('runtime/a.py',limit=4)
    def test_fifo_rejected_without_opening_it(self):
        os.mkfifo(self.root/'runtime/fifo')
        with self.assertRaises(RuntimeError):
            with PackageReadBatch(self.root) as batch:batch.read('runtime/fifo')
    def test_missing_file_closes_cached_directories(self):
        fds=[]
        with self.assertRaises(FileNotFoundError):
            with PackageReadBatch(self.root) as batch:
                batch.read('runtime/a.py');fds=[x[0] for x in batch.directories.values()]
                batch.read('runtime/missing')
        for fd in fds:
            with self.assertRaises(OSError):os.fstat(fd)
    def test_directory_mode_change_rejected(self):
        with self.assertRaises(RuntimeError):
            with PackageReadBatch(self.root) as batch:
                batch.read('runtime/a.py')
                directory=self.root/'runtime';os.chmod(directory,directory.stat().st_mode ^ 0o020)
    def test_content_is_not_cached_between_reads(self):
        with PackageReadBatch(self.root) as batch:
            self.assertEqual(batch.read('runtime/a.py'),b'first')
            (self.root/'runtime/a.py').write_bytes(b'other')
            self.assertEqual(batch.read('runtime/a.py'),b'other')
    def test_uncertain_directory_close_rejects_success_and_closes_others(self):
        original=os.close;closed=[]
        def close(fd):
            original(fd);closed.append(fd)
            if len(closed)==2:raise OSError('close unconfirmed')
        with self.assertRaises(RuntimeError),patch('package_read_batch.os.close',side_effect=close):
            with PackageReadBatch(self.root) as batch:batch.read('runtime/a.py')
        self.assertEqual(len(closed),3)  # File plus both directory descriptors.
    def test_directory_open_failure_closes_existing_handles(self):
        original=os.open;fds=[]
        def opened(name,flags,**kwargs):
            if name=='runtime':raise PermissionError('denied')
            fd=original(name,flags,**kwargs);fds.append(fd);return fd
        with self.assertRaises(PermissionError),patch('package_read_batch.os.open',side_effect=opened):
            with PackageReadBatch(self.root) as batch:batch.read('runtime/a.py')
        for fd in fds:
            with self.assertRaises(OSError):os.fstat(fd)


if __name__=='__main__':unittest.main()
