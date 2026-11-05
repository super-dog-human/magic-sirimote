"""Read navigation while sensor setup waits; preserve one input pipeline.

The caller supplies an initialized input link, verified descriptors, and a
current-generation guard. No Bluetooth commands or device opens occur here.
Motion is disabled until the active sensor session adopts this pipeline.
"""
import errno
import os
from rolling_receiver import RollingReceiver
from combined_controls import CombinedControls

class EarlyNavigation:
    poll_interval = .005

    def __call__(self):
        self.pump()

    def __init__(self, outputs, fd, *, generation, guard, abort, clock,
                 read_fn=None, system_key_emit=None, screen_control=None):
        if (type(fd) is not int or fd < 0 or type(generation) is not int or generation <= 0
                or not all(callable(x) for x in (guard, abort, clock))):
            raise ValueError('initialized input and guarded descriptors required')
        self.fd=fd;self.generation=generation;self.guard=guard;self.abort=abort
        self.read=os.read if read_fn is None else read_fn
        self.closed=False;self.adopted=False;self.started=False
        self.stats={'reads':0,'reports':0,'bytes':0,'motionEnabled':False}
        self.rolling=RollingReceiver(outputs,continuity=self.valid,mode_verified=lambda:False,
                                     navigation_verified=self.valid,clock=clock,seconds=300)
        self.receiver=(CombinedControls(self.rolling,system_key_emit,screen_control=screen_control)
                       if system_key_emit is not None else self.rolling)

    def valid(self):
        return not self.closed and self.abort() is False and self.guard() is True

    def start(self):
        if self.started or not self.valid():raise RuntimeError('early input unavailable')
        self.started=True
        self.receiver.start()

    def pump(self):
        if self.closed or self.adopted:return
        if not self.started or not self.valid():
            self.stop();raise RuntimeError('early input control lost')
        try:
            self.receiver.tick()
            if self.receiver.closed:raise RuntimeError('early input ended')
            self.stats['reads']+=1
            try:data=self.read(self.fd,4096)
            except (BlockingIOError,InterruptedError):return
            if not data:raise OSError(errno.EIO,'input disconnected')
            if not self.valid():raise RuntimeError('early input changed during read')
            self.stats['reports']+=1;self.stats['bytes']+=len(data)
            self.receiver.feed_raw(1,data)
            self.receiver.tick()
            if self.receiver.closed:raise RuntimeError('early input ended')
        except BaseException:
            self.stop();raise

    def adopt(self,session,*,live,outputs,fd):
        from borrowed_mode_session import BorrowedModeSession
        if (self.closed or self.adopted or not self.started or not self.valid()
                or type(session) is not BorrowedModeSession or session.state!='active'
                or session.view.generation!=self.generation or session.control_valid() is not True
                or outputs is not self.rolling.outputs or fd!=self.fd or not callable(live)
                or live() is not True):
            raise RuntimeError('early input handoff rejected')
        # No new parser, button binding or read is created at this boundary.
        self.rolling.continuity=live;self.rolling.mode_verified=live
        self.rolling.navigation_verified=None
        self.adopted=True
        return self.receiver

    def stop(self):
        if self.closed:return
        self.closed=True
        self.receiver.stop('early-input-ended')
