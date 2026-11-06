"""Read-only cursor visibility tracking for the lifetime of input reception.

Uses only wl_display.get_registry and wl_registry.bind. The webOS input
manager is listened to; set_cursor_visibility is deliberately not described.
"""
import ctypes as C
import errno
import json
import os
import select
import threading
import time

class Interface(C.Structure):
    pass
class Message(C.Structure):
    _fields_=[('name',C.c_char_p),('signature',C.c_char_p),('types',C.POINTER(C.POINTER(Interface)))]
Interface._fields_=[('name',C.c_char_p),('version',C.c_int),('method_count',C.c_int),('methods',C.POINTER(Message)),('event_count',C.c_int),('events',C.POINTER(Message))]

class VisibilityClient:
    def __init__(self):
        self.lib=C.CDLL('libwayland-client.so.0',use_errno=True)
        self.display=self.registry=self.manager=None
        self.values=[];self.error=None;self.globals=0
        def bind(name,result,args):
            f=getattr(self.lib,name);f.restype=result;f.argtypes=args;return f
        self.connect=bind('wl_display_connect',C.c_void_p,[C.c_char_p])
        self.disconnect=bind('wl_display_disconnect',None,[C.c_void_p])
        self.marshal=bind('wl_proxy_marshal_constructor_versioned',C.c_void_p,[C.c_void_p,C.c_uint,C.POINTER(Interface),C.c_uint])
        self.listen=bind('wl_proxy_add_listener',C.c_int,[C.c_void_p,C.c_void_p,C.c_void_p])
        self.destroy=bind('wl_proxy_destroy',None,[C.c_void_p])
        self.prepare=bind('wl_display_prepare_read',C.c_int,[C.c_void_p])
        self.cancel=bind('wl_display_cancel_read',None,[C.c_void_p])
        self.read=bind('wl_display_read_events',C.c_int,[C.c_void_p])
        self.pending=bind('wl_display_dispatch_pending',C.c_int,[C.c_void_p])
        self.flush=bind('wl_display_flush',C.c_int,[C.c_void_p])
        self.get_fd=bind('wl_display_get_fd',C.c_int,[C.c_void_p])
        self.registry_interface=Interface.in_dll(self.lib,'wl_registry_interface')
        self.seat_interface=Interface(b'wl_webos_seat',1,0,None,0,None)
        self.types=(C.POINTER(Interface)*2)(None,C.pointer(self.seat_interface))
        self.events=(Message*1)(Message(b'cursor_visibility',b'u?o',self.types))
        self.manager_interface=Interface(b'wl_webos_input_manager',1,0,None,1,self.events)
        Global=C.CFUNCTYPE(None,C.c_void_p,C.c_void_p,C.c_uint,C.c_char_p,C.c_uint)
        Remove=C.CFUNCTYPE(None,C.c_void_p,C.c_void_p,C.c_uint)
        Visible=C.CFUNCTYPE(None,C.c_void_p,C.c_void_p,C.c_uint,C.c_void_p)
        self.global_cb=Global(self._global);self.remove_cb=Remove(self._removed);self.visible_cb=Visible(self._visible)
        self.registry_listener=(C.c_void_p*2)(C.cast(self.global_cb,C.c_void_p),C.cast(self.remove_cb,C.c_void_p))
        self.manager_listener=(C.c_void_p*1)(C.cast(self.visible_cb,C.c_void_p))
        self.manager_name=None
        try:
            # The ARM launcher intentionally starts Python with an empty environment.
            # Use the same runtime directory as our native Canvas, within this jail.
            os.environ.setdefault('XDG_RUNTIME_DIR','/tmp/xdg')
            self.display=self.connect(None)
            if not self.display:raise OSError(C.get_errno(),'display unavailable')
            self.registry=self.marshal(self.display,1,C.byref(self.registry_interface),1,C.c_void_p())
            if not self.registry or self.listen(self.registry,self.registry_listener,None)!=0:raise RuntimeError('registry unavailable')
        except BaseException:
            self.close();raise
    def _global(self,data,registry,name,interface,version):
        try:
            self.globals+=1
            if self.globals>256:raise RuntimeError('registry limit')
            if interface!=b'wl_webos_input_manager' or version<1:return
            if self.manager is not None:raise RuntimeError('duplicate input manager')
            self.manager_name=name
            self.manager=self.marshal(registry,0,C.byref(self.manager_interface),1,C.c_uint(name),C.c_char_p(interface),C.c_uint(1),C.c_void_p())
            if not self.manager or self.listen(self.manager,self.manager_listener,None)!=0:raise RuntimeError('manager unavailable')
        except BaseException as exc:self.error=type(exc).__name__
    def _removed(self,data,registry,name):
        if name==self.manager_name:self.error='ManagerRemoved'
    def _visible(self,data,manager,value,seat):
        if value not in (0,1) or len(self.values)>=32:
            self.error='InvalidVisibility';return
        self.values.append({'visible':bool(value),'uptime':round(time.monotonic(),6)})
    def poll(self,timeout):
        if not 0<=timeout<=.2:raise ValueError('bounded poll required')
        prepared=False
        try:
            for _ in range(64):
                if self.prepare(self.display)==0:prepared=True;break
                if self.pending(self.display)<0:raise RuntimeError('display error')
            if not prepared:raise RuntimeError('display queue limit')
            if self.flush(self.display)<0 and C.get_errno()!=errno.EAGAIN:raise RuntimeError('flush failed')
            ready,_,_=select.select([self.get_fd(self.display)],[],[],timeout)
            if ready:
                prepared=False
                if self.read(self.display)<0:raise RuntimeError('display read failed')
            else:
                self.cancel(self.display);prepared=False
            if self.pending(self.display)<0:raise RuntimeError('dispatch failed')
            if self.error:raise RuntimeError(self.error)
            values=self.values;self.values=[];return values
        finally:
            if prepared:self.cancel(self.display)
    def close(self):
        for name in ('manager','registry'):
            pointer=getattr(self,name,None)
            if pointer:self.destroy(pointer);setattr(self,name,None)
        if self.display:self.disconnect(self.display);self.display=None

