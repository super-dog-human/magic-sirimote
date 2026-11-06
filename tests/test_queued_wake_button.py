import unittest
from unittest.mock import patch
from queued_wake_button import QueuedWakeButton
from combined_controls import CombinedControls
from rolling_receiver import RollingReceiver
from output_bridge import VerifiedOutputs
from fixture_devices import MemoryDevices


class Tests(unittest.TestCase):
 def make(self,**kw):
  self.now=0.
  return QueuedWakeButton(enabled=True,mapping={1:'home',8:'playpause',16:'screen-toggle'},
                         holds={8:'back'},clock=lambda:self.now,**kw)
 def test_queued_press_requires_real_release_and_can_only_deliver_once(self):
  q=self.make();q.feed(bytes.fromhex('fce00800'));self.assertFalse(q.ready())
  q.feed(bytes.fromhex('fce00800'));self.now=.1;q.feed(bytes.fromhex('fc0000'))
  self.assertEqual(q.take(),'playpause');self.assertIsNone(q.take())
  q.feed(bytes.fromhex('fce00800'));q.feed(bytes.fromhex('fc0000'));self.assertIsNone(q.take())
 def test_real_hold_duration_selects_hold_mapping(self):
  q=self.make();q.feed(bytes.fromhex('fce008'));self.now=.8;q.feed(bytes.fromhex('fc0000'))
  self.assertEqual(q.take(),'back')
 def test_normal_first_state_never_enables_response_replay(self):
  for first in ('fc0000','fc0008','fc0080'):
   q=self.make();q.feed(bytes.fromhex(first));q.feed(bytes.fromhex('fce00800'));q.feed(bytes.fromhex('fc0000'))
   self.assertIsNone(q.take())
 def test_conflicting_buttons_chords_and_unknown_forms_do_not_dispatch(self):
  for first,second in [('fce00800','fc0001'),('fce00900','fc0000'),('fce04000','fc0000'),('fce08000','fc0000'),('fce0080000','fc0000')]:
   q=self.make();q.feed(bytes.fromhex(first));q.feed(bytes.fromhex(second));q.feed(bytes.fromhex('fc0000'))
   self.assertIsNone(q.take())
 def test_expired_reversed_or_missing_release_is_dropped(self):
  for now in (3.01,-.1,float('nan')):
   q=self.make();q.feed(bytes.fromhex('fce00800'));self.now=now;q.feed(bytes.fromhex('fc0000'))
   self.assertIsNone(q.take())
  q=self.make();q.feed(bytes.fromhex('fce00800'));self.assertIsNone(q.take())
 def test_ir_and_do_nothing_do_not_emit_tv_actions(self):
  self.now=0.
  q=QueuedWakeButton(enabled=True,mapping={8:None},holds={8:None},clock=lambda:self.now)
  q.feed(bytes.fromhex('fce00800'));q.feed(bytes.fromhex('fc0000'));self.assertIsNone(q.take())


class Screen:
 def __init__(self):self.state=None
 def blocked(self):return self.state!='active'
 def initializing(self):return self.state is None
 def toggle(self):return True


