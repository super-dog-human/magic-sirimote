import struct
import unittest
from pathlib import Path
from unittest.mock import patch
import compat


def elf(symbol=b'open64', machine=40, flags=0x5000200):
    # Small ELF32 with a real undefined dynamic symbol and a string table.
    strings=b'\0'+symbol+b'\0'
    data=bytearray(256)
    data[:16]=b'\x7fELF\x01\x01\x01'+bytes(9)
    struct.pack_into('<HHIIIIIHHHHHH',data,16,3,machine,1,0,0,52,flags,52,0,0,40,3,0)
    struct.pack_into('<IIIIIIIIII',data,92,0,3,0,0,172,len(strings),0,0,1,0)
    struct.pack_into('<IIIIIIIIII',data,132,0,11,0,0,208,16,1,0,4,16)
    data[172:172+len(strings)]=strings
    struct.pack_into('<IIIBBH',data,208,1,0,0,0x12,0,0)
    return bytes(data)


class CompatibilityTests(unittest.TestCase):
    def test_changed_code_and_build_flags_are_allowed(self):
        target=bytearray(elf(flags=0x5000204)); target[-1]=99
        compat.validate_elf(target,elf())

    def test_missing_import_is_reported(self):
        with self.assertRaisesRegex(RuntimeError,'open64'):
            compat.validate_elf(elf(b'open'),elf())

    def test_cpu_and_float_abi_mismatch_are_reported(self):
        for target in (elf(machine=183),elf(flags=0x5000400)):
            with self.assertRaisesRegex(RuntimeError,'CPU/ABI'):
                compat.validate_elf(target,elf())

    def test_invalid_or_truncated_elf_rejected(self):
        for target in (b'wrong',elf()[:90],elf()[:215]):
            with self.assertRaises(RuntimeError):compat.elf_info(target)

    def test_real_release_library_is_arm32_soft_float(self):
        info=compat.elf_info(Path(__file__).with_name('libsirimote-hid-guard.so').read_bytes())
        self.assertEqual(info['abi'],(1,1,40,0x200))

    def test_probe_failure_is_reported_without_service_action(self):
        with patch.object(compat.Path,'read_bytes',return_value=elf()), \
             patch.object(compat.subprocess,'run') as run:
            run.return_value.returncode=3;run.return_value.stderr='missing GLIBC symbol'
            with self.assertRaisesRegex(RuntimeError,'GLIBC'):compat.check_runtime(Path('/bundle'))
            self.assertEqual(run.call_args.args[0],['/bundle/guard_probe_arm','/bundle/libsirimote-hid-guard.so'])

if __name__=='__main__':unittest.main()
