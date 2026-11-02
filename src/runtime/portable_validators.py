"""Generated receiver validators; no host launcher, network, or device I/O."""
import re
APP_A_ID='org.codex.siriremote.hidgattroutera20261029u'
APP_B_ID='org.codex.siriremote.hidgattrouterb20261029u'
TARGET='02:00:00:00:00:01'
APPS=(('A',APP_A_ID,'native_probe.py'),('B',APP_B_ID,'native_probe.py'))
A_READY_DEADLINE_SECONDS=390
B_READY_DEADLINE_SECONDS=75
RESULT_DEADLINE_SECONDS=220
def profiles_confirm_connected(v):
 if not isinstance(v,dict):return False
 for name in ('hid','gatt'):
  item=v.get(name)
  if not isinstance(item,dict) or item.get('returncode')!=0 or not isinstance(item.get('reply'),dict):return False
  r=item['reply']
  if r.get('returnValue') is not True or str(r.get('address','')).lower()!='02:00:00:00:00:01' or str(r.get('adapterAddress','')).lower()!='02:00:00:00:00:02' or r.get('connected') is not True or r.get('connecting') is not False or r.get('connectRequest') is not False:return False
 return True

def profiles_confirm_cleanup(v):
 if not isinstance(v,dict):return False
 for name,want in (('hid',False),('gatt',True)):
  item=v.get(name)
  if not isinstance(item,dict) or item.get('returncode')!=0 or not isinstance(item.get('reply'),dict):return False
  r=item['reply']
  if r.get('returnValue') is not True or str(r.get('address','')).lower()!='02:00:00:00:00:01' or str(r.get('adapterAddress','')).lower()!='02:00:00:00:00:02' or r.get('connected') is not want or r.get('connecting') is not False or r.get('connectRequest') is not False:return False
 return True

def valid_target_identity(ident):
 return isinstance(ident,dict) and ident.get('matches') is True and ident.get('bus')==5 and ident.get('vendor')==0x004c and ident.get('product')==0x0266 and ident.get('name')=='EXAMPLE_REMOTE_SERIAL' and str(ident.get('uniq','')).lower()=='02:00:00:00:00:01'

def valid_ordinary_process(p):
 if not isinstance(p,dict):return False
 u=str(p.get('Uid','')).split();g=str(p.get('Gid','')).split()
 return len(u)==4 and len(set(u))==1 and u[0]!='0' and len(g)==4 and set(g)=={'5000'} and p.get('CapEff')=='0000000000000000'

def valid_action_output_devices(records,inventory,process):
 if not isinstance(records,list) or len(records)!=2 or not isinstance(inventory,dict) or inventory.get('inventoryComplete') is not True:return False
 if not valid_ordinary_process(process):return False
 gids=str(process.get('Groups','')).split()
 if any(not re.fullmatch(r'[0-9]{1,10}',g) for g in gids):return False
 permitted_gids=set(gids)|set(str(process.get('Gid','')).split())
 by={x.get('name'):x for x in records if isinstance(x,dict)}
 if set(by)!={'LGE M-RCU - Builtin [1]','ClickableMouse'}:return False
 if len({(x.get('dev'),x.get('inode'),x.get('rdev')) for x in records})!=2 or len({x.get('path') for x in records})!=2:return False
 if by['LGE M-RCU - Builtin [1]'].get('capabilitiesVerified') is not True or by['LGE M-RCU - Builtin [1]'].get('eventTypes')!=[0,1] or by['LGE M-RCU - Builtin [1]'].get('keyCodes')!=[103,105,106,108]:return False
 if by['ClickableMouse'].get('capabilitiesVerified') is not True or by['ClickableMouse'].get('eventTypes')!=[0,1,2] or by['ClickableMouse'].get('keyCodes')!=[0x110] or by['ClickableMouse'].get('relativeCodes')!=[0,1]:return False
 for x in records:
  if not isinstance(x.get('path'),str) or not re.fullmatch(r'/dev/input/event(?:[0-9]|[1-9][0-9]|1[01][0-9]|12[0-7])',x['path']):return False
  if any(type(x.get(k)) is not int for k in ('dev','inode','rdev','uid','gid')):return False
  if x.get('uid')!=0 or str(x.get('gid')) not in permitted_gids:return False
  if x.get('mode')!='0o660':return False
 return inventory.get('candidateCounts')=={'LGE M-RCU - Builtin [1]':1,'ClickableMouse':1}

def snapshot_profiles_connected(snapshot):
 if not isinstance(snapshot,dict):return False
 for name in ('hid','gatt'):
  item=snapshot.get(name);r=item.get('reply') if isinstance(item,dict) and item.get('returncode')==0 else None
  if not isinstance(r,dict) or r.get('returnValue') is not True or str(r.get('address','')).lower()!='02:00:00:00:00:01' or str(r.get('adapterAddress','')).lower()!='02:00:00:00:00:02' or r.get('connected') is not True or r.get('connecting') is not False or r.get('connectRequest') is not False:return False
 return True

