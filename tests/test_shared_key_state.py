import unittest
from fixture_devices import MemoryDevices
from output_bridge import VerifiedOutputs,KEY_ENTER,BTN_LEFT,_frame
from system_key_sink import SystemKeySink,EVIOCGKEY,EVIOCGBIT_KEY,KEYS,EVENT

class Tests(unittest.TestCase):
 def outputs(self,held):
  self.dev=MemoryDevices();self.dev.held[1].update(held)
  return VerifiedOutputs(1,2,ioctl_fn=self.dev.ioctl,write_fn=self.dev.write,sleep_fn=lambda _:None)
 def test_coldboot_power_latch_survives_all_owned_outputs_and_cleanup(self):
  out=self.outputs({116});out.key_pulse('right');out.select_frame(_frame(KEY_ENTER,1));out.select_frame(_frame(KEY_ENTER,0));out.click_frame(_frame(BTN_LEFT,1));out.click_frame(_frame(BTN_LEFT,0))
  self.assertTrue(out.verify_released());self.assertTrue(out.best_effort_release());self.assertEqual(self.dev.held[1],{116})
  self.assertFalse(any(code==116 for fd,events in self.dev.writes for _,_,kind,code,v in events if kind==1))
 def test_owned_keys_held_at_start_still_rejected(self):
  for code in (28,103,108,105,106):
   with self.assertRaises(RuntimeError):self.outputs({116,code})
 def test_direction_conflict_after_start_rejected_without_releasing_foreign_key(self):
  out=self.outputs({116});self.dev.held[1].add(103)
  with self.assertRaises(RuntimeError):out.key_pulse('right')
  self.assertEqual(self.dev.writes,[]);self.assertEqual(self.dev.held[1],{116,103})
 def test_cleanup_releases_owned_enter_but_keeps_power(self):
  out=self.outputs({116});out.select_frame(_frame(KEY_ENTER,1));self.assertTrue(out.best_effort_release());self.assertEqual(self.dev.held[1],{116})
 def system(self):
  self.held={116};self.writes=[]
  def ioctl(fd,request,buf,mutate):
   codes=KEYS.values() if request==EVIOCGBIT_KEY else self.held if request==EVIOCGKEY else None
   assert codes is not None
   for c in codes:buf[c//8]|=1<<(c%8)
  def write(fd,packet):
   for _,_,kind,c,v in EVENT.iter_unpack(packet):
    if kind==1:
     self.writes.append((c,v))
     if v:self.held.add(c)
     else:self.held.discard(c)
   return len(packet)
  return SystemKeySink(1,identity_check=lambda fd:fd==1,ioctl=ioctl,write=write)
 def test_system_keys_work_with_power_latch_without_changing_it(self):
  sink=self.system()
  for action in KEYS:sink.pulse(action)
  self.assertEqual(self.held,{116});self.assertTrue(sink.verify_released());self.assertFalse(any(c==116 for c,v in self.writes))
 def test_external_system_key_skips_without_poisoning_sink(self):
  sink=self.system();self.held.add(KEYS['home'])
  self.assertIs(sink.pulse('back'),False);self.assertFalse(sink.failed)
  self.assertEqual(self.writes,[]);self.assertEqual(self.held,{116,KEYS['home']})
  self.held.remove(KEYS['home']);sink.pulse('back')
  self.assertEqual(self.writes,[(KEYS['back'],1),(KEYS['back'],0)])
  self.assertEqual(self.held,{116})

 def test_duplicate_ir_home_does_not_write_or_release_ir_key(self):
  sink=self.system();self.held.add(KEYS['home'])
  self.assertIs(sink.pulse('home'),False);self.assertFalse(sink.failed)
  self.assertEqual(self.writes,[]);self.assertIn(KEYS['home'],self.held)
  self.held.remove(KEYS['home']);sink.pulse('settings');self.assertTrue(sink.verify_released())
 def test_uncertain_press_remains_terminal_and_attempts_one_release(self):
  sink=self.system();writes=[]
  def short(fd,packet):writes.append(packet);return len(packet)-1 if len(writes)==1 else len(packet)
  sink.write=short
  with self.assertRaises(OSError):sink.pulse('home')
  self.assertTrue(sink.failed);self.assertEqual(len(writes),2)
  with self.assertRaises(RuntimeError):sink.pulse('home')
  self.assertEqual(len(writes),2)
 def test_skipped_media_toggle_accepts_fresh_unchanged_play_state(self):
  from media_toggle import PlaybackSnapshot,MediaAwareSink
  snapshot=PlaybackSnapshot(clock=lambda:1.)
  playing={'returnValue':True,'foregroundAppInfo':[{'playState':'playing'}]}
  snapshot.update(playing);sink=self.system();media=MediaAwareSink(sink,snapshot)
  self.held.add(KEYS['home']);self.assertIs(media.pulse('playpause'),False)
  self.assertEqual(self.writes,[]);self.assertIsNone(snapshot.choose())
  self.held.remove(KEYS['home']);snapshot.update(playing)
  self.assertIs(media.pulse('playpause'),True);self.assertEqual(self.writes,[(KEYS['pause'],1),(KEYS['pause'],0)])
 def test_cancelled_media_does_not_accept_stale_inflight_poll(self):
  from media_toggle import PlaybackSnapshot
  snapshot=PlaybackSnapshot(clock=lambda:1.)
  playing={'returnValue':True,'foregroundAppInfo':[{'playState':'playing'}]}
  snapshot.update(playing);self.assertEqual(snapshot.consume(),'pause');ticket=snapshot.ticket()
  self.assertTrue(snapshot.cancel_consumed(ticket));self.assertFalse(snapshot.update(playing,ticket=ticket))
  snapshot.update(playing);self.assertEqual(snapshot.choose(),'pause')

 def test_ir_collision_does_not_stop_combined_receiver(self):
  from combined_controls import CombinedControls
  from media_toggle import PlaybackSnapshot,MediaAwareSink
  class Rolling:
   generation=1
   closed=False
   def start(self):pass
   def feed_raw(self,*args):return True
   def tick(self):return True
   def stop(self,reason):self.closed=True
   def _live(self):return True
  sink=self.system();rolling=Rolling();controls=CombinedControls(rolling,MediaAwareSink(sink,PlaybackSnapshot()).pulse)
  controls.start()
  def feed(mask):controls.feed_raw(1,bytes((0xfc,0,mask)))
  feed(0);feed(1);self.held.add(KEYS['home']);feed(0)
  self.assertFalse(controls.closed);self.assertFalse(sink.failed);self.assertEqual(self.writes,[])
  self.held.remove(KEYS['home']);feed(32);feed(0)
  self.assertEqual(self.writes,[(KEYS['back'],1),(KEYS['back'],0)]);self.assertFalse(controls.closed)

if __name__=='__main__':unittest.main()
