"""Single distinct post-stop mode read using a verified feature reference.

The supplied stop client is separate from the activation client's two-read
budget. No selector, connect, disconnect or sensor write occurs here.
"""
from direct_gatt_read import DirectGattReadProbe,READ_CHARACTERISTICS,HID_SERVICE,REPORT_CHAR,_mode_candidate
from borrowed_gatt_view import valid_client

class BorrowedStopModeRead:
 def __init__(self,stop_client,*,guard):
  if not callable(stop_client) or not callable(guard):raise ValueError('invalid stop reader')
  self.call=stop_client;self.guard=guard;self.used=False
 def __call__(self,reader):
  if self.used:raise RuntimeError('stop read already used')
  self.used=True
  attempts=getattr(reader,'selector_attempts',None)
  if self.guard() is not True or getattr(reader,'reference_verified',None) is not True or type(attempts) is not int or attempts!=1 or not valid_client(getattr(reader,'client_id',None)):raise RuntimeError('stop reference unavailable')
  client=reader.client_id
  reply=self.call(READ_CHARACTERISTICS,{'clientId':client,'service':HID_SERVICE,'characteristics':[REPORT_CHAR]},timeout=5)
  if self.guard() is not True or not DirectGattReadProbe._reply_ok(reply) or not DirectGattReadProbe._identity(reply,client):raise RuntimeError('stop read unconfirmed')
  data=DirectGattReadProbe._extract_candidate(reply);candidate=None if data is None else _mode_candidate(data)
  if candidate!={'framing':'A0-mode','mode':0,'status':'candidate_only'}:raise RuntimeError('stop mode not zero')
  return 0
