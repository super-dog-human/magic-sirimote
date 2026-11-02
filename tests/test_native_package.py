import ast
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import build_native
import build_support


class NativePackageTest(unittest.TestCase):
    def test_generic_single_native_package_is_reproducible_and_requires_explicit_ir_action(self):
        with tempfile.TemporaryDirectory() as path:
            outputs = [Path(path) / 'a', Path(path) / 'b']
            results = [build_native.build(out) for out in outputs]
            name = results[0]['package']['package']
            self.assertEqual((outputs[0] / name).read_bytes(), (outputs[1] / name).read_bytes())
            for result in results:
                self.assertFalse(result['controlsRemote'])
                self.assertFalse(result['deviceIdentitiesEmbedded'])
                self.assertFalse(result['registersAutomaticStartup'])
                self.assertTrue(result['programsInfrared'])
                self.assertFalse(result['automaticInfraredWrites'])
                self.assertFalse(result['hardwareValidated'])
            members = build_support.read_ar((outputs[0] / name).read_bytes())
            with tarfile.open(fileobj=io.BytesIO(members['control.tar.gz']), mode='r:gz') as control:
                self.assertEqual(control.getnames(), ['control'])
                self.assertIn(b'Description: Magic Sirimote native settings and IR programming preview',
                              control.extractfile('control').read())
            with tarfile.open(fileobj=io.BytesIO(members['data.tar.gz']), mode='r:gz') as archive:
                files = {entry.name: archive.extractfile(entry).read() for entry in archive if entry.isfile()}
                self.assertEqual({name: hashlib.sha256(data).hexdigest() for name, data in files.items()}, results[0]['package']['files'])
                self.assertEqual(hashlib.sha256((outputs[0] / name).read_bytes()).hexdigest(), results[0]['package']['packageSha256'])
                appinfos = [name for name in files if name.endswith('/appinfo.json')]
                self.assertEqual(len(appinfos), 1)
                info = json.loads(files[appinfos[0]])
                self.assertEqual(info['id'], 'org.magicsirimote.app')
                self.assertEqual(info['type'], 'native')
                self.assertEqual(info['requiredACG'], [])
                self.assertFalse(any('/services/' in name or name.endswith('/settings.json') for name in files))
                prefix = 'usr/palm/applications/org.magicsirimote.app/'
                expected = {'appinfo.json', 'device_check.py', 'entry', 'entry.py',
                            'graphics.py', 'icon.png', 'ir_packets.py', 'ir_programmer.py',
                            'ir_screen.py', 'native_luna.py', 'native_probe.py', 'settings.py',
                            'tv_assignments.py', 'state/README.txt'}
                self.assertEqual(set(files), {prefix + item for item in expected} |
                                 {'usr/palm/packages/org.magicsirimote.app/packageinfo.json'})
                modules = {Path(path).stem: content for path, content in files.items() if path.endswith('.py')}
                visited, pending = set(), ['native_probe']
                while pending:
                    module = pending.pop()
                    if module in visited:
                        continue
                    visited.add(module)
                    for node in ast.walk(ast.parse(modules[module])):
                        imports = ([item.name.split('.')[0] for item in node.names] if isinstance(node, ast.Import)
                                   else [node.module.split('.')[0]] if isinstance(node, ast.ImportFrom) and node.module else [])
                        pending.extend(item for item in imports if item in modules and item not in visited)
                self.assertEqual(visited, set(modules), 'Bundled Python modules must be used by the app')
                for name in build_native.SOURCES:
                    compile(files[prefix + name], name, 'exec')
                self.assertTrue(files[prefix + 'entry'].startswith(b'\x7fELF'))
                compile(files[prefix + 'ir_packets.py'], 'ir_packets.py', 'exec')
                state = archive.getmember(prefix + 'state')
                self.assertEqual((state.uid, state.gid, state.mode), (5999, 5000, 0o770))


if __name__ == '__main__':
    unittest.main()
