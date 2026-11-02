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
 def test_system_owned_key_conflict_still_blocks(self):
  sink=self.system();self.held.add(KEYS['home'])
  with self.assertRaises(RuntimeError):sink.pulse('back')
  self.assertEqual(self.writes,[]);self.assertEqual(self.held,{116,KEYS['home']})

if __name__=='__main__':unittest.main()
