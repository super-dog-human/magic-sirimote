"""A prepared controller remains inert until its parent releases a private pipe."""
import json
import os
import re
import socket
import stat
import sys

ENV = 'MAGIC_SIRIMOTE_PRELOAD'


def token(environ=os.environ):
    value = environ.get(ENV)
    if value is None:
        return None
    if type(value) is not str or re.fullmatch('[a-f0-9]{32}', value) is None:
        raise RuntimeError('Invalid controller preparation token')
    return value


def await_start(value, *, source=None, sink=None, pid=None, ticks=None):
    if re.fullmatch('[a-f0-9]{32}', value) is None:
        raise RuntimeError('Invalid controller preparation token')
    if source is None:
        source = sys.stdin
        mode = os.fstat(source.fileno()).st_mode
        if stat.S_ISSOCK(mode):
            # Node/libuv uses an inherited Unix socket pair for piped stdio.
            with socket.socket(fileno=os.dup(source.fileno())) as channel:
                if channel.family != socket.AF_UNIX or channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
                    raise RuntimeError('Unexpected controller preparation channel')
        elif not stat.S_ISFIFO(mode):
            raise RuntimeError('Controller preparation needs a private pipe')
    sink = sys.stdout if sink is None else sink
    if pid is None:
        pid = os.getpid()
    if ticks is None:
        from pathlib import Path
        from local_attestation import _start_ticks
        ticks = _start_ticks(Path('/proc/self/stat'))
    sink.write(json.dumps({'stage':'controller-preloaded','token':value,'pid':pid,'startTicks':ticks}, separators=(',', ':'))+'\n')
    sink.flush()
    line = source.readline(256)
    if not line:
        return False
    if len(line) >= 256 or not line.endswith('\n'):
        raise RuntimeError('Invalid controller preparation reply')
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('Duplicate preparation field')
            result[key] = item
        return result
    request = json.loads(line, object_pairs_hook=unique)
    if request != {'action':'start','token':value}:
        raise RuntimeError('Controller preparation was not released')
    # This protocol has exactly one request. EOF also detects an accidental
    # extra command; after release no further authority comes from this pipe.
    if source.read(1):
        raise RuntimeError('Unexpected extra preparation command')
    return True


def revalidate(values, pins, *, load_values, read_pin, verify_package, verify_process, check_conflicts, verify_pair=None):
    if verify_process() is not True:
        raise RuntimeError('Prepared controller identity changed')
    check_conflicts()
    if load_values() != values:
        raise RuntimeError('Settings changed during controller preparation')
    for role in ('controller','receiver'):
        if read_pin(role) != pins[role]:
            raise RuntimeError('Code changed during controller preparation')
    valid = (verify_pair(pins) if verify_pair is not None else
             all(verify_package(role, pins[role]) is True for role in ('controller', 'receiver')))
    if valid is not True:
        raise RuntimeError('Code changed during controller preparation')
