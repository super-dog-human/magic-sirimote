"""Wiring of the borrowed-client sensor preparation path.

Callers must durably record the lookup attempt and implement recovery before
using on device. An existing GATT client may be returned; none is
disconnected here. A project lock does not exclude unrelated TV software.
"""
import hashlib,time
from borrowed_gatt_requester import BorrowedGattRequester
from borrowed_input_start import BorrowedInputStart
from borrowed_control_guard import BorrowedControlGuard
from connected_status_watch import BoundConnectedView
from preborrow_guard import PreBorrowGuard
from borrowed_mode_writer import BorrowedModeWriter
from borrowed_stop_mode import BorrowedStopModeRead
from input_notifications import ensure_notifications
from borrowed_session_coordinator import create_session
from native_mode_session import NativeModeClient
from partial_activation_stop import PumpingGattPartialStopClient

class InputStartProof:
 def __init__(self,*,watch,lease,external_feature_guard,record,generation):
  self.watch=watch;self.lease=lease;self.external=external_feature_guard;self.record=record;self.generation=generation;self.used=False

def initialize_input(*,watch,lease,paired,external_feature_guard,record,pump=lambda:None,clock=time.monotonic,gatt_lookup_reply=None):
 if paired is not True or not callable(record) or not callable(external_feature_guard) or not callable(pump):raise ValueError('invalid runtime dependencies')
 snapshot=watch.snapshot()
 if type(snapshot) is not dict or type(snapshot.get('generation')) is not int:raise RuntimeError('no observed connected generation')
 generation=snapshot['generation'];pre=PreBorrowGuard(watch,lease,generation=generation,external_feature_guard=external_feature_guard,clock=clock)
 if pre() is not True:raise RuntimeError('pre-borrow guard unavailable')
 if gatt_lookup_reply is not None:
  from recovery_lookup_handoff import validate_reply
  validate_reply(gatt_lookup_reply)
 if record({'stage':'f0af-intent','generation':generation}) is not True:raise RuntimeError('input start intent not recorded')
 input_start=BorrowedInputStart(pump=pump,guard=pre)
 try:
  if input_start.start() is not True or pre() is not True:raise RuntimeError('input start unconfirmed')
 except BaseException:
  record({'stage':'f0af-unknown','generation':generation});raise
 if record({'stage':'f0af-ack','generation':generation}) is not True:raise RuntimeError('input start acknowledgement not recorded')
 proof=InputStartProof(watch=watch,lease=lease,external_feature_guard=external_feature_guard,record=record,generation=generation)
 proof.gatt_lookup_reply=gatt_lookup_reply
 return proof

def accept_prelaunch_input(*,watch,lease,paired,external_feature_guard,record,handoff_check,clock=time.monotonic,gatt_lookup_reply=None):
 if paired is not True or not callable(handoff_check):raise ValueError('invalid input handoff')
 snapshot=watch.snapshot()
 if type(snapshot) is not dict or type(snapshot.get('generation')) is not int:raise RuntimeError('receiver connection unavailable')
 generation=snapshot['generation']
 # This number belongs only to the receiver watcher. The controller independently
 # validates its original watcher via a fresh authenticated challenge.
 pre=PreBorrowGuard(watch,lease,generation=generation,external_feature_guard=external_feature_guard,clock=clock)
 if record({'stage':'prelaunch-input-intent','generation':generation}) is not True:raise RuntimeError('input handoff intent not recorded')
 if pre() is not True or handoff_check() is not True or pre() is not True:raise RuntimeError('input handoff unconfirmed')
 if record({'stage':'prelaunch-input-ack','generation':generation}) is not True:raise RuntimeError('input handoff not recorded')
 proof=InputStartProof(watch=watch,lease=lease,external_feature_guard=external_feature_guard,record=record,generation=generation)
 proof.handoff_check=handoff_check
 proof.gatt_lookup_reply=gatt_lookup_reply
 return proof

def prepare(*,watch,lease,paired,external_feature_guard,record,pump=lambda:None,clock=time.monotonic,input_start=None):
 if input_start is None:input_start=initialize_input(watch=watch,lease=lease,paired=paired,external_feature_guard=external_feature_guard,record=record,pump=pump,clock=clock)
 if (type(input_start) is not InputStartProof or input_start.used or input_start.watch is not watch or input_start.lease is not lease or input_start.external is not external_feature_guard or input_start.record is not record or paired is not True):raise RuntimeError('input start proof invalid')
 input_start.used=True;generation=input_start.generation
 if hasattr(input_start,'handoff_check') and input_start.handoff_check() is not True:raise RuntimeError('controller connection changed before prepare')
 pre=PreBorrowGuard(watch,lease,generation=generation,external_feature_guard=external_feature_guard,clock=clock)
 if pre() is not True:raise RuntimeError('connection changed after input start')
 if record({'stage':'gatt-lookup-intent','generation':generation}) is not True:raise RuntimeError('intent not recorded')
 requester=BorrowedGattRequester(pump=pump,guard=pre)
 try:
  reply=getattr(input_start,'gatt_lookup_reply',None)
  if reply is None:view=requester.borrow(generation=generation,control_valid=pre)
  else:view=requester.adopt(reply,generation=generation,control_valid=pre)
 except BaseException as exc:
  record({'stage':'gatt-lookup-unknown','generation':generation})
  # Preserve the unknown lookup outcome; the category describes only the
  # guard's last decision and says nothing about whether dispatch occurred.
  if isinstance(exc,RuntimeError) and str(exc)=='Call guard rejected dispatch' and pre.last_failure in ('lease','feature','snapshot','age','hid','gatt','exception'):
   raise RuntimeError('preborrow-'+pre.last_failure) from exc
  raise
 try:
  evidence={'stage':'borrowed-view-obtained','generation':generation,'clientIdSha256':hashlib.sha256(view.client_id.encode('ascii')).hexdigest(),'ownership':'unproven'}
  if record(evidence) is not True:raise RuntimeError('lookup result not recorded')
  bound=BoundConnectedView(watch,view.client_id)
  guard=BorrowedControlGuard(generation=generation,client_id=view.client_id,lease=lease,profiles=bound.snapshot,clock=clock)
  def control():return guard() is True and external_feature_guard() is True
  activation=NativeModeClient(generation=generation,client_id=view.client_id,pump=pump,guard=control)
  stop=PumpingGattPartialStopClient(generation=generation,client_id=view.client_id,pump=pump,guard=control,native_app=True)
  writer=BorrowedModeWriter(activation,stop,guard=control);post=BorrowedStopModeRead(stop,guard=control)
  session,_=create_session(watch=watch,view=view,lease=lease,paired=True,call=activation,write_mode=writer,read_stop_mode=post,external_feature_guard=external_feature_guard,record=record,clock=clock,reader_clock=clock)
  ensure_notifications(view.client_id,pump=pump,guard=control,record=record)
  import runtime_bundle as bundle
  if bundle.active():
   from battery_read import ScreenRefresh
   session.battery_refresh=ScreenRefresh(view.client_id, control)
  return session
 except BaseException:
  view.close();raise
