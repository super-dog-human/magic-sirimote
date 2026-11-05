import sys
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/runtime'))
import takeover_recovery

class TakeoverWindowTests(unittest.TestCase):
 def test_no_request_is_published_while_settings_remains_open(self):
  now=[0.0];stop=Mock();stop.is_set.return_value=False
  stop.wait.side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)
  lease=Mock();lease.held.return_value=True
  prepare=Mock();write=Mock();launch=Mock()
  with patch('runtime_bundle.active',return_value=True),patch.dict(sys.modules,{'control_processes':Mock(processes=lambda:{'ui':[1]})}):
   with self.assertRaisesRegex(RuntimeError,'settings window'):
    takeover_recovery.execute(run='a'*32,watch=Mock(),lease=lease,stop=stop,
     controller_state='/c',receiver_state='/b',controller_app='/ca',receiver_app='/ba',
     receiver_package='/pkg',pin={},prepare_fn=prepare,write_request=write,
     launcher_factory=launch,clock=lambda:now[0],timeout=1)
  prepare.assert_not_called();write.assert_not_called();launch.assert_not_called()
  self.assertGreaterEqual(now[0],1)

if __name__=='__main__':unittest.main()
