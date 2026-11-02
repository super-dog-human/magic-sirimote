"""Authenticate the live controller and its receiver request before use.

Requires a separately obtained, run-bound controller process record and pinned
package. A permission-limited executable fallback is disclosed, not security
proof against a malicious local process. No device or input changes here.
"""
import local_attestation as att
import receiver_package_attestation as pkg
from receiver_request import read_request
CONTROLLER='org.codex.siriremote.autocoord20261029v'

def authenticate(*,controller_record,run,controller_app,controller_package,pin,receiver_state,proc_path='/proc',python_path='/usr/bin/python3',read=read_request,allow_exe_permission_denied=False):
 if type(controller_record) is not dict or controller_record.get('appId')!=CONTROLLER or controller_record.get('run')!=run or type(controller_record.get('process')) is not dict or type(pin) is not dict or pin.get('appId')!=CONTROLLER or not callable(read):raise ValueError('invalid controller identity')
 p=controller_record['process']
 if type(p.get('pid')) is not int or p['pid']<=0 or type(p.get('startTicks')) is not int or p['startTicks']<=0 or type(p.get('status')) is not dict:raise RuntimeError('controller process invalid')
 status=p['status'];uids=status.get('Uid','').split()
 if len(uids)!=4 or len(set(uids))!=1 or not uids[0].isascii() or not uids[0].isdecimal() or int(uids[0])<=0:raise RuntimeError('controller UID invalid')
 if not pkg.package_matches(controller_app,controller_package,pin):raise RuntimeError('controller package mismatch')
 def checked():
  found=att.matching_processes(controller_app,status,proc_path,python_path,allow_exe_permission_denied=allow_exe_permission_denied)
  if len(found)!=1 or found[0].get('pid')!=p['pid'] or found[0].get('startTicks')!=p['startTicks']:raise RuntimeError('controller process unconfirmed')
  return found[0]
 first=checked();request=read(receiver_state,owner_uid=int(uids[0]));second=checked();request_after=read(receiver_state,owner_uid=int(uids[0]))
 if type(request) is not dict or request.get('run')!=run or request_after!=request or first!=second:raise RuntimeError('controller or request changed')
 return {'request':request,'controllerPid':p['pid'],'controllerStartTicks':p['startTicks'],'executableVerified':first.get('exeVerified') is not False}
