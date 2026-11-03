"""Bounded, one-attempt TV-local application launch adapter.

Caller must durably record launch intent before calling. This file performs no
operation on import and does not by itself establish a TV service grant.
"""
import runtime_bundle as bundle
import json,re,subprocess
APPS={'A':bundle.app_id('org.codex.siriremote.hidgattroutera20261029u'),'B':bundle.app_id('org.codex.siriremote.hidgattrouterb20261029u')}
URI='luna://com.webos.applicationManager/launch'
def _strict(raw):
 if not isinstance(raw,str) or len(raw.encode('utf8'))>8192:raise ValueError('invalid reply')
 def unique(pairs):
  out={}
  for k,v in pairs:
   if k in out:raise ValueError('duplicate key')
   out[k]=v
  return out
 obj=json.loads(raw,object_pairs_hook=unique)
 if not isinstance(obj,dict) or type(obj.get('returnValue')) is not bool:raise ValueError('invalid reply')
 return obj
class Launcher:
 def __init__(self,run,invoke=subprocess.run):
  if not isinstance(run,str) or not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('invalid run')
  self.run=run;self.invoke=invoke;self.attempted=set()
 def launch(self,role,run):
  if run!=self.run or role not in APPS:raise ValueError('invalid target')
  if role in self.attempted:raise RuntimeError('launch already attempted')
  self.attempted.add(role)
  args=['/usr/bin/luna-send-pub','-n','1','-f',URI,json.dumps({'id':APPS[role],'params':{}},separators=(',',':'))]
  try:
   result=self.invoke(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=15,check=False)
   if result.returncode!=0 or not result.stdout:return 'unknown'
   reply=_strict(result.stdout)
   return 'accepted' if reply['returnValue'] is True else 'rejected'
  except (OSError,subprocess.TimeoutExpired,ValueError,TypeError):return 'unknown'
