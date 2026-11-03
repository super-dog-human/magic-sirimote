"""Read-only package-pin client for the controller.
"""
import runtime_bundle as bundle
import json,re
SERVICE='luna://org.codex.siriremote.v20scheduler20261031a.service/receiverPin'
RECEIVER='org.codex.siriremote.hidgattrouterb20261029u'
HEX=re.compile(r'^[0-9a-f]{64}$')
PATH=re.compile(r'^[a-zA-Z0-9_./-]+$')
def validate_response(response):
 if type(response) is not dict or set(response)!={'returnValue','pin'} or response['returnValue'] is not True:raise RuntimeError('scheduler response invalid')
 pin=response['pin']
 if type(pin) is not dict or set(pin)!={'appId','files','packageInfoSha256'} or pin['appId']!=RECEIVER or type(pin['packageInfoSha256']) is not str or not HEX.fullmatch(pin['packageInfoSha256']):raise RuntimeError('pin invalid')
 files=pin['files']
 if type(files) is not dict or not 1<=len(files)<=200:raise RuntimeError('file list invalid')
 for k,v in files.items():
  if type(k) is not str or not PATH.fullmatch(k) or k.startswith('/') or any(part in ('','.','..') for part in k.split('/')) or type(v) is not str or not HEX.fullmatch(v):raise RuntimeError('file entry invalid')
 if len(json.dumps(response,separators=(',',':')).encode())>32768:raise RuntimeError('response too large')
 return pin

def read_pin(call):
 if bundle.active():return bundle.read_pin('receiver')
 if not callable(call):raise ValueError('transport required')
 # The transport must identify the exact LS2 service response, bound its time
 # and reject duplicate JSON keys; no default trust decision is implemented.
 return validate_response(call(SERVICE,{}))
