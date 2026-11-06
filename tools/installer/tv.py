"""Developer-connection operations for the interactive installer. No TV root."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import struct
import sys
import time

APP = 'org.magicsirimote.app'
ROOT = Path('/media/developer/apps/usr/palm')
APP_DIR = ROOT/'applications'/APP
SERVICE = ROOT/'services'/(APP+'.service')


def probe():
    missing = []
    if sys.version_info < (3, 10):
        missing.append('Python 3.10 or newer on the TV (required by the app runtime)')
    if struct.calcsize('P') != 4 or not platform.machine().lower().startswith(('arm', 'aarch')):
        missing.append('a 32-bit ARM Python runtime for this IPK; a matching build is needed for other architectures')
    for library in ('libluna-service2.so.3', 'libglib-2.0.so.0', 'libSDL2-2.0.so.0', 'libSDL2_ttf-2.0.so.0'):
        try: ctypes.CDLL(library)
        except OSError: missing.append(library+' on the TV')
    return {'missing': missing, 'appPresent': (APP_DIR/'appinfo.json').is_file(),
            'python': platform.python_version(), 'machine': platform.machine()}


def maintenance(action, nonce):
    import re
    if action not in ('start', 'stop') or re.fullmatch('[a-f0-9]{32}', nonce) is None:
        raise ValueError('Invalid maintenance request')
    parent = APP_DIR/'state'
    if not parent.is_dir(): raise RuntimeError('Installed app has no maintenance state directory')
    path = parent/('install-request-'+nonce+'.json')
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o640)
    with os.fdopen(fd, 'w') as out:
        os.fchmod(out.fileno(), 0o640)
        out.write(json.dumps({'nonce': nonce, 'action': action})+'\n')
        out.flush(); os.fsync(out.fileno())
    return {'staged': True}


def status():
    """Read the app's own status over LS2, using an anonymous client."""
    import ctypes as C
    class Error(C.Structure):
        _fields_ = [('code',C.c_int),('message',C.c_char_p),('file',C.c_char_p),
                    ('line',C.c_int),('func',C.c_char_p),('padding',C.c_void_p),('magic',C.c_ulong)]
    lib=C.CDLL('libluna-service2.so.3'); glib=C.CDLL('libglib-2.0.so.0')
    callback_type=C.CFUNCTYPE(C.c_bool,C.c_void_p,C.c_void_p,C.c_void_p)
    def bind(library,name,result,args):
        f=getattr(library,name);f.restype=result;f.argtypes=args;return f
    error_ptr=C.POINTER(Error); handle=C.c_void_p(); error=Error(); context=None
    init=bind(lib,'LSErrorInit',C.c_bool,[error_ptr]); init(C.byref(error))
    free=bind(lib,'LSErrorFree',None,[error_ptr])
    register=bind(lib,'LSRegister',C.c_bool,[C.c_char_p,C.POINTER(C.c_void_p),error_ptr])
    unregister=bind(lib,'LSUnregister',C.c_bool,[C.c_void_p,error_ptr])
    attach=bind(lib,'LSGmainContextAttach',C.c_bool,[C.c_void_p,C.c_void_p,error_ptr])
    call=bind(lib,'LSCallOneReply',C.c_bool,[C.c_void_p,C.c_char_p,C.c_char_p,callback_type,C.c_void_p,C.POINTER(C.c_ulong),error_ptr])
    cancel=bind(lib,'LSCallCancel',C.c_bool,[C.c_void_p,C.c_ulong,error_ptr])
    payload=bind(lib,'LSMessageGetPayload',C.c_char_p,[C.c_void_p])
    new=bind(glib,'g_main_context_new',C.c_void_p,[])
    iterate=bind(glib,'g_main_context_iteration',C.c_int,[C.c_void_p,C.c_int])
    unref=bind(glib,'g_main_context_unref',None,[C.c_void_p])
    def checked(ok):
        if not ok: raise RuntimeError('The app status service is unavailable')
    replies=[]
    @callback_type
    def receive(_handle,message,_data):
        try: replies.append(json.loads(payload(message)))
        except Exception: replies.append({'returnValue':False})
        return True
    try:
        checked(register(None,C.byref(handle),C.byref(error)))
        context=new(); checked(bool(context)); checked(attach(handle,context,C.byref(error)))
        token=C.c_ulong()
        checked(call(handle,('luna://'+APP+'.service/status').encode(),b'{}',receive,None,C.byref(token),C.byref(error)))
        deadline=time.monotonic()+12
        while not replies and time.monotonic()<deadline:
            iterate(context,False);time.sleep(.01)
        if not replies:
            cancel(handle,token,C.byref(error));raise RuntimeError('The app did not answer its status check')
        reply=replies[0]
        return {key:reply.get(key) for key in ('returnValue','cleanStop','startup','processes')}
    finally:
        if handle.value: unregister(handle,C.byref(error))
        if context: unref(context)
        free(C.byref(error))


def verify(expected):
    bad=[]
    for name,digest in expected.items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts: raise ValueError('Invalid package manifest path')
        p=Path('/media/developer/apps')/relative
        try:
            if not stat.S_ISREG(p.lstat().st_mode) or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:bad.append(name)
        except OSError:bad.append(name)
    return {'verifiedFiles':len(expected)-len(bad),'mismatch':bad}


def dispatch(request):
    action=request['action']
    if action=='removal-info':return {'appPresent': APP_DIR.exists() or SERVICE.exists()}
    if action=='probe':return probe()
    if action=='status':return status()
    if action=='maintenance':return maintenance(request['operation'],request['nonce'])
    if action=='verify':return verify(request['files'])
    raise ValueError('Unknown installer operation')