class PipelineTests(unittest.TestCase):
 def make(self,product=0x0266):
  self.now=0.;self.live=True;self.actions=[];self.screen=Screen()
  device=MemoryDevices()
  outputs=VerifiedOutputs(1,2,ioctl_fn=device.ioctl,write_fn=device.write,sleep_fn=lambda _:None)
  rolling=RollingReceiver(outputs,continuity=lambda:self.live,mode_verified=lambda:True,clock=lambda:self.now)
  with patch('touch_surface.current_product',return_value=product),patch('system_buttons.CONFIGURED',None):
   self.controls=CombinedControls(rolling,lambda action:self.actions.append(action) or True,screen_control=self.screen)
   self.controls.start()
  return self.controls
 def feed(self,data):
  self.now+=.02;self.controls.feed_raw(1,bytes.fromhex(data));self.controls.tick()
 def test_tv_capture_delivers_once_after_initial_screen_confirmation(self):
  c=self.make();c.tick()
  self.feed('fce00800');self.feed('fc0000');self.assertEqual(self.actions,[])
  self.screen.state='active';c.tick();self.assertEqual(self.actions,['playpause'])
  self.feed('fc0000');c.tick();self.assertEqual(self.actions,['playpause'])
  # The subsequent deliberate press still works through the normal decoder.
  self.feed('fc0008');self.feed('fc0000');self.assertEqual(self.actions,['playpause','playpause'])
 def test_off_screen_or_lost_connection_discards_pending_action(self):
  for mode in ('off','lost','expired','stop'):
   c=self.make();c.tick();self.feed('fce00800');self.feed('fc0000')
   if mode=='off':self.screen.state='off'
   elif mode=='lost':self.live=False
   elif mode=='expired':self.now=4
   else:c.stop()
   c.tick();self.screen.state='active';c.tick();self.assertEqual(self.actions,[])
 def test_a1962_and_unverified_product_keep_existing_behavior(self):
  for product in (None,0x026d):
   c=self.make(product);self.screen.state='active'
   self.feed('fce00800');self.feed('fc0000');self.assertEqual(self.actions,[])
 def test_failed_output_is_never_replayed(self):
  c=self.make();self.screen.state='active'
  c.emit=lambda action:self.actions.append(action) or False
  self.feed('fce00800');self.feed('fc0000');c.tick();c.tick()
  self.assertEqual(self.actions,['playpause'])

 def media(self):
  from media_toggle import PlaybackSnapshot,MediaAwareSink
  from types import SimpleNamespace
  self.snapshot=PlaybackSnapshot(clock=lambda:self.now)
  self.media_sink=MediaAwareSink(SimpleNamespace(pulse=lambda action:self.actions.append(action) or True),self.snapshot)
  self.controls.emit=self.media_sink.pulse
  self.controls.emit_ready=self.media_sink.ready
 def publish(self,state='playing'):
  self.snapshot.update({'returnValue':True,'foregroundAppInfo':[{'playState':state}]})
 def test_wake_waits_for_real_media_state_without_consuming_or_sending(self):
  c=self.make();self.media();self.screen.state='active'
  self.feed('fce00800');self.feed('fc0000');c.tick()
  self.assertEqual(self.actions,[]);self.assertEqual(self.media_sink.skipped,0)
  self.now=.5;self.publish();c.tick();c.tick()
  self.assertEqual(self.actions,['pause']);self.assertEqual(c.system_actions,1)
 def test_pending_wake_drops_on_timeout_screen_off_and_new_press(self):
  for mode in ('timeout','off','new-press','lost','stop'):
   c=self.make();self.media();self.screen.state='active'
   self.feed('fce00800');self.feed('fc0000')
   if mode=='timeout':self.now=3.1
   elif mode=='off':self.screen.state='off'
   elif mode=='new-press':self.feed('fc0008')
   elif mode=='lost':self.live=False
   else:c.stop()
   c.tick();self.publish();self.screen.state='active';c.tick()
   self.assertEqual(self.actions,[])
 def test_other_wake_buttons_do_not_wait_for_media_state(self):
  c=self.make();self.media();self.screen.state='active'
  self.feed('fce00100');self.feed('fc0000')
  self.assertEqual(self.actions,['home'])
 def test_output_skip_after_media_ready_is_not_retried(self):
  c=self.make();self.media();self.screen.state='active';self.publish()
  self.media_sink.sink.pulse=lambda action:self.actions.append(action) or False
  self.feed('fce00800');self.feed('fc0000');self.publish();c.tick()
  self.assertEqual(self.actions,['pause']);self.assertEqual(c.system_actions,0)

 def test_wake_screen_toggle_uses_current_power_state_once_without_resuming_pointer(self):
  from screen_power import ScreenPowerWorker
  from test_screen_power import Client
  for state,method in [('Screen Off','turnOnScreen'),('Screen Saver','turnOnScreen'),('Active','turnOffScreen')]:
   with self.subTest(state=state):
    c=self.make();self.media()
    w=ScreenPowerWorker(clock=lambda:self.now);client=Client(state)
    c.screen=w;w._step(client);c.tick()
    self.feed('fce01000')
    self.assertFalse(w.requested)
    self.feed('fc0000')
    self.assertTrue(w.requested);self.assertTrue(c.rolling.paused)
    self.assertEqual(c.system_actions,1);self.assertEqual(self.actions,[])
    c.tick();w._step(client);c.tick();self.feed('fc0000');c.tick()
    self.assertEqual(client.calls.count(method),1);self.assertEqual(c.system_actions,1)
    self.assertEqual(self.actions,[])
 def test_wake_screen_toggle_waits_for_initial_power_query(self):
  from screen_power import ScreenPowerWorker
  from test_screen_power import Client
  c=self.make();w=ScreenPowerWorker(clock=lambda:self.now);client=Client('Screen Off');c.screen=w
  self.feed('fce01000');self.feed('fc0000')
  self.assertFalse(w.requested);self.assertEqual(c.system_actions,0)
  w._step(client);c.tick();self.assertTrue(w.requested)
  w._step(client);c.tick();self.assertEqual(client.calls.count('turnOnScreen'),1)
 def test_wake_screen_toggle_is_not_retried_after_lost_write_reply(self):
  from screen_power import ScreenPowerWorker
  from test_screen_power import Client
  c=self.make();w=ScreenPowerWorker(clock=lambda:self.now);client=Client('Screen Off',lost_reply=True);c.screen=w
  w._step(client);self.feed('fce01000');self.feed('fc0000');w._step(client)
  for _ in range(3):c.tick();w._step(client)
  self.assertEqual(client.calls.count('turnOnScreen'),1);self.assertEqual(c.system_actions,1)
