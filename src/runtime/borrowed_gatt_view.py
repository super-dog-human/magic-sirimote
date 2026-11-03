"""Read-only view over a possibly pre-existing GATT client.

The caller supplies the already-observed reply and live profile guard. This
object never connects, disconnects, enables sensors, or claims exclusivity.
"""
from runtime_device import identity as device_identity
TARGET=device_identity().remote
ADAPTER=device_identity().adapter

def valid_client(value):
 return type(value) is str and value.isascii() and value.isdecimal() and 1<=len(value)<=5 and 1<=int(value)<=65535

class BorrowedGattView:
 def __init__(self,reply,*,generation,control_valid,discover):
  if (type(reply) is not dict or reply.get('returnValue') is not True or
      str(reply.get('address','')).lower()!=TARGET or str(reply.get('adapterAddress','')).lower()!=ADAPTER or
      not valid_client(reply.get('clientId')) or type(generation) is not int or generation<=0 or
      not callable(control_valid) or not callable(discover)):raise ValueError('invalid borrowed view')
  self.client_id=reply['clientId'];self.generation=generation;self.control_valid=control_valid;self._discover=discover;self.state='new'
 def discover(self):
  if self.state!='new' or self.control_valid() is not True:raise RuntimeError('borrowed control unavailable')
  self.state='discover-unknown'
  answer=self._discover({'address':TARGET})
  if type(answer) is not dict or answer.get('returnValue') is not True or self.control_valid() is not True:raise RuntimeError('discovery unconfirmed')
  self.state='discovered';return self.client_id
 def close(self):
  if self.state not in ('new','discovered','discover-unknown'):raise RuntimeError('view already closed')
  # There is no GATT disconnect here: the underlying client may be shared.
  self.state='closed'
  return {'closed':True,'gattDisconnectCalls':0,'clientOwnership':'unproven'}
