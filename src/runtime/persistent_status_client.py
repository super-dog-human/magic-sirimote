"""One anonymous LS2 handle for bounded, read-only profile polls.

Create, call, and close on the same polling thread. No process is spawned and
no service identity is borrowed. Subscription events remain a separate input
to the existing connection-generation tracker.
"""
import ctypes as C
import json
import threading
import time

TARGET = '02:00:00:00:00:01'
METHODS = ('hid/getStatus', 'gatt/getStatus')


class Error(C.Structure):
    _fields_ = [('code', C.c_int), ('message', C.c_char_p),
                ('file', C.c_char_p), ('line', C.c_int),
                ('func', C.c_char_p), ('padding', C.c_void_p),
                ('magic', C.c_ulong)]


REPLY = C.CFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p, C.c_void_p)
DISCONNECT = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p)


class PersistentStatusClient:
    def __init__(self, *, abort=lambda: False):
        if not callable(abort):
            raise ValueError('abort callback required')
        self.owner = threading.get_ident()
        self.abort = abort
        self.handle = C.c_void_p()
        self.context = None
        self.closed = self.disconnected = False
        self.callbacks = []
        self.lib = C.CDLL('libluna-service2.so.3')
        self.glib = C.CDLL('libglib-2.0.so.0')
        def bind(lib, name, result, args):
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = result, args
            return fn
        ep = C.POINTER(Error)
        self.init_error = bind(self.lib, 'LSErrorInit', C.c_bool, [ep])
        self.free_error = bind(self.lib, 'LSErrorFree', None, [ep])
        self.register = bind(self.lib, 'LSRegister', C.c_bool,
                             [C.c_char_p, C.POINTER(C.c_void_p), ep])
        self.unregister = bind(self.lib, 'LSUnregister', C.c_bool, [C.c_void_p, ep])
        self.attach = bind(self.lib, 'LSGmainContextAttach', C.c_bool,
                           [C.c_void_p, C.c_void_p, ep])
        self.set_disconnect = bind(self.lib, 'LSSetDisconnectHandler', C.c_bool,
                                   [C.c_void_p, DISCONNECT, C.c_void_p, ep])
        self.call_one = bind(self.lib, 'LSCallOneReply', C.c_bool,
                             [C.c_void_p, C.c_char_p, C.c_char_p, REPLY,
                              C.c_void_p, C.POINTER(C.c_ulong), ep])
        self.cancel = bind(self.lib, 'LSCallCancel', C.c_bool,
                           [C.c_void_p, C.c_ulong, ep])
        self.payload = bind(self.lib, 'LSMessageGetPayload', C.c_char_p, [C.c_void_p])
        self.context_new = bind(self.glib, 'g_main_context_new', C.c_void_p, [])
        self.iterate = bind(self.glib, 'g_main_context_iteration', C.c_int,
                            [C.c_void_p, C.c_int])
        self.context_unref = bind(self.glib, 'g_main_context_unref', None, [C.c_void_p])
        self.error = Error()
        self.init_error(C.byref(self.error))
        @DISCONNECT
        def disconnect(handle, data):
            self.disconnected = True
        self.disconnect_callback = disconnect
        try:
            self._check(self.register(None, C.byref(self.handle), C.byref(self.error)))
            self.context = self.context_new()
            if not self.context:
                raise RuntimeError('LS2 context unavailable')
            self._check(self.attach(self.handle, self.context, C.byref(self.error)))
            self._check(self.set_disconnect(self.handle, disconnect, None, C.byref(self.error)))
        except BaseException:
            self.close()
            raise

    def _check(self, ok):
        if not ok:
            self.free_error(C.byref(self.error))
            self.init_error(C.byref(self.error))
            raise RuntimeError('LS2 operation failed')

    def _thread(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError('LS2 client thread changed')

    def read(self, method, *, timeout=3):
        self._thread()
        if method not in METHODS or type(timeout) not in (int, float) or not 0 < timeout <= 3:
            raise ValueError('bounded profile status read required')
        if self.closed or self.disconnected or self.abort():
            raise RuntimeError('LS2 client unavailable')
        replies = []
        @REPLY
        def receive(handle, message, data):
            try:
                raw = self.payload(message)
                if raw is None or len(raw) > 65536:
                    raise ValueError('reply size invalid')
                value = json.loads(raw)
                replies.append(value if type(value) is dict else None)
            except Exception:
                replies.append(None)
            return True
        # Keep the callback alive until delivery, cancellation, or unregister.
        self.callbacks.append(receive)
        token = C.c_ulong()
        delivered = False
        try:
            self._check(self.call_one(self.handle,
                ('luna://com.webos.service.bluetooth2/' + method).encode(),
                json.dumps({'address': TARGET, 'subscribe': False}).encode(),
                receive, None, C.byref(token), C.byref(self.error)))
            deadline = time.monotonic() + timeout
            while not replies:
                if self.disconnected or self.abort():
                    raise RuntimeError('LS2 read interrupted')
                if time.monotonic() >= deadline:
                    raise TimeoutError('LS2 read timed out')
                self.iterate(self.context, False)
                if not replies:
                    time.sleep(.005)
            delivered = True
            if len(replies) != 1 or type(replies[0]) is not dict:
                raise RuntimeError('LS2 reply invalid')
            if self.disconnected or self.abort():
                raise RuntimeError('LS2 read interrupted')
            return replies[0]
        finally:
            if delivered:
                self.callbacks.remove(receive)
            elif token.value:
                # On any uncertain call, stop using the handle. Unregister
                # releases all remaining callbacks before their Python refs.
                if not self.cancel(self.handle, token, C.byref(self.error)):
                    self.free_error(C.byref(self.error))
                    self.init_error(C.byref(self.error))
                self.close()
            else:
                self.close()

    def poll(self):
        return {role: self.read(role + '/getStatus') for role in ('hid', 'gatt')}

    def close(self):
        self._thread()
        if self.closed:
            return
        if self.handle.value:
            self._check(self.unregister(self.handle, C.byref(self.error)))
            self.handle = C.c_void_p()
        if self.context:
            self.context_unref(self.context)
            self.context = None
        self.callbacks.clear()
        self.free_error(C.byref(self.error))
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
