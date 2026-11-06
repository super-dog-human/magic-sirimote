"""Exercise the user-facing shell bootstrap with isolated command availability."""
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'install.sh'

class ShellInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.bin=self.root/'bin';self.bin.mkdir()
        self.script=self.root/'install.sh';shutil.copyfile(SCRIPT,self.script)
        self.env=dict(os.environ,PATH=str(self.bin),TMPDIR=str(self.root))

    def command(self,name,body):
        p=self.bin/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)

    def run_installer(self):
        return subprocess.run(['/bin/sh',str(self.script)],env=self.env,capture_output=True,text=True,timeout=10)

    def test_missing_node_explains_install(self):
        result=self.run_installer()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Node.js is missing',result.stderr)
        self.assertIn('https://nodejs.org',result.stderr)

    def test_old_node_explains_supported_version(self):
        self.command('node','exit 1')
        self.assertIn('Node.js 20 or newer',self.run_installer().stderr)

    def test_missing_npm_explains_install(self):
        self.command('node','exit 0')
        self.assertIn('npm is missing',self.run_installer().stderr)

    def test_missing_builtin_tool_is_named(self):
        self.command('node','exit 0');self.command('npm','exit 0')
        self.assertIn('Missing tool: curl',self.run_installer().stderr)

    def prepare_download(self):
        for tool in ('tar','mktemp','dirname','rm'):
            os.symlink(shutil.which(tool),self.bin/tool)
        self.command('npm','exit 0')
        self.command('node','[ "$1" = -e ] && exit 0\n[ -f "$1" ] || exit 8\nprintf "%s\\n" "driver-started"')

    def test_failed_download_explains_retry_and_cleans_up(self):
        self.prepare_download();self.command('curl','exit 22')
        result=self.run_installer()
        self.assertNotEqual(result.returncode,0);self.assertIn('Download failed',result.stderr)
        self.assertEqual(list(self.root.glob('magic-sirimote-install.*')),[])

    def test_standalone_script_downloads_one_archive_and_launches_driver(self):
        self.prepare_download()
        source=self.root/'source';(source/'tools/installer').mkdir(parents=True)
        (source/'tools/installer/main.js').write_text('driver')
        archive=self.root/'source.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:tar.add(source,arcname='magic-sirimote-main')
        self.env['TEST_ARCHIVE']=str(archive)
        self.command('curl','while [ "$#" -gt 0 ]; do if [ "$1" = --output ]; then shift; /bin/cp "$TEST_ARCHIVE" "$1"; exit; fi; shift; done; exit 1')
        result=self.run_installer()
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('driver-started',result.stdout)
        self.assertEqual(list(self.root.glob('magic-sirimote-install.*')),[])

if __name__=='__main__':unittest.main()
