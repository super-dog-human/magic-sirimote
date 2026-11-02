"""One post-connection receiver launch using the existing TV launcher.

Offline composition only. The caller must provide durable launch evidence,
matching receiver request/package, cleanup and app-level lifecycle handling.
A launch acknowledgement is not proof that an app started or saw a device.
"""
import re

class PostConnectReceiverLaunch:
 def __init__(self,watch,launcher,run,record,*,prepare_request):
  if not callable(getattr(watch,'snapshot',None)) or not callable(getattr(launcher,'launch',None)) or type(run) is not str or not re.fullmatch('[a-f0-9]{32}',run) or not callable(record) or not callable(prepare_request):raise ValueError('invalid launch context')
  self.watch=watch;self.launcher=launcher;self.run=run;self.record=record;self.prepare_request=prepare_request;self.attempted=False
 def launch_once(self):
  if self.attempted:raise RuntimeError('launch already considered')
  current=self.watch.snapshot()
  if type(current) is not dict or type(current.get('generation')) is not int or current['generation']<=0:return {'status':'not-ready'}
  generation=current['generation']
  # Failure after this point is ambiguous and is not retried with this object.
  self.attempted=True
  if self.record({'stage':'receiver-launch-intent','run':self.run,'generation':generation}) is not True:return {'status':'attention','reason':'intent-unconfirmed'}
  try:
   if self.prepare_request(self.run,generation) is not True:return {'status':'attention','reason':'receiver-request-unconfirmed'}
  except Exception:return {'status':'attention','reason':'receiver-request-unknown'}
  current=self.watch.snapshot()
  if type(current) is not dict or type(current.get('generation')) is not int or current['generation']!=generation:return {'status':'attention','reason':'connection-changed-before-launch'}
  try:result=self.launcher.launch('B',self.run)
  except Exception:return {'status':'attention','reason':'launch-unknown'}
  if result!='accepted':return {'status':'attention','reason':'launch-'+('rejected' if result=='rejected' else 'unknown')}
  # Return the generation for a separate receiver-ready and link check.
  return {'status':'accepted','generation':generation,'receiverReady':False}
