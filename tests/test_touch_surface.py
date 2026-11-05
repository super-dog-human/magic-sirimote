import unittest
import touch_surface
from adaptive_prefix_router import AdaptivePrefixRouter
from input_router import InputRouter
from swipe_click import SwipeClick
from test_swipe_click import FakeClock,touch

class TouchSurfaceTests(unittest.TestCase):
 def setUp(self):
  self.old=touch_surface._product;touch_surface._product=None
 def tearDown(self):touch_surface._product=self.old
 def recognizer(self,product):
  touch_surface.bind_product(product);clock=FakeClock();events=[]
  r=SwipeClick(lambda a,d:events.append((a,d)),touch_surface.regions(),clock=clock)
  r.bind(1);r.feed(1,b'\0\0');return r,clock,events
 def swipe(self,r,c,start,end):
  for x,y,state in ((*start,3),(*end,4),(*end,7)):
   c.step();r.feed(1,touch(x,y,state=state))
  c.step(.07);r.tick()
 def test_a1962_published_edge_coordinates_are_not_discarded(self):
  r,c,e=self.recognizer(0x026d)
  for start,end,direction in (((-1700,584),(-1000,584),'right'),((-300,-1058),(-1000,-1058),'left'),((-1813,-850),(-1813,100),'up'),((-182,400),(-182,-400),'down')):
   self.swipe(r,c,start,end)
   self.assertEqual(e[-2:],[(direction,True),(direction,False)])
  self.assertEqual(r.stats['cancelReasons']['bounds'],0)
 def test_a1513_original_geometry_and_swipe_remain(self):
  r,c,e=self.recognizer(0x0266)
  self.assertEqual((r.regions.x_min,r.regions.x_max,r.regions.y_min,r.regions.y_max),(-1768,-200,-1032,440))
  self.swipe(r,c,(-1500,-300),(-900,-300));self.assertEqual(e,[('right',True),('right',False)])
  self.swipe(r,c,(-1500,584),(-900,584));self.assertEqual(len(e),2)
 def test_corrupt_coordinate_does_not_become_swipe(self):
  r,c,e=self.recognizer(0x026d);self.swipe(r,c,(-1000,0),(1800,0));self.assertFalse(e)
 def test_product_cannot_change_in_existing_process(self):
  touch_surface.bind_product(0x026d);touch_surface.bind_product(0x026d)
  with self.assertRaises(RuntimeError):touch_surface.bind_product(0x0266)
  for value in (None,True,0x1234,'621'):
   with self.assertRaises(ValueError):touch_surface.bind_product(value)
 def test_both_routers_use_selected_geometry(self):
  touch_surface.bind_product(0x026d);c=FakeClock()
  for router in (AdaptivePrefixRouter(lambda *_:True,clock=c),InputRouter(lambda *_:True,clock=c,touch_mode='swipe-click')):
   self.assertEqual(router.press.regions.y_max,650)
 def target(self,ident):
  import stat
  from types import SimpleNamespace
  from unittest.mock import Mock
  node=SimpleNamespace(st_mode=stat.S_IFCHR|0o600,st_ino=10,st_dev=1,st_rdev=12)
  return dict(inventory=lambda **_: {'inventoryComplete':True,'allOpenedFdsClosed':True,'targetCandidateIndexes':[2]},
   lstat=lambda _:node,open_fn=lambda *_:7,fstat=lambda _:node,identity_fn=lambda _:ident,close_fn=Mock())
 def test_open_verified_target_selects_profile_before_router_creation(self):
  import postconnect_receiver_device as device
  _open_target_once=getattr(device,"_open_target_once",device.open_target)
  args=self.target({'matches':True,'product':0x026d})
  self.assertEqual(_open_target_once(**args),7);self.assertEqual(touch_surface.regions().y_min,-1100)
  args['close_fn'].assert_not_called()
 def test_wrong_or_missing_identity_cannot_select_surface(self):
  import postconnect_receiver_device as device
  _open_target_once=getattr(device,"_open_target_once",device.open_target)
  for ident in ({'matches':False,'product':0x026d},{'matches':True},{'matches':True,'product':123}):
   args=self.target(ident)
   with self.assertRaises((ValueError,RuntimeError)):_open_target_once(**args)
   self.assertIsNone(touch_surface._product);args['close_fn'].assert_called_once_with(7)
