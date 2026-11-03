"""Bounded native LS2 calls as the application's own unprivileged account."""
import ctypes as C
import json
import os
import time
from pathlib import Path


class Error(C.Structure):
    _fields_ = [('code', C.c_int), ('message', C.c_char_p), ('file', C.c_char_p),
                ('line', C.c_int), ('func', C.c_char_p), ('padding', C.c_void_p), ('magic', C.c_ulong)]


class Luna:
    def __enter__(self):
        from ir_programmer import APP
        expected = '/media/developer/apps/usr/palm/applications/' + APP + '/native_probe.py'
        command = (Path('/proc/self/cmdline').read_bytes()).rstrip(b'\0').split(b'\0')
        if os.getuid() <= 0 or os.getgid() != 5000 or command != [b'/usr/bin/python3', b'-I', b'-B', expected.encode()]:
            raise RuntimeError('Open the installed native app on the TV to program infrared.')
        self.lib = C.CDLL('libluna-service2.so.3')
        self.glib = C.CDLL('libglib-2.0.so.0')
        self.callback_type = C.CFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p, C.c_void_p)
        self.error = Error()
        self.handle = C.c_void_p()
        self.context = None
        def bind(lib, name, result, args):
            fn = getattr(lib, name); fn.restype = result; fn.argtypes = args
            return fn
        e = C.POINTER(Error); h = C.c_void_p
        self.init = bind(self.lib, 'LSErrorInit', C.c_bool, [e])
        self.free = bind(self.lib, 'LSErrorFree', None, [e])
        self.register = bind(self.lib, 'LSRegister', C.c_bool, [C.c_char_p, C.POINTER(h), e])
        self.unregister = bind(self.lib, 'LSUnregister', C.c_bool, [h, e])
        self.attach = bind(self.lib, 'LSGmainContextAttach', C.c_bool, [h, h, e])
        self.call = bind(self.lib, 'LSCallOneReply', C.c_bool,
                         [h, C.c_char_p, C.c_char_p, self.callback_type, h, C.POINTER(C.c_ulong), e])
        self.payload = bind(self.lib, 'LSMessageGetPayload', C.c_char_p, [h])
        self.new_context = bind(self.glib, 'g_main_context_new', h, [])
        self.iterate = bind(self.glib, 'g_main_context_iteration', C.c_int, [h, C.c_int])
        self.unref = bind(self.glib, 'g_main_context_unref', None, [h])
        self.init(C.byref(self.error))
        self.callbacks = []
        self.failed = False
        try:
            self.check(self.register(None, C.byref(self.handle), C.byref(self.error)))
            self.context = self.new_context()
            if not self.context:
                raise RuntimeError('Bluetooth service context is unavailable.')
            self.check(self.attach(self.handle, self.context, C.byref(self.error)))
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def check(self, ok):
        if not ok:
            self.free(C.byref(self.error)); self.init(C.byref(self.error))
            raise RuntimeError('Bluetooth service access failed.')

    def __call__(self, method, params, timeout):
        from ir_programmer import BASE
        if self.failed:
            raise RuntimeError('Bluetooth communication stopped after an uncertain response.')
        if method not in ('adapter/getStatus', 'adapter/unpair', 'device/getStatus', 'hid/getStatus', 'gatt/getStatus', 'gatt/connect', 'gatt/discoverServices',
                          'gatt/readCharacteristicValues', 'gatt/readDescriptorValues',
                          'hid/internal/setReport', 'gatt/disconnect') or not 0 < timeout <= 12:
            raise ValueError('Unsupported configuration request.')
        replies = []
        @self.callback_type
        def receive(handle, message, data):
            try:
                raw = self.payload(message)
                if raw is None or len(raw) > 65536:
                    raise ValueError('Unexpected reply size')
                replies.append(json.loads(raw))
            except Exception:
                replies.append(None)
            return True
        # Retain every callback until unregister, including after a timeout.
        self.callbacks.append(receive)
        token = C.c_ulong()
        try:
            self.check(self.call(self.handle, (BASE + method).encode(), json.dumps(params).encode(),
                                 receive, None, C.byref(token), C.byref(self.error)))
            deadline = time.monotonic() + timeout
            while not replies and time.monotonic() < deadline:
                self.iterate(self.context, False)
                time.sleep(.005)
            if len(replies) != 1 or type(replies[0]) is not dict:
                raise RuntimeError('No reliable Bluetooth response. The request was not repeated.')
            return replies[0]
        except Exception:
            self.failed = True
            raise

    def __exit__(self, *args):
        if self.handle.value:
            self.unregister(self.handle, C.byref(self.error))
            self.handle = C.c_void_p()
        if self.context:
            self.unref(self.context); self.context = None
        self.free(C.byref(self.error))
