"""A hidden settings wrapper must not strand a finished receiver."""
import ctypes as C
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/integrated'),str(ROOT/'src/native')]
import native_manager as manager
from graphics import Canvas

class HiddenReceiverExitTests(unittest.TestCase):
 def test_window_state_events_are_not_button_events(self):
  canvas=Canvas.__new__(Canvas);pending=[2,7,12,13,11]
  def poll(buf):
   if not pending:return 0
   raw=bytearray(64);raw[:4]=(0x200).to_bytes(4,'little');raw[12]=pending.pop(0)
   C.memmove(buf,bytes(raw),64);return 1
  canvas.poll=poll
  self.assertEqual(list(canvas.events()),[('window-active',False),('window-active',False),('window-active',True),('window-active',False)])

 def scenario(self,*,hide_at,exit_at,pause=False,program_until=0,intentional_stop=False):
  app=MagicMock();app.reset=app.pairing=app.infrared=None
  app.saving_assignments=False;app.stop_requested=intentional_stop;app.done=False
  app.values={'remoteAddress':'','adapterAddress':''}
  worker=MagicMock();step=[0]
  worker.poll.side_effect=lambda: 2 if step[0]>=exit_at else None
  bus=MagicMock();bus.__enter__.return_value=bus
  def events():
   step[0]+=1
   if step[0]>10:raise AssertionError('Hidden wrapper did not exit')
   app.saving_assignments=step[0]<program_until
   if step[0]==1:return [('relaunch',{})]
   if pause and step[0]==hide_at:return [('pause',{})]
   return []
  bus.events.side_effect=events
  canvas=MagicMock()
  def canvas_events():
   if not pause and step[0]==hide_at:return [('window-active',False)]
   if intentional_stop and step[0]==7:return [('close',None)]
   return []
  canvas.events.side_effect=canvas_events
  app.handle.side_effect=lambda *_:setattr(app,'done',True)
  with ExitStack() as stack:
   for name,value in [('NativeBus',bus),('RuntimeSetup',app),('pending_worker',True),('Canvas',canvas)]:
    stack.enter_context(patch.object(manager,name,return_value=value))
   stack.enter_context(patch('native_manager.subprocess.Popen',return_value=worker))
   for name in ('write_status','signal.signal','time.sleep','os.set_blocking','os.close'):
    stack.enter_context(patch('native_manager.'+name))
   stack.enter_context(patch('native_manager.os.open',return_value=123))
   stack.enter_context(patch('native_manager.os.read',side_effect=BlockingIOError))
   manager.main()
  worker.terminate.assert_not_called()
  return step[0],app

 def test_home_before_worker_exit_does_not_terminate_live_receiver(self):
  count,_=self.scenario(hide_at=2,exit_at=4);self.assertEqual(count,4)
 def test_home_after_worker_exit_releases_wrapper(self):
  count,app=self.scenario(hide_at=4,exit_at=2);self.assertEqual(count,4)
  app.handle.assert_not_called()
 def test_late_native_pause_also_releases_wrapper(self):
  count,_=self.scenario(hide_at=4,exit_at=2,pause=True);self.assertEqual(count,4)
 def test_programming_is_not_interrupted(self):
  count,_=self.scenario(hide_at=2,exit_at=3,program_until=6);self.assertEqual(count,6)
 def test_intentional_settings_stop_still_waits_for_user_close(self):
  count,_=self.scenario(hide_at=2,exit_at=3,intentional_stop=True);self.assertEqual(count,7)

if __name__=='__main__':unittest.main()
