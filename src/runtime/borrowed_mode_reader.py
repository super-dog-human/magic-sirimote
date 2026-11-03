"""Adaptation of the audited mode reader for an unowned client.

A caller-supplied feature guard is checked on every operation. The inherited
reader assumes serialized feature commands; the guard itself cannot
establish system-wide exclusivity unless separately verified. A cooperative-
only caller therefore accepts that competing TV software could invalidate
the mode read. This class does not connect or disconnect or grant sensor-
write authority.
"""
from verified_mode_reader import VerifiedModeReader,EVIDENCE_SHA256
from direct_gatt_read import TARGET,ADAPTER
from borrowed_gatt_view import valid_client

class BorrowedModeReader(VerifiedModeReader):
 def __init__(self,call,*,exclusive_feature_guard,clock):
  if not callable(exclusive_feature_guard):raise ValueError('independent feature guard required')
  self.exclusive_feature_guard=exclusive_feature_guard
  super().__init__(call,audited_evidence_sha256=EVIDENCE_SHA256,exclusive_feature_access=True,clock=clock)
 def bind_borrowed(self,*,link,client_id,control_valid):
  if self.used_bind or self.closed:self.closed=True;raise RuntimeError('reader already bound')
  self.used_bind=True
  if (not callable(control_valid) or type(link) is not dict or set(link)!={'remote','adapter','generation','connected','connecting','paired'} or
      link.get('remote')!=TARGET or link.get('adapter')!=ADAPTER or type(link.get('generation')) is not int or link['generation']<=0 or
      link.get('connected') is not True or link.get('connecting') is not False or link.get('paired') is not True or not valid_client(client_id) or
      control_valid() is not True or self.exclusive_feature_guard() is not True):
   self.closed=True;raise ValueError('borrowed control not established')
  self.link=dict(link);self.client_id=client_id;self.control_valid=control_valid
 def bind(self,**_):raise RuntimeError('use explicit borrowed binding')
 def _check(self):
  if self.exclusive_feature_guard() is not True:raise RuntimeError('exclusive feature guard lost')
  return super()._check()
