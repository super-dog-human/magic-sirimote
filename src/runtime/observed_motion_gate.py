"""Finite experimental motion gate: complete frames and a live mode proof.

No device I/O here. The caller supplies the already-verified receiver, cue and
continuity guard. A shape-valid frame does not prove physical units or quality.
"""
import re
from combined_receiver import CombinedReceiver
from hidraw_frame_demux import demux_report,MOTION_REPORT_LENGTHS
import portable_validators as validators

def verify_start(*,run,ready,cue,profiles,now_ms,continuity):
 if type(run) is not str or not re.fullmatch('[0-9a-f]{32}',run) or type(now_ms) is not int or not callable(continuity):raise ValueError('invalid run context')
 if not validators.valid_a_ready(ready,run) or type(ready.get('epochMs')) is not int or not 0<=now_ms-ready['epochMs']<=30000:raise ValueError('ready invalid or stale')
 sensor=ready.get('sensorStart')
 if not isinstance(sensor,dict) or sensor.get('status')!='active' or type(sensor.get('generation')) is not int or sensor['generation']!=1 or type(sensor.get('sensorModeVerified')) is not int or sensor['sensorModeVerified']!=1:raise ValueError('sensor mode unverified')
 if not isinstance(cue,dict) or cue.get('appId')!=validators.APP_A_ID or cue.get('run')!=run or cue.get('stage')!='VERIFIED_RECEIVE_GATE' or type(cue.get('epochNs')) is not int or not 0<=now_ms-cue['epochNs']//1_000_000<=30000:raise ValueError('cue invalid or stale')
 try:valid=continuity() is True
 except Exception:valid=False
 if not validators.profiles_confirm_connected(profiles) or not valid:raise ValueError('live control unavailable')

class ObservedMotionGate:
 def __init__(self,receiver,*,run,ready,cue,profiles,now_ms,continuity):
  if type(receiver) is not CombinedReceiver or receiver.closed or receiver.generation!=1 or receiver.bridge.sensor_input_verified is not False:raise ValueError('fresh bound receiver required')
  verify_start(run=run,ready=ready,cue=cue,profiles=profiles,now_ms=now_ms,continuity=continuity)
  self.receiver=receiver;self.continuity=continuity;self.opened=False;self.closed=False;self.complete_frames=0
 def _live(self):
  try:return self.continuity() is True
  except Exception:return False
 def feed_raw(self,generation,report):
  if self.closed:return False
  if generation!=1 or type(generation) is not int:return False
  if not self._live():
   self.closed=True;self.receiver.bridge.sensor_input_verified=False;self.receiver.stop('motion-link-lost');return False
  if type(report) is bytes and len(report) in MOTION_REPORT_LENGTHS and demux_report(report) is not None:
   self.complete_frames+=1
   if not self.opened:self.receiver.bridge.sensor_input_verified=True;self.opened=True
  return self.receiver.feed_raw(generation,report)
 def tick(self):
  if self.closed:return
  if not self._live():self.closed=True;self.receiver.bridge.sensor_input_verified=False;self.receiver.stop('motion-link-lost');return
  self.receiver.tick()
 def stop(self,reason='requested'):
  if self.closed:return
  self.closed=True;self.receiver.bridge.sensor_input_verified=False;self.receiver.stop(reason)
 def summary(self):
  out=self.receiver.summary()
  out['motionEvidence']={'motionGateOpened':self.opened,'completeFrames':self.complete_frames,'closed':self.closed,'rawReportsStored':False}
  return out