class VisibilityState:
    """Unknown unless a real event arrived and this connection is still polled."""
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.lock=threading.Lock();self.value=None;self.last_poll=None
    def update(self,values):
        with self.lock:
            for value in values:
                if type(value.get('visible')) is not bool:raise ValueError('invalid visibility')
                self.value=value['visible']
            self.last_poll=self.clock()
    def clear(self):
        with self.lock:self.value=None;self.last_poll=None
    def current(self):
        with self.lock:
            if self.last_poll is None or not 0<=self.clock()-self.last_poll<=.5:return None
            return self.value

_state=VisibilityState()
def current_visibility():return _state.current()

def observe(*,factory=VisibilityClient,clock=time.monotonic,emit=None,state=None,duration=180,max_events=64,stop_event=None):
    if (duration is None and stop_event is None) or (duration is not None and not 0<duration<=600):raise ValueError("observer lifetime required")
    if type(max_events) is not int or not 1<=max_events<=256:raise ValueError("bounded diagnostics required")
    emit=emit or (lambda value:print(json.dumps({'stage':'cursor-visibility-probe',**value}),flush=True))
    client=None;start=clock();last=None;rows=0
    try:
        client=factory();emit({'event':'connected','uptime':round(start,6)})
        while (stop_event is None or not stop_event.is_set()) and (duration is None or (clock()-start<duration and rows<max_events)):
            values=client.poll(.1)
            if state is not None:state.update(values)
            for value in values:
                if type(value.get('visible')) is not bool:raise ValueError('invalid visibility')
                if value['visible']!=last:
                    if rows<max_events:emit({'event':'visibility',**value})
                    last=value['visible'];rows+=1
                if duration is not None and rows>=max_events:break
        emit({'event':'end','uptime':round(clock(),6),'observations':rows})
    except Exception as exc:
        emit({'event':'unavailable','errorType':type(exc).__name__,'errno':getattr(exc,'errno',None)})
    finally:
        if state is not None:state.clear()
        if client is not None:client.close()

class VisibilityMonitor:
    def __init__(self, *, state, factory=VisibilityClient, emit=None):
        self.state=state;self.factory=factory;self.emit=emit
        self.stopped=threading.Event()
        self.thread=threading.Thread(target=self.run,name='cursor-visibility',daemon=True)
    def run(self):
        while not self.stopped.is_set():
            observe(factory=self.factory,state=self.state,emit=self.emit,
                    duration=None,max_events=256,stop_event=self.stopped)
            if self.stopped.wait(1):break
    def close(self):
        self.stopped.set()
        self.thread.join(timeout=2)
        self.state.clear()

_monitor=None
_lock=threading.Lock()
def start():
    import runtime_bundle
    if not runtime_bundle.active():return None
    global _monitor
    with _lock:
        if _monitor is not None and _monitor.thread.is_alive():
            if _monitor.stopped.is_set():raise RuntimeError('visibility monitor is stopping')
            return _monitor
        _monitor=VisibilityMonitor(state=_state)
        _monitor.thread.start()
        return _monitor
