"""An exited procfs task must not block settings, or hide another live worker."""
import errno
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src/integrated'), str(ROOT/'src/native')]
import control_processes as control
import ir_programmer as ir


class ProcessExitTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.gone = self.root/'2147483000'
        self.gone.mkdir()
        (self.gone/'cmdline').write_bytes(b'unrelated-process\0')

    def put_receiver(self):
        p = self.root/'2147483001'
        p.mkdir()
        command = ['/usr/bin/python3', '-I', '-B', str(control.bundle.ROOT/'roles/receiver/native_probe.py')]
        (p/'cmdline').write_bytes(('\0'.join(command)+'\0').encode())
        (p/'stat').write_text('2147483001 (python3) '+' '.join(['S']+['0']*18+['1234', '0']))
        (p/'status').write_text('Uid: 5999 5999 5999 5999\nGid: 5000 5000 5000 5000\nCapEff: 0000000000000000\n')
        return p

    def test_exited_command_does_not_prevent_idle_or_hide_live_receiver(self):
        read = Path.read_bytes
        def raced(path):
            if path == self.gone/'cmdline': raise ProcessLookupError(errno.ESRCH, 'No such process')
            return read(path)
        with patch.object(Path, 'read_bytes', raced):
            self.assertFalse(any(control.processes(self.root).values()))
            ir.runtime_idle(self.root, allow_idle_service=True)
            self.put_receiver()
            self.assertEqual(control.processes(self.root)['receiver'][0]['pid'], 2147483001)
            with self.assertRaisesRegex(RuntimeError, 'Stop the other'):
                ir.runtime_idle(self.root, allow_idle_service=True)
            scan = control.processes
            with patch.object(control, 'processes', side_effect=lambda: scan(self.root)):
                with self.assertRaisesRegex(RuntimeError, 'Another input runtime'):
                    control.require_no_other_input()

    def test_exited_identity_read_is_not_a_live_receiver(self):
        p = self.put_receiver()
        read = Path.read_text
        for name in ('stat', 'status'):
            def raced(path, *args, **kwargs):
                if path == p/name: raise ProcessLookupError(errno.ESRCH, 'No such process')
                return read(path, *args, **kwargs)
            with patch.object(Path, 'read_text', raced):
                self.assertFalse(any(control.processes(self.root).values()))

    def test_permission_io_and_other_errors_still_prevent_programming(self):
        for code in (errno.EACCES, errno.EIO, errno.EPERM):
            with patch.object(Path, 'read_bytes', side_effect=OSError(code, 'unavailable')):
                with self.assertRaises(OSError): control.processes(self.root)
                with patch.object(Path, 'stat', return_value=type('Stat', (), {'st_uid':5999})()):
                    with self.assertRaises((OSError, RuntimeError)):
                        ir.runtime_idle(self.root, allow_idle_service=True)

    def test_task_can_exit_between_permission_error_and_owner_check(self):
        with patch.object(Path, 'read_bytes', side_effect=PermissionError(errno.EACCES, 'unavailable')):
            with patch.object(Path, 'stat', side_effect=ProcessLookupError(errno.ESRCH, 'No such process')):
                ir.runtime_idle(self.root, allow_idle_service=True)


if __name__ == '__main__':
    unittest.main()
