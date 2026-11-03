"""Lifecycle notifications and own-service requests as this native application's ID."""
import ctypes as C
import json
import os
import time
from collections import deque
from pathlib import Path
from native_luna import Error

APP = 'org.magicsirimote.app'


def lifecycle_event(value):
    if type(value) is not dict or value.get('returnValue') is not True:
        raise RuntimeError('Native lifecycle registration failed')
    event = value.get('message', value.get('event'))
    if event not in ('registered', 'relaunch', 'pause', 'close'):
        raise ValueError('Unknown native lifecycle event')
    params = value.get('parameters', {})
    if type(params) is not dict:
        raise ValueError('Invalid native launch parameters')
    return event, params


def verify_process():
    expected = '/media/developer/apps/usr/palm/applications/' + APP + '/native_probe.py'
    args = Path('/proc/self/cmdline').read_bytes().rstrip(b'\0').split(b'\0')
    fields = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    return (os.getuid() > 0 and os.getgid() == 5000
            and args == [b'/usr/bin/python3', b'-I', b'-B', expected.encode()]
            and fields.get('Uid', '').split() == [str(os.getuid())] * 4
            and fields.get('Gid', '').split() == ['5000'] * 4
            and fields.get('CapEff', '').strip() == '0000000000000000')


class NativeBus:
    def __init__(self):
        self.handle = C.c_void_p()
        self.context = None
        self.callbacks = []
        self.queue = deque()
        self.ready = False
        self.failed = False
        self.error = None

    def __enter__(self):
        if not verify_process():
            raise RuntimeError('Open the installed Magic Sirimote application')
        self.lib = C.CDLL('libluna-service2.so.3')
        self.glib = C.CDLL('libglib-2.0.so.0')
        self.callback_type = C.CFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p, C.c_void_p)
        h = C.c_void_p; e = C.POINTER(Error)
        def bind(lib, name, result, args):
            fn = getattr(lib, name); fn.restype = result; fn.argtypes = args
            return fn
        self.init = bind(self.lib, 'LSErrorInit', C.c_bool, [e])
        self.free = bind(self.lib, 'LSErrorFree', None, [e])
        self.register = bind(self.lib, 'LSRegister', C.c_bool, [C.c_char_p, C.POINTER(h), e])
        self.unregister = bind(self.lib, 'LSUnregister', C.c_bool, [h, e])
        self.attach = bind(self.lib, 'LSGmainContextAttach', C.c_bool, [h, h, e])
        self.send = bind(self.lib, 'LSCall', C.c_bool, [h, C.c_char_p, C.c_char_p, self.callback_type, h, C.POINTER(C.c_ulong), e])
        self.once = bind(self.lib, 'LSCallOneReply', C.c_bool, [h, C.c_char_p, C.c_char_p, self.callback_type, h, C.POINTER(C.c_ulong), e])
        self.payload = bind(self.lib, 'LSMessageGetPayload', C.c_char_p, [h])
        self.new = bind(self.glib, 'g_main_context_new', h, [])
        self.iterate = bind(self.glib, 'g_main_context_iteration', C.c_int, [h, C.c_int])
        self.unref = bind(self.glib, 'g_main_context_unref', None, [h])
        self.error = Error(); self.init(C.byref(self.error))
        try:
            # The app's own name works on the tested TV. RegisterApplicationService
            # is a different permission model and is not needed here.
            self.check(self.register(APP.encode(), C.byref(self.handle), C.byref(self.error)))
            self.context = self.new()
            if not self.context:
                raise RuntimeError('Native lifecycle context unavailable')
            self.check(self.attach(self.handle, self.context, C.byref(self.error)))
            @self.callback_type
            def receive(_handle, message, _data):
                try:
                    event = lifecycle_event(self.decode(message))
                    if len(self.queue) >= 32:
                        raise RuntimeError('Native event queue overflow')
                    if event[0] == 'registered':
                        self.ready = True
                    elif not self.ready:
                        raise RuntimeError('Native registration not confirmed')
                    self.queue.append(event)
                except Exception:
                    self.failed = True
                return True
            self.callbacks.append(receive)
            token = C.c_ulong()
            self.check(self.send(self.handle, b'luna://com.webos.applicationManager/registerNativeApp',
                                 b'{"subscribe":true}', receive, None, C.byref(token), C.byref(self.error)))
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def check(self, value):
        if not value:
            self.failed = True
            raise RuntimeError('Native application bus operation failed')

    def decode(self, message):
        raw = self.payload(message)
        if raw is None or len(raw) > 16384:
            raise ValueError('Native response is too large')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate response field')
                result[key] = value
            return result
        result = json.loads(raw, object_pairs_hook=unique)
        if type(result) is not dict:
            raise ValueError('Invalid native response')
        return result

    def pump(self):
        if self.failed or not self.context:
            raise RuntimeError('Native application bus is unavailable')
        for _ in range(32):
            if not self.iterate(self.context, False):
                break
        if self.failed:
            raise RuntimeError('Native application notification failed')

    def events(self):
        self.pump()
        while self.queue:
            yield self.queue.popleft()

    def request(self, method, params, timeout=8):
        if method not in ('status', 'configure', 'start', 'stop', 'drain', 'resume', 'startupPrepare', 'startupBind', 'startupDisable', 'startupRepair', 'startupCancelled'):
            raise ValueError('Unsupported application request')
        return self._request_uri('luna://' + APP + '.service/' + method, params, timeout)

    def tv_address(self):
        # A failed Bluetooth read must not invalidate the lifecycle/service bus.
        from settings import read_tv_address
        return read_tv_address()

    def remote_name(self, remote, adapter):
        from settings import read_remote_name
        return read_remote_name(remote, adapter)

    def cancel_startup(self, activity_id):
        if type(activity_id) is not int or activity_id <= 0: raise ValueError('Invalid activity ID')
        return self._request_uri('luna://com.webos.service.activitymanager/cancel', {'activityId': activity_id}, 8)

    def create_startup(self, token):
        import re
        if type(token) is not str or not re.fullmatch('[a-f0-9]{48}', token):
            raise ValueError('Invalid startup token')
        from datetime import datetime, timezone, timedelta
        start = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime('%Y-%m-%d %H:%M:%SZ')
        return self._request_uri('luna://com.webos.service.activitymanager/create', {
            'activity': {'name': APP + '.startup', 'description': 'Magic Sirimote automatic startup',
                         'type': {'foreground': True, 'persist': True, 'explicit': False, 'continuous': False},
                         'schedule': {'start': start},
                         'callback': {'method': 'luna://' + APP + '.service/startupTick', 'params': {'token': token}}},
            'start': True, 'subscribe': False, 'replace': False}, 8)

    def _request_uri(self, uri, params, timeout):
        if type(params) is not dict or type(timeout) not in (int, float) or not 0 < timeout <= 10:
            raise ValueError('Unsupported application request')
        if self.failed or not self.handle.value:
            raise RuntimeError('Native application bus unavailable')
        raw = json.dumps(params, separators=(',', ':')).encode()
        if len(raw) > 8192:
            raise ValueError('Application request is too large')
        replies = []
        @self.callback_type
        def receive(_handle, message, _data):
            try:
                replies.append(self.decode(message))
            except Exception:
                replies.append(None)
            return True
        self.callbacks.append(receive)
        token = C.c_ulong()
        self.check(self.once(self.handle, uri.encode(), raw,
                             receive, None, C.byref(token), C.byref(self.error)))
        deadline = time.monotonic() + timeout
        while not replies and time.monotonic() < deadline:
            self.pump(); time.sleep(.005)
        if len(replies) != 1 or type(replies[0]) is not dict:
            self.failed = True
            raise RuntimeError('Application request outcome is unknown; it was not repeated')
        # OneReply has returned through the GLib pump; its callback can now be released.
        self.callbacks.remove(receive)
        return replies[0]

    def __exit__(self, *_args):
        if self.handle.value:
            self.unregister(self.handle, C.byref(self.error)); self.handle = C.c_void_p()
        if self.context:
            self.unref(self.context); self.context = None
        if self.error is not None:
            self.free(C.byref(self.error)); self.error = None
        self.callbacks.clear()
