"""TV-local input-start handoff over an authenticated Unix socket.

The controller owns the connection watcher and initializes input BEFORE launching
its receiver. Each receiver query checks that SAME watcher; receiver-local
connection generations are never compared with controller-local generations.

Integration must authorize_peer against the pinned receiver process and keep the
server alive until the receiving session ends. This does not prove physical radio
continuity beyond the Bluetooth watcher's observations. No Bluetooth operations,
app launches, or installations occur in this module.
"""
import json, os, secrets, socket, stat, struct, threading

LIMIT = 2048

def _send(sock, value):
    raw = json.dumps(value, separators=(',', ':')).encode() + b'\n'
    if len(raw) > LIMIT:
        raise ValueError('handoff message too large')
    sock.sendall(raw)

def _receive(sock):
    raw = bytearray()
    while len(raw) < LIMIT:
        part = sock.recv(1)
        if not part:
            raise RuntimeError('handoff connection closed')
        raw.extend(part)
        if part == b'\n':
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError('duplicate handoff key')
                    result[key] = value
                return result
            return json.loads(raw, object_pairs_hook=unique)
    raise ValueError('handoff message too large')

class InputStartHandoff:
    def __init__(self, *, run, controller, generation, connection_valid,
                 journal, send_input_start, launch_receiver, connection_snapshot=None):
        if not isinstance(run, str) or len(run) != 32 or any(c not in '0123456789abcdef' for c in run):
            raise ValueError('invalid run')
        if (set(controller) != {'pid', 'startTicks'} or
                any(type(v) is not int or v <= 0 for v in controller.values()) or
                type(generation) is not int or generation < 1):
            raise ValueError('invalid controller identity')
        self.run, self.controller, self.generation = run, dict(controller), generation
        self.valid, self.journal = connection_valid, journal
        if connection_snapshot is not None and not callable(connection_snapshot):raise ValueError("invalid observation provider")
        self.connection_snapshot=connection_snapshot
        self.send, self.launch = send_input_start, launch_receiver
        self.token = secrets.token_hex(16)
        self.started = self.acknowledged = self.revoked = False
        self.receiver_pid = None
        self.lock = threading.RLock()

    def _check(self):
        # Once invalidated, reconnection can never revive this handoff.
        try:
            valid = not self.revoked and self.valid(self.generation) is True
        except BaseException:
            self.revoked = True
            raise
        if not valid:
            self.revoked = True
            raise RuntimeError('input-start connection revoked')

    def _record(self, stage):
        if self.journal({'stage':stage, 'run':self.run,
                         'controller':self.controller, 'controllerGeneration':self.generation}) is not True:
            raise RuntimeError('handoff journal unavailable')

    def begin(self):
        with self.lock:
            if self.started:
                raise RuntimeError('input start already attempted')
            self.started = True
        try:
            with self.lock:
                self._check()
                self._record('input-intent')
                if self.send() is not True:
                    raise RuntimeError('input start unconfirmed')
                self._check()
                self._record('input-ack')
                self.acknowledged = True
                self._record('receiver-launch-intent')
                self._check()
            # The launched receiver can query us before launch() returns its ACK.
            # Holding the validation lock across launch would deadlock that query.
            if self.launch(self.token) is not True:
                raise RuntimeError('receiver launch unconfirmed')
            with self.lock:
                self._check()
                self._record('receiver-launch-ack')
        except BaseException:
            with self.lock:
                self.revoked = True
            raise

    def validate(self, request, peer_pid):
        with self.lock:
            if not self.acknowledged:
                raise RuntimeError('input start not acknowledged')
            if type(request) is not dict or set(request) not in ({'run','token','challenge'}, {'run','token','challenge','operation'}) or ('operation' in request and request['operation']!='observe'):
                raise ValueError('invalid handoff request')
            if request['run'] != self.run or request['token'] != self.token:
                raise RuntimeError('wrong handoff session')
            challenge = request['challenge']
            if not isinstance(challenge, str) or len(challenge) != 32 or any(c not in '0123456789abcdef' for c in challenge):
                raise ValueError('invalid challenge')
            self._check()
            if self.receiver_pid is None:
                self.receiver_pid = peer_pid
            if self.receiver_pid != peer_pid:
                raise RuntimeError('handoff already bound to another receiver')
            reply={'run':self.run, 'challenge':challenge,
                   'controller':self.controller, 'inputStarted':True}
            if request.get('operation')=='observe':
                from controller_status_watch import select_observation
                if self.connection_snapshot is None:raise RuntimeError('observation unavailable')
                observation=select_observation(self.connection_snapshot())
                if observation['generation']!=self.generation:raise RuntimeError('observation generation changed')
                self._check()
                reply['observation']=observation
            return reply

