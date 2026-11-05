"""Recovery-only borrowed mode path using existing bounded v17 collaborators.

No enable, F0/AF input-start, connect ownership or disconnect is authorized.
Caller holds a freshly acquired Feature lease and durably records each stage.
"""
import time
from borrowed_gatt_view import TARGET, ADAPTER
from borrowed_gatt_requester import BorrowedGattRequester
from borrowed_mode_reader import BorrowedModeReader
from borrowed_stop_mode import BorrowedStopModeRead
from connected_status_watch import BoundConnectedView
from borrowed_control_guard import BorrowedControlGuard
from preborrow_guard import PreBorrowGuard
from native_mode_session import NativeModeClient, ack
from partial_activation_stop import PumpingGattPartialStopClient

class RecoveryBorrowedModeWriter:
 def __init__(self, stop, *, guard, identity_verified):
  if not all(callable(f) for f in (stop,guard,identity_verified)):raise ValueError('recovery proofs required')
  self.stop=stop;self.guard=guard;self.identity=identity_verified;self.used=False
 def __call__(self, mode):
  if type(mode) is not int or mode!=0 or self.used or self.guard() is not True or self.identity() is not True:raise RuntimeError('recovery disable unavailable')
  self.used=True
  return ack(self.stop('hid/internal/setReport',{'address':TARGET,'reportType':'feature','reportData':[240,160,0]},timeout=6))

def _recover_zero(*,watch,lease,generation,paired_check,external_feature_guard,record,
                 prior_inactive,gatt_lookup_reply,clock=time.monotonic,pump=lambda:None,
                 requester_factory=BorrowedGattRequester,reader_factory=BorrowedModeReader,
                 activation_factory=NativeModeClient,stop_factory=PumpingGattPartialStopClient):
 pre=PreBorrowGuard(watch,lease,generation=generation,external_feature_guard=external_feature_guard,clock=clock)
 from postconnect_receiver_device import RecoveryPairingCheck
 admit=RecoveryPairingCheck(paired_check,lambda:pre() is True and prior_inactive() is True,clock=clock)
 if admit() is not True:raise RuntimeError('recovery target unavailable')
 if record({'stage':'recovery-gatt-lookup-intent','generation':generation}) is not True:raise RuntimeError('lookup intent unrecorded')
 from recovery_lookup_handoff import validate_reply
 validate_reply(gatt_lookup_reply)
 view=requester_factory(pump=pump,guard=admit).adopt(gatt_lookup_reply,generation=generation,control_valid=admit)
 try:
  if view.generation!=generation or view.discover()!=view.client_id:raise RuntimeError('recovery view differs')
  bound=BoundConnectedView(watch,view.client_id)
  guard=BorrowedControlGuard(generation=generation,client_id=view.client_id,lease=lease,profiles=bound.snapshot,clock=clock)
  def control():return admit() is True and guard() is True
  activation=activation_factory(generation=generation,client_id=view.client_id,pump=pump,guard=control)
  stop=stop_factory(generation=generation,client_id=view.client_id,pump=pump,guard=control,native_app=True)
  reader=reader_factory(activation,exclusive_feature_guard=control,clock=clock)
  reader.bind_borrowed(link={'remote':TARGET,'adapter':ADAPTER,'generation':generation,'connected':True,'connecting':False,'paired':True},client_id=view.client_id,control_valid=control)
  mode=reader.read(generation)['mode']
  if type(mode) is not int or mode not in (0,1) or not control():raise RuntimeError('recovery baseline invalid')
  writer=RecoveryBorrowedModeWriter(stop,guard=control,identity_verified=lambda:reader.reference_verified is True)
  if mode==1:
   if record({'stage':'recovery-disable-intent','generation':generation}) is not True:raise RuntimeError('disable intent unrecorded')
   writer(0)
   mode=BorrowedStopModeRead(stop,guard=control)(reader)
  if type(mode) is not int or mode!=0 or not control() or not admit(fresh=True):raise RuntimeError('recovery zero unconfirmed')
  return {'status':'recovered','generation':generation,'modeZeroVerified':True,'featureExclusivity':'cooperative-only-unproven'}
 finally:view.close()


def recover_zero(*,old_receiver_exited,**kwargs):
 result=_recover_zero(prior_inactive=old_receiver_exited,**kwargs)
 return {**result,'oldReceiverExitVerified':True}


def recover_owned_zero(*,session_closed,**kwargs):
 """The same worker has closed every input/output resource before waiting."""
 result=_recover_zero(prior_inactive=session_closed,**kwargs)
 return {**result,'priorSessionClosedVerified':True}
