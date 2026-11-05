import errno,os,stat,struct,unittest
from types import SimpleNamespace
from absolute_pointer import AbsoluteOutputs,prefer_absolute,visible_frame,NAME,SHOW,HIDE
from output_bridge import VerifiedOutputs,EVENT,BTN_LEFT,KEY_CODES,_frame
from output_devices import OutputCloseError

class Kernel:
 def __init__(self):
  self.names={1:'LGE RCU',2:'ClickableMouse',3:NAME}
  self.positions=[960,540];self.held={1:set(),2:set(),3:set()};self.writes=[];self.closed=[]
 def ioctl(self,fd,request,buffer,mutate=True):
  number=request&255;size=len(buffer)
  if number==6:value=self.names[fd].encode()+b'\0'
  elif number in (0x40,0x41):
   axis=number-0x40;value=struct.pack('=6i',self.positions[axis],0,(1920,1080)[axis],0,0,0)
  else:
   if number==0x20:codes=(0,1) if fd==1 else (0,1,2) if fd==2 else (0,1,3)
   elif number==0x21:codes=KEY_CODES if fd==1 else (BTN_LEFT,) if fd==2 else (BTN_LEFT,SHOW,HIDE)
   elif number==0x22:codes=(0,1) if fd==2 else ()
   elif number==0x23:codes=(0,1) if fd==3 else ()
   elif number==0x18:codes=self.held[fd]
   else:raise AssertionError(number)
   bits=sum(1<<code for code in codes if code<size*8);value=bits.to_bytes(size,'little')
  buffer[:]=value.ljust(size,b'\0')[:size]
 def write(self,fd,data):
  self.writes.append((fd,data))
  for _,_,kind,code,value in EVENT.iter_unpack(data):
   if kind==3:self.positions[code]=value
   elif kind==1:
    if value:self.held[fd].add(code)
    else:self.held[fd].discard(code)
  return len(data)
 def original(self,mouse=2):return VerifiedOutputs(1,mouse,ioctl_fn=self.ioctl,write_fn=self.write,sleep_fn=lambda _:None,allow_missing_mouse=mouse is None)
 def replacement(self):return AbsoluteOutputs(1,3,ioctl_fn=self.ioctl,write_fn=self.write,sleep_fn=lambda _:None)
 def info(self):return SimpleNamespace(st_dev=1,st_ino=42,st_rdev=os.makedev(13,67),st_mode=stat.S_IFCHR|0o660,st_uid=100,st_gid=100)
 def upgrade(self,original,guard=lambda:True,**kwargs):
  return prefer_absolute(original,[{'name':'LGE RCU'}],guard,read_inventory=kwargs.pop('read_inventory',lambda:{3:(NAME,1,42)}),lstat=lambda _:self.info(),open_fd=lambda *_:3,fstat=lambda _:self.info(),close=kwargs.pop('close',self.closed.append),ioctl=self.ioctl,**kwargs)

