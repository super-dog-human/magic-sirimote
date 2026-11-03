"""Asynchronous, bounded LS2 Bluetooth calls as this native app's own UID."""
import ctypes as C
import json
import time
from collections import deque
from native_luna import Error

BASE = 'luna://com.webos.service.bluetooth2/'
METHODS = {'adapter/getStatus', 'device/getStatus', 'le/startScan',
           'adapter/pair', 'adapter/unpair', 'adapter/supplyPasskeyConfirmation', 'hid/getStatus',
           'hid/connect', 'gatt/connect', 'hid/internal/setReport', 'gatt/discoverServices', 'gatt/getServices', 'gatt/readCharacteristicValues'}


class BluetoothBus:
    def __enter__(self):
        self.lib = C.CDLL('libluna-service2.so.3')
        self.glib = C.CDLL('libglib-2.0.so.0')
        self.cbtype = C.CFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p, C.c_void_p)
        self.handle = C.c_void_p(); self.context = None
        self.error = Error(); self.jobs = {}; self.callbacks = []; self.queue = deque()
        h = C.c_void_p; e = C.POINTER(Error)
        def bind(lib, name, result, args):
            fn = getattr(lib, name); fn.restype = result; fn.argtypes = args
            return fn
        self.init = bind(self.lib, 'LSErrorInit', C.c_bool, [e])
        self.free = bind(self.lib, 'LSErrorFree', None, [e])
        self.register = bind(self.lib, 'LSRegister', C.c_bool, [C.c_char_p, C.POINTER(h), e])
        self.unregister = bind(self.lib, 'LSUnregister', C.c_bool, [h, e])
        self.attach = bind(self.lib, 'LSGmainContextAttach', C.c_bool, [h, h, e])
        signature = [h, C.c_char_p, C.c_char_p, self.cbtype, h, C.POINTER(C.c_ulong), e]
        self.send = bind(self.lib, 'LSCall', C.c_bool, signature)
        self.once = bind(self.lib, 'LSCallOneReply', C.c_bool, signature)
        self.cancel_call = bind(self.lib, 'LSCallCancel', C.c_bool, [h, C.c_ulong, e])
        self.payload = bind(self.lib, 'LSMessageGetPayload', C.c_char_p, [h])
        self.new = bind(self.glib, 'g_main_context_new', h, [])
        self.iterate = bind(self.glib, 'g_main_context_iteration', C.c_int, [h, C.c_int])
        self.unref = bind(self.glib, 'g_main_context_unref', None, [h])
        self.init(C.byref(self.error))
        try:
            self.check(self.register(None, C.byref(self.handle), C.byref(self.error)))
            self.context = self.new()
            if not self.context: raise RuntimeError('Bluetooth context unavailable')
            self.check(self.attach(self.handle, self.context, C.byref(self.error)))
            return self
        except BaseException:
            self.__exit__(None, None, None); raise

    def check(self, ok):
        if not ok:
            self.free(C.byref(self.error)); self.init(C.byref(self.error))
            raise RuntimeError('Bluetooth bus call rejected')

    def request(self, tag, method, params, timeout=10, subscription=False):
        if tag in self.jobs or len(self.callbacks) >= 512:
            raise RuntimeError('Too many requests; reopen the app')
        if method == 'main/status':
            uri = 'luna://org.magicsirimote.app.service/status'
            if params != {}: raise ValueError('Read-only main app status required')
        elif method in METHODS:
            uri = BASE + method
        else: raise ValueError('Unsupported pairing method')
        if method == 'hid/internal/setReport' and (set(params) != {'address', 'reportType', 'reportData'}
                or params['reportType'] != 'feature' or params['reportData'] != [240, 175]):
            raise ValueError('Only the input-start report is permitted')
        token = C.c_ulong()
        @self.cbtype
        def receive(_handle, message, _data):
            try:
                raw = self.payload(message)
                if raw is None or len(raw) > 131072 or len(self.queue) >= 256: raise ValueError()
                reply = json.loads(raw)
                if type(reply) is not dict: raise ValueError()
            except Exception:
                reply = {'returnValue': False, 'errorText': 'Invalid or excessive response'}
            self.queue.append((tag, reply))
            return True
        self.callbacks.append(receive)
        self.check((self.send if subscription else self.once)(self.handle, uri.encode(),
            json.dumps(params, separators=(',', ':')).encode(), receive, None,
            C.byref(token), C.byref(self.error)))
        self.jobs[tag] = (token.value, time.monotonic() + timeout, subscription)

    def cancel(self, tag, completed=False):
        job = self.jobs.pop(tag, None)
        if job:
            ok = self.cancel_call(self.handle, job[0], C.byref(self.error))
            if not ok and completed:
                self.free(C.byref(self.error)); self.init(C.byref(self.error))
            else: self.check(ok)

    def events(self):
        for _ in range(32):
            if not self.iterate(self.context, False): break
        while self.queue:
            tag, reply = self.queue.popleft()
            job = self.jobs.get(tag)
            if job:
                if not job[2]: self.jobs.pop(tag)
                yield tag, reply
        for tag, job in list(self.jobs.items()):
            if time.monotonic() >= job[1]:
                self.cancel(tag)
                yield tag, {'returnValue': False, 'errorText': 'Request timed out; not repeated'}

    def __exit__(self, *_):
        if self.handle.value:
            self.unregister(self.handle, C.byref(self.error)); self.handle = C.c_void_p()
        if self.context: self.unref(self.context); self.context = None
        self.free(C.byref(self.error)); self.callbacks.clear(); self.jobs.clear()