class HandoffServer:
    """One bounded request per connection, kernel-provided peer credentials."""
    def __init__(self, path, handoff, authorize_peer):
        self.path, self.handoff, self.authorize = os.fspath(path), handoff, authorize_peer
        if len(os.fsencode(self.path)) >= 108:
            raise ValueError('Unix socket path too long')
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.stop = threading.Event()
        self.inode = None
        self.closed = False
        try:
            # Never unlink an old socket: its owner may still be running.
            self.socket.bind(self.path)
            self.inode = os.lstat(self.path).st_ino
            os.chmod(self.path, 0o660)
            self.socket.listen(4)
            self.socket.settimeout(.1)
        except BaseException:
            self.socket.close()
            self._unlink_owned()
            raise
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(.5)
                try:
                    pid, uid, gid = struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if self.authorize(pid, uid, gid) is not True:
                        raise RuntimeError('receiver identity rejected')
                    result = self.handoff.validate(_receive(conn), pid)
                    _send(conn, result)
                except (OSError, ValueError, RuntimeError):
                    # Closing without a positive reply is a denied handoff.
                    pass

    def _unlink_owned(self):
        if self.inode is None:return
        try:s = os.lstat(self.path)
        except FileNotFoundError:return
        if not stat.S_ISSOCK(s.st_mode) or s.st_ino != self.inode:
            raise RuntimeError("handoff socket changed")
        os.unlink(self.path)

    def close(self):
        if self.closed:return
        self.handoff.revoked = True
        self.stop.set()
        self.socket.close()
        self.thread.join(1)
        if self.thread.is_alive():
            raise RuntimeError('handoff server did not stop')
        self._unlink_owned()
        self.closed = True

class HandoffClient:
    def __init__(self, *, path, run, token, controller, controller_uid):
        self.path, self.run, self.token = path, run, token
        self.controller, self.uid = dict(controller), controller_uid
        self.authenticated = False

    def _request(self, observe=False):
        challenge = secrets.token_hex(16)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                # The first peer authorization hashes the installed package.
                # Cold storage can exceed 0.5 s; steady-state checks stay short.
                sock.settimeout(.5 if self.authenticated else 3)
                sock.connect(self.path)
                pid, uid, _ = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if pid != self.controller['pid'] or uid != self.uid:
                    return None
                request={'run':self.run, 'token':self.token, 'challenge':challenge}
                if observe:request['operation']='observe'
                _send(sock,request)
                response = _receive(sock)
                expected={'run':self.run, 'challenge':challenge,
                          'controller':self.controller, 'inputStarted':True}
                if observe:
                    if type(response) is not dict or set(response)!=set(expected)|{'observation'}:return None
                    if {key:response[key] for key in expected}!=expected:return None
                    from controller_status_watch import select_observation
                    value = select_observation(response['observation'])
                    self.authenticated = True
                    return value
                if response != expected: return None
                self.authenticated = True
                return expected
        except (OSError, ValueError, RuntimeError, TypeError, KeyError):
            return None

    def check(self):return self._request() is not None
    def observe(self):return self._request(observe=True)