class AbsolutePointerTests(unittest.TestCase):
 def test_selection_never_sends_input_and_transfers_ownership(self):
  k=Kernel();old=k.original();new,records=k.upgrade(old)
  self.assertTrue(old.closed);self.assertIsNone(old.key_fd);self.assertIsNone(old.mouse_fd)
  self.assertEqual((new.key_fd,new.mouse_fd),(1,3));self.assertEqual(k.closed,[2]);self.assertEqual(k.writes,[])
  self.assertEqual(records[1]['name'],NAME);self.assertTrue(new.pointer_ready)
  new.close(close_fn=k.closed.append);self.assertEqual(sorted(k.closed),[1,2,3])
 def test_ready_without_clickable_mouse(self):
  k=Kernel();new,_=k.upgrade(k.original(None));self.assertTrue(new.pointer_ready);self.assertEqual(k.closed,[])
 def test_absence_retains_original(self):
  k=Kernel();old=k.original(None);new,_=k.upgrade(old,read_inventory=lambda:{0:('LGE RCU',1,2)})
  self.assertIs(old,new);self.assertFalse(new.pointer_ready);self.assertEqual(k.writes,[])
 def test_incompatible_device_retains_original_and_closes_candidate(self):
  k=Kernel();old=k.original();k.names[3]='Unrelated mouse';new,_=k.upgrade(old)
  self.assertIs(old,new);self.assertEqual(k.closed,[3]);self.assertEqual(k.writes,[])
 def test_ambiguous_inventory_rejected(self):
  k=Kernel();old=k.original()
  with self.assertRaisesRegex(RuntimeError,'not unique'):k.upgrade(old,read_inventory=lambda:{3:(NAME,1,2),4:(NAME,1,3)})
  self.assertEqual(k.closed,[]);self.assertFalse(old.closed)
 def test_lost_guard_releases_candidate_without_moving(self):
  k=Kernel();old=k.original();checks=iter((True,False))
  with self.assertRaisesRegex(RuntimeError,'guard lost'):k.upgrade(old,guard=lambda:next(checks))
  self.assertEqual(k.closed,[3]);self.assertEqual(old.key_fd,1);self.assertEqual(k.writes,[])
 def test_close_failure_never_falls_back_as_success(self):
  k=Kernel();old=k.original()
  def close(fd):
   k.closed.append(fd)
   if fd==2:raise OSError(errno.EIO,'close')
  with self.assertRaises(OutputCloseError):k.upgrade(old,close=close)
  self.assertEqual(k.closed,[2,3]);self.assertEqual(old.key_fd,1)
 def test_motion_uses_current_position_and_one_complete_frame(self):
  k=Kernel();out=k.replacement();k.positions=[1100,600];out.move_relative(20,-10)
  self.assertEqual(k.positions,[1150,575]);self.assertEqual(len(k.writes),1)
  records=[e[2:] for e in EVENT.iter_unpack(k.writes[0][1])]
  self.assertEqual(records[:2],[(1,SHOW,1),(1,SHOW,0)])
  self.assertEqual(records[-3:],[(3,0,1150),(3,1,575),(0,0,0)])
  self.assertEqual([e for e in records if e[0]==0],[(0,0,0)])
 def test_unchanged_axes_are_delivered_after_visibility_reset(self):
  for x,y in ((0,0),(1920,1080),(768,648),(960,540)):
   kernel={0:x,1:y};delivered=[]
   for _,_,kind,code,value in EVENT.iter_unpack(visible_frame(x,y,((0,1920),(0,1080)))):
    if kind==3 and kernel[code]!=value:delivered.append((code,value));kernel[code]=value
   self.assertEqual(delivered[-2:],[(0,x),(1,y)])
 def test_no_motion_at_rest_and_coordinates_stay_bounded(self):
  k=Kernel();out=k.replacement();out.move_relative(0,0);self.assertEqual(k.writes,[])
  out.move_relative(2147483647,-2147483648);self.assertEqual(k.positions,[1920,0])
 def test_fractional_motion_preserves_small_steps_in_both_directions(self):
  for sign in (-1,1):
   k=Kernel();out=k.replacement()
   for _ in range(20):out.move_relative(sign,sign)
   self.assertEqual(k.positions,[960+50*sign,540+50*sign])
   for _ in range(20):out.move_relative(-sign,-sign)
   self.assertEqual(k.positions,[960,540])
 def test_other_remote_movement_discards_fractional_remainder(self):
  k=Kernel();out=k.replacement();out.move_relative(1,1)
  k.positions=[800,400];out.move_relative(1,1)
  self.assertEqual(k.positions,[802,402])
 def test_idle_and_click_do_not_flush_fractional_motion(self):
  k=Kernel();out=k.replacement();out.move_relative(1,1)
  count=len(k.writes);out.move_relative(0,0)
  self.assertEqual(len(k.writes),count)
  out.click_frame(_frame(BTN_LEFT,1));out.click_frame(_frame(BTN_LEFT,0))
  self.assertEqual(k.positions,[962,542]);out.move_relative(1,1)
  self.assertEqual(k.positions,[965,545])
 def test_click_and_navigation_use_separate_devices_and_release(self):
  k=Kernel();out=k.replacement();out.click_frame(_frame(BTN_LEFT,1));out.click_frame(_frame(BTN_LEFT,0));out.key_pulse('left')
  self.assertEqual([fd for fd,_ in k.writes],[3,3,1,1]);self.assertTrue(out.verify_released())
 def test_short_motion_write_fails_without_retry(self):
  k=Kernel();out=k.replacement();calls=[]
  def short(fd,data):calls.append(fd);return 16
  out.write_fn=short
  with self.assertRaises(OSError):out.move_relative(1,1)
  self.assertTrue(out.failed);self.assertEqual(calls,[3])
 def test_held_builtin_click_does_not_replace_current_backend(self):
  k=Kernel();old=k.original();k.held[3].add(BTN_LEFT)
  with self.assertRaisesRegex(RuntimeError,'already held'):k.upgrade(old)
  self.assertEqual(k.closed,[3]);self.assertEqual((old.key_fd,old.mouse_fd),(1,2));self.assertFalse(old.closed)
  self.assertEqual(k.writes,[])
 def test_changed_inventory_never_transfers_descriptors(self):
  k=Kernel();old=k.original();scans=iter(({3:(NAME,1,42)},{3:(NAME,1,43)}))
  with self.assertRaisesRegex(RuntimeError,'changed while opening'):k.upgrade(old,read_inventory=lambda:next(scans))
  self.assertEqual(k.closed,[3]);self.assertEqual((old.key_fd,old.mouse_fd),(1,2));self.assertEqual(k.writes,[])
 def test_display_capability_missing_falls_back_without_input(self):
  k=Kernel();old=k.original();original=k.ioctl
  def ioctl(fd,request,buffer,mutate=True):
   original(fd,request,buffer,mutate)
   if fd==3 and request&255==0x21:
    bitmap=int.from_bytes(buffer,'little')&~(1<<SHOW)
    buffer[:]=bitmap.to_bytes(len(buffer),'little')
  k.ioctl=ioctl
  output,_=k.upgrade(old)
  self.assertIs(output,old);self.assertEqual(k.closed,[3]);self.assertEqual(k.writes,[])
 def test_changed_axis_limits_fail_before_sending_motion(self):
  k=Kernel();out=k.replacement();original=out.ioctl_fn
  def ioctl(fd,request,buffer,mutate=True):
   original(fd,request,buffer,mutate)
   if fd==3 and request&255==0x40:buffer[:]=struct.pack('=6i',960,0,3840,0,0,0)
  out.ioctl_fn=ioctl
  with self.assertRaisesRegex(RuntimeError,'ranges changed'):out.move_relative(10,10)
  self.assertTrue(out.failed);self.assertEqual(k.writes,[])
 def test_cleanup_releases_held_pointer_button(self):
  k=Kernel();out=k.replacement();out.click_frame(_frame(BTN_LEFT,1))
  self.assertTrue(out.best_effort_release());self.assertNotIn(BTN_LEFT,k.held[3])

if __name__=='__main__':unittest.main()