def valid_b_observation(report):
 if not isinstance(report,dict) or report.get('status')!='complete' or report.get('readStarted') is not True:return False
 scope=report.get('scope',{});ident=report.get('targetIdentity',{})
 if not valid_target_identity(ident) or type(report.get('targetIndex')) is not int or not 0<=report['targetIndex']<32 or report.get('profileStable') is not True:return False
 if not valid_ordinary_process(report.get('process')):return False
 if not snapshot_profiles_connected(report.get('profilesAtOpen')) or not snapshot_profiles_connected(report.get('profilesAfterReceive')):return False
 if scope.get('rawReportsPersisted') is not False or scope.get('fdClosed') is not True or scope.get('outputFdsClosed') is not True or scope.get('outputStateReleased') is not True or scope.get('readCalls',0)<=0:return False
 if any(scope.get(k)!=0 for k in ('bluetoothWrites','connectCalls','disconnectCalls','cccdWrites','sensorWrites','selectorWrites','grabCalls')):return False
 if type(scope.get('inputWrites')) is not int or scope['inputWrites']!=scope.get('keyFrameWrites',-1)+scope.get('clickFrameWrites',-1):return False
 actions=report.get('actions')
 if not isinstance(actions,dict) or actions.get('rawReportsPersisted') is not False or actions.get('sensorEnableAttempted') is not False or actions.get('failed') is not False or actions.get('stopped') is not True or actions.get('motionGateOpen') is not False:return False
 if type(actions.get('semanticActionCount')) is not int or not 0<=actions['semanticActionCount']<=12 or actions.get('maxActions')!=12:return False
 items=actions.get('actions')
 if not isinstance(items,list) or len(items)>24:return False
 arrows=[];click_values=[]
 for item in items:
  if not isinstance(item,dict):return False
  if item.get('kind')=='arrow' and item.get('direction') in ('up','down','left','right'):arrows.append(item['direction'])
  elif item.get('kind')=='click-frame' and item.get('bytes')==32 and item.get('value') in (0,1):click_values.append(item['value'])
  else:return False
 if len(click_values)%2 or any(click_values[i:i+2]!=[1,0] for i in range(0,len(click_values),2)):return False
 if len(arrows)+len(click_values)//2!=actions['semanticActionCount']:return False
 if scope.get('keyFrameWrites')!=2*len(arrows) or scope.get('clickFrameWrites')!=len(click_values):return False
 if not isinstance(report.get('outputDevices'),list) or len(report['outputDevices'])!=2 or not valid_action_output_devices(report['outputDevices'],report.get('outputInventory'),report.get('process')):return False
 cleanup=report.get('cleanup',{})
 if cleanup.get('hidrawFdClosed') is not True or cleanup.get('outputFdsClosed') is not True or cleanup.get('outputsReleased') is not True or cleanup.get('emergencyReleaseAttempted') is not True or cleanup.get('emergencyReleaseVerified') is not True:return False
 if type(scope.get('bytesReceived')) is not int or type(scope.get('nonemptyReads')) is not int or scope['bytesReceived']<=0 or scope['nonemptyReads']<=0:return False
 if type(report.get('elapsedMs')) is not int or report['elapsedMs']<59000:return False
 cue=report.get('cueEpochNs');start=report.get('receiveStartEpochNs');end=report.get('receiveEndEpochNs')
 if any(type(x) is not int for x in (cue,start,end)) or not (cue<=start<=end) or end-start<59_000_000_000:return False
 if any(k in report for k in ('raw','rawBytes','reports','payloads')):return False
 return True

def native_cleanup_confirmed(report):
 if not isinstance(report,dict):return False
 scope=report.get('scope',{});cleanup=report.get('cleanup',{})
 if scope.get('hidConnectCalls')==0:return cleanup.get('ownershipUncertain') is not True
 return scope.get('hidConnectCalls')==1 and report.get('status')=='complete' and cleanup.get('hidClear') is True and cleanup.get('gattPreserved') is True

def validate_result_identity(role,result,run):
 ids={app_role:app_id for app_role,app_id,_ in APPS}
 if role not in ids or not isinstance(result,dict) or result.get('appId')!=ids[role] or result.get('run')!=run:raise RuntimeError(role+'-result-identity-mismatch')

def validate_final_identities(a_report,b_report,run):
 validate_result_identity('A',a_report,run);validate_result_identity('B',b_report,run)

def valid_a_ready(ready,run):
 if not isinstance(ready,dict) or ready.get('appId')!=APP_A_ID or ready.get('run')!=run or ready.get('stage')!='A_CONNECTED_F0_ACKED':return False
 reply=ready.get('f0afReply')
 if ready.get('f0afCalls')!=1 or not isinstance(reply,dict) or reply.get('returnValue') is not True or str(reply.get('address','')).lower()!=TARGET or str(reply.get('adapterAddress','')).lower()!='02:00:00:00:00:02':return False
 profiles=ready.get('profiles')
 if not isinstance(profiles,dict):return False
 for name in ('hid','gatt'):
  p=profiles.get(name)
  if not isinstance(p,dict) or p.get('returnValue') is not True or str(p.get('address','')).lower()!=TARGET or str(p.get('adapterAddress','')).lower()!='02:00:00:00:00:02' or p.get('connected') is not True or p.get('connecting') is not False or p.get('connectRequest') is not False:return False
 return True
