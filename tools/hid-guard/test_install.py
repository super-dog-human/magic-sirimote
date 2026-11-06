import unittest
import base64
import hashlib
from pathlib import Path
import tempfile
from unittest.mock import patch
from install import persistent_var,validate_properties
import install
class InstallGuardTests(unittest.TestCase):
 def test_stacked_persistent_var(self):
  info='48 20 0:49 / /var rw - overlay overlay ro\n63 48 179:56 /var /var rw,nosuid - ext4 /dev/mmc rw\n90 63 0:4 / /var/lib/dbus rw - tmpfs tmpfs rw'
  self.assertTrue(all(row['filesystem']=='ext4' for row in persistent_var(info).values()))
 def test_volatile_readonly_or_nested_mount_rejected(self):
  for info in ['48 20 0:49 / /var rw - overlay overlay ro','63 48 179:56 /var /var ro - ext4 /dev/mmc ro','63 48 179:56 /var /var rw - ext4 /dev/mmc rw\n90 63 0:4 / /var/lib/magic-sirimote-hid-guard rw - tmpfs tmpfs rw']:
   with self.assertRaises(RuntimeError):persistent_var(info)
 def test_service_scope(self):
  p={'MainPID':'1725','ActiveState':'active','EnvironmentFiles':'/var/systemd/system/env/bthidmanager.env (ignore_errors=yes)'}
  validate_properties(p)
  for key,value in [('MainPID','0'),('ActiveState','failed'),('EnvironmentFiles','elsewhere'),('BoundBy','other.service'),('Environment','LD_PRELOAD=/another.so')]:
   with self.assertRaises(RuntimeError):validate_properties({**p,key:value})

 def test_root_required_before_any_service_inspection(self):
  with patch.object(install.os,'geteuid',return_value=5415), patch.object(install,'props') as props:
   with self.assertRaisesRegex(RuntimeError,'TV root'):install.preflight()
   props.assert_not_called()

 def test_compatible_changed_firmware_does_not_need_known_hash(self):
  with patch.object(install.os,'geteuid',return_value=0), \
       patch.object(install,'digest',side_effect=AssertionError('TV hashes must not gate compatibility')), \
       patch.object(install,'check_runtime') as check, \
       patch.object(install.Path,'read_text',return_value='mountinfo'), \
       patch.object(install,'persistent_var',return_value={}), \
       patch.object(install,'props',return_value={'MainPID':'42'}), \
       patch.object(install,'validate_properties'), \
       patch.object(install.os.path,'realpath',return_value='/usr/sbin/bthidmanager'):
   install.preflight()
   check.assert_called_once()

 def test_other_persistent_filesystems_and_unrelated_overrides_allowed(self):
  for filesystem in ('f2fs','btrfs','ubifs','xfs'):
   result=persistent_var('1 0 179:1 / / rw - '+filesystem+' /dev/flash rw')
   self.assertTrue(all(row['filesystem']==filesystem for row in result.values()))
  validate_properties({'MainPID':'42','ActiveState':'active','PartOf':'bluetooth.target',
                       'DropInPaths':'/etc/systemd/system/bthidmanager.service.d/custom.conf',
                       'EnvironmentFiles':'/etc/extra.env (ignore_errors=yes) '+str(install.ENV_FILE)+' (ignore_errors=yes)'})

 def test_runtime_incompatibility_does_not_restart_or_write(self):
  with patch.object(install.os,'geteuid',return_value=0), \
       patch.object(install,'check_runtime',side_effect=RuntimeError('missing open64')), \
       patch.object(install,'restart') as restart, patch.object(install,'write_new') as write:
   with self.assertRaisesRegex(RuntimeError,'open64'):install.preflight()
   restart.assert_not_called();write.assert_not_called()

 def test_atomic_publication_never_overwrites_configuration(self):
  with tempfile.TemporaryDirectory() as folder:
   target=Path(folder)/'environment'
   target.write_text('existing')
   with self.assertRaises(FileExistsError):install.write_new(target,b'new',0o600)
   self.assertEqual(target.read_text(),'existing')
   self.assertFalse(target.with_name('environment.pending').exists())

 def test_failed_activation_removes_only_new_files_and_restores_service(self):
  with tempfile.TemporaryDirectory() as folder:
   base=Path(folder);dest=base/'guard';env=base/'env'/'bthidmanager.env'
   lib=dest/'libsirimote-hid-guard.so'
   data=b'test library'
   read_text=Path.read_text
   def mkdir(path,created):
    path.mkdir();created.append(str(path))
   with patch.multiple(install,FIX_DIR=dest,FIX_LIB=lib,ENV_FILE=env,ENV_CONTENT='LD_PRELOAD='+str(lib)+'\n'), \
        patch.object(install,'preflight',return_value=({'MainPID':'10'},{})), \
        patch.object(install.Path,'read_text',autospec=True,side_effect=lambda p,*a,**kw: 'boot-id' if str(p).startswith('/proc/') else read_text(p,*a,**kw)), \
        patch.object(install,'secure_dirs',side_effect=mkdir), \
        patch.object(install.time,'sleep'), patch.object(install,'restart') as restart, \
        patch.object(install,'props',side_effect=[{'MainPID':'10'},{'ActiveState':'active'}]), \
        patch.object(install,'validate_properties'):
    report={}
    with self.assertRaisesRegex(RuntimeError,'did not restart'):
     install.install_fix({'libraryBase64':base64.b64encode(data).decode(),
                         'librarySha256':hashlib.sha256(data).hexdigest(),
                         'rollbackSource':'rollback'},report)
    self.assertEqual(restart.call_count,2)
    self.assertEqual(report['status'],'rolled-back')
    self.assertFalse(dest.exists())
    self.assertFalse(env.exists())

 def test_shipped_payload_checksums(self):
  directory=Path(__file__).parent
  for line in (directory/'SHA256SUMS').read_text().splitlines():
   expected,name=line.split('  ')
   self.assertEqual(install.digest(directory/name),expected,name)
if __name__=='__main__':unittest.main()
