"""Composition of the borrowed sensor lifecycle.

The caller must supply a live watcher, paired-target proof, an explicit
feature-serialization guard and audited API adapters. A cooperative-only
guard is an unproven assumption about other processes. This module never
starts on import.
"""
from borrowed_control_guard import BorrowedControlGuard
from borrowed_gatt_view import TARGET,ADAPTER
from borrowed_mode_reader import BorrowedModeReader
from borrowed_mode_session import BorrowedModeSession
from connected_status_watch import BoundConnectedView

def create_session(*,watch,view,lease,paired,call,write_mode,read_stop_mode,external_feature_guard,record,clock,reader_clock):
 if paired is not True or not callable(external_feature_guard) or not callable(read_stop_mode) or not callable(record):raise ValueError('paired target, separate stop read, journal and external feature guard required')
 bound=BoundConnectedView(watch,view.client_id)
 if view.generation!=bound.generation:raise RuntimeError('connection generation differs')
 guard=BorrowedControlGuard(generation=bound.generation,client_id=view.client_id,lease=lease,profiles=bound.snapshot,clock=clock)
 last_failure={}
 def feature_guard():
  if guard() is not True:
   last_failure['failure']=guard.last_failure;return False
  if external_feature_guard() is not True:
   last_failure['failure']='external';return False
  last_failure.clear();return True
 def control_diagnostic():
  info=dict(last_failure)
  diagnostic=getattr(watch,'diagnostic',None)
  if callable(diagnostic):info.update(diagnostic(bound.generation))
  return info
 if feature_guard() is not True:raise RuntimeError('feature access unavailable')
 if view.discover()!=view.client_id:raise RuntimeError('discovery identity mismatch')
 reader=BorrowedModeReader(call,exclusive_feature_guard=feature_guard,clock=reader_clock)
 reader.bind_borrowed(link={'remote':TARGET,'adapter':ADAPTER,'generation':bound.generation,'connected':True,'connecting':False,'paired':True},client_id=view.client_id,control_valid=feature_guard)
 def read_stop():
  # Preparation can be cancelled before start() performs its first read.
  # Establish the reference then use the independent stop read. Never retry
  # a selector/reference operation that was already attempted or failed.
  if (reader.reference_verified is not True and not reader.closed
      and reader.selector_attempts==0 and feature_guard() is True):
   reader.read(bound.generation)
  if reader.reference_verified is not True or feature_guard() is not True:raise RuntimeError('stop reference unavailable')
  return read_stop_mode(reader)
 session=BorrowedModeSession(view,read_mode=lambda:reader.read(bound.generation)['mode'],read_stop_mode=read_stop,write_mode=write_mode,control_valid=feature_guard,record=record)
 session.control_diagnostic=control_diagnostic
 return session,guard
