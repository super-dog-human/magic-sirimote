"""Offline failure tests; optional real Apple archive supplied outside Git."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('firmware', ROOT / 'tools/firmware/firmware.py')
firmware = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(firmware)
FIXTURE = os.environ.get('SIRIMOTE_TEST_FIRMWARE')


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / 'cache'

    def test_manual_bad_archive_never_uses_network_or_changes_file(self):
        source = self.root / 'manual.zip'
        source.write_bytes(b'invalid')
        with patch.object(firmware.subprocess, 'run') as network:
            with self.assertRaises(ValueError):
                firmware.acquire(source, self.cache)
            network.assert_not_called()
        self.assertEqual(source.read_bytes(), b'invalid')
        self.assertFalse(self.cache.exists())

    def test_bad_cache_is_not_replaced(self):
        self.cache.mkdir()
        cached = self.cache / 'a1513-0257.zip'
        cached.write_bytes(b'invalid cached archive')
        with patch.object(firmware.subprocess, 'run') as network:
            with self.assertRaises(ValueError):
                firmware.acquire(None, self.cache)
            network.assert_not_called()
        self.assertEqual(cached.read_bytes(), b'invalid cached archive')

    def test_correct_size_wrong_hash_rejected_before_zip_processing(self):
        source = self.root / 'wrong.zip'
        source.write_bytes(bytes(firmware.ARCHIVE_SIZE))
        with patch.object(firmware.zipfile, 'ZipFile') as unzip:
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                firmware.validate_archive(source)
            unzip.assert_not_called()

    def test_invalid_download_is_never_published(self):
        def download(command, **kwargs):
            Path(command[command.index('--output') + 1]).write_bytes(b'not firmware')
        with patch.object(firmware.subprocess, 'run', side_effect=download):
            with self.assertRaises(ValueError):
                firmware.acquire(None, self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_failed_download_cleans_partial_file(self):
        def download(command, **kwargs):
            Path(command[command.index('--output') + 1]).write_bytes(b'partial')
            raise subprocess.CalledProcessError(28, command)
        with patch.object(firmware.subprocess, 'run', side_effect=download):
            with self.assertRaises(subprocess.CalledProcessError):
                firmware.acquire(None, self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_launcher_rejects_conflicting_modes_before_device_access(self):
        result = subprocess.run(['bash', str(ROOT / 'tools/firmware/update-a1513.sh'),
                                 '--apply', '--check'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Choose exactly one mode', result.stderr)


@unittest.skipUnless(FIXTURE, 'Set SIRIMOTE_TEST_FIRMWARE to the pinned ZIP for archive tests')
class RealArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(FIXTURE).resolve()
        cls.payloads = firmware.validate_archive(cls.source)

    def test_exact_components_and_versions(self):
        self.assertEqual(set(self.payloads), {'main', 'radio'})
        self.assertEqual(firmware.validate_component(self.payloads['main']), (1, 0x257))
        self.assertEqual(firmware.validate_component(self.payloads['radio']), (0x30, 0x120))

    def test_tampered_signed_components_rejected(self):
        for name, original in self.payloads.items():
            # Header, payload, digest and signature are independently covered.
            for offset in (24, 140, len(original) - 280, len(original) - 1):
                with self.subTest(component=name, offset=offset):
                    damaged = bytearray(original)
                    damaged[offset] ^= 1
                    with self.assertRaises(ValueError):
                        firmware.validate_component(damaged)

    def test_truncated_component_rejected(self):
        for original in self.payloads.values():
            with self.assertRaises(ValueError):
                firmware.validate_component(original[:-1])

    def test_manual_valid_archive_never_uses_network(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / 'unused'
            with patch.object(firmware.subprocess, 'run') as network:
                path, payloads = firmware.acquire(self.source, cache)
                network.assert_not_called()
            self.assertEqual(path, self.source)
            self.assertEqual(payloads, self.payloads)
            self.assertFalse(cache.exists())

    def test_verified_download_published_then_reused_without_network(self):
        archive = self.source.read_bytes()
        def download(command, **kwargs):
            self.assertEqual(command[-1], firmware.URL)
            self.assertEqual(command[command.index('--proto') + 1], '=https')
            self.assertEqual(command[command.index('--proto-redir') + 1], '=https')
            Path(command[command.index('--output') + 1]).write_bytes(archive)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(firmware.subprocess, 'run', side_effect=download) as network:
                path, payloads = firmware.acquire(None, directory)
                self.assertEqual(payloads, self.payloads)
                self.assertEqual(path.read_bytes(), archive)
                _, reused = firmware.acquire(None, directory)
                self.assertEqual(reused, payloads)
                self.assertEqual(network.call_count, 1)
                self.assertEqual(list(Path(directory).resolve().iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
