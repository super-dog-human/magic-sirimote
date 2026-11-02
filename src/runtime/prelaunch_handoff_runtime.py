"""Native controller/receiver integration; hardware acceptance still pending."""
import json, os, stat, time
from pathlib import Path
from input_start_handoff import InputStartHandoff, HandoffServer, HandoffClient
from borrowed_input_start import BorrowedInputStart
from receiver_process_observer import observe_live
from borrowed_gatt_view import BorrowedGattView,TARGET
from borrowed_gatt_requester import BorrowedGattRequester


def write_json_once(path, value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640)
    try:
        os.fchmod(fd,0o640)
        raw=(json.dumps(value,separators=(',',':'))+'\n').encode()
        with os.fdopen(fd,'wb',closefd=False) as stream:
            stream.write(raw);stream.flush();os.fsync(fd)
    finally:os.close(fd)
    d=os.open(Path(path).parent,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:os.fsync(d)
    finally:os.close(d)

class PrelaunchOwner:
    def __init__(self, cycle, controller_state, generation, lookup_reply=None):
        self.cycle=cycle;self.generation=generation;self.peer=None;self.server=None;self.journal_fd=None
        self.state=Path(controller_state)
        identity={k:cycle.controller_process[k] for k in ('pid','startTicks')}
        self.handoff=InputStartHandoff(run=cycle.run,controller=identity,generation=generation,
            connection_valid=self.valid,journal=self.record,send_input_start=self.start_input,launch_receiver=self.launch,connection_snapshot=cycle.watch.snapshot)
        try:
            self.journal_fd=os.open(self.state/('input-'+cycle.run+'.jsonl'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640)
            os.fchmod(self.journal_fd,0o640)
            self.server=HandoffServer(self.state/('h'+cycle.run[:16]),self.handoff,self.authorize)
            metadata={'run':cycle.run,'token':self.handoff.token,'controller':identity,'controllerUid':os.getuid()}
            if lookup_reply is not None:metadata['gattLookupReply']=lookup_reply
            write_json_once(self.state/('input-'+cycle.run+'.json'),metadata)
        except BaseException:
            self.close();raise

    def valid(self, generation):
        if self.cycle.lease.held() is not True:return False
        current=self.cycle.watch.snapshot()
        return type(current) is dict and current.get('generation')==generation

    def record(self,event):
        raw=(json.dumps(event,separators=(',',':'))+'\n').encode()
        with os.fdopen(os.dup(self.journal_fd),'ab') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        return True

    def start_input(self):
        # The supervisor lease and absence of a prior receiver serialize the
        # project's own start. This does not exclude unrelated TV software.
        client=BorrowedInputStart(pump=lambda:None,guard=lambda:self.valid(self.generation))
        return client.start()

    def launch(self, token):
        return self.cycle.launcher.launch('B',self.cycle.run)=='accepted'

    def authorize(self,pid,uid,gid):
        c=self.cycle
        if uid<=0 or gid!=5000:return False
        if self.peer is None:
            value=observe_live(receiver_state=c.receiver_state,run=c.run,app_path=c.receiver_app,
                pkg_path=c.receiver_package,pin=c.pin,allow_exe_permission_denied=c.allow_fallback)
            p=value['process'];uids=p['status']['Uid'].split()
            if p['pid']!=pid or uids!=[str(uid)]*4:return False
            self.peer=(pid,uid,gid,p['startTicks'])
        if self.peer[:3]!=(pid,uid,gid):return False
        # Detect PID reuse without hashing the package on every challenge.
        text=Path('/proc/'+str(pid)+'/stat').read_text()
        return int(text[text.rfind(')')+2:].split()[19])==self.peer[3]

    def begin(self):self.handoff.begin()

    def close(self):
        try:
            if self.server is not None:
                server,self.server=self.server,None;server.close()
        finally:
            if self.journal_fd is not None:
                os.close(self.journal_fd);self.journal_fd=None


def lookup_before_input(*,watch,lease,record,requester_factory=BorrowedGattRequester,
                        clock=time.monotonic,wait=time.sleep):
    """Obtain the client before binding any input proof to a generation.

    This TV emits GATT connecting/disconnected notifications even for a lookup
    of an already connected client. No input or sensor operation is allowed
    here. A fresh stable generation is required after the one lookup returns.
    The caller has reserved a durable launch intent and excluded a receiver.
    """
    def guard():return lease.held() is True and watch.is_open() is True
    initial=watch.snapshot()
    if not guard() or type(initial) is not dict:raise RuntimeError('lookup connection unavailable')
    record('intent',{'generation':initial['generation']})
    requester=requester_factory(pump=lambda:None,guard=guard)
    # During this connection operation only, generation changes are expected.
    # All subsequent Feature operations retain the original strict guards.
    try:
        reply=requester('gatt/connect',{'address':TARGET,'subscribe':False},timeout=12)
        BorrowedGattView(reply,generation=initial['generation'],control_valid=guard,discover=lambda _:None)
        if not guard():raise RuntimeError('lookup watch unavailable')
        record('reply',{'reply':reply,'ownership':'unproven'})
    except BaseException:
        record('unknown',{'ownership':'unproven'});raise
    completed=clock();deadline=completed+8;first=None
    while clock()<deadline:
        if not guard():raise RuntimeError('lookup watch unavailable')
        current=watch.snapshot()
        if type(current) is dict and current['observedAt']>completed:
            if first is not None and current['generation']==first['generation'] and current['observedAt']-first['observedAt']>=.5:
                record('stable',{'generation':current['generation']})
                return reply,current['generation']
            if first is None or current['generation']!=first['generation']:first=current
        else:first=None
        wait(.05)
    raise RuntimeError('lookup connection did not stabilize')


def receiver_client(controller_app, record):
    """Called only after existing live-controller/package authentication."""
    run=record['run'];process=record['process'];uid=int(process['status']['Uid'].split()[0])
    state=Path(controller_app)/'state';path=state/('input-'+run+'.json')
    f=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        before=os.fstat(f)
        if not stat.S_ISREG(before.st_mode) or before.st_uid!=uid or before.st_nlink!=1 or stat.S_IMODE(before.st_mode)!=0o640 or before.st_size>2048:raise RuntimeError('input handoff metadata invalid')
        raw=os.read(f,2049);after=os.fstat(f)
        if len(raw)!=before.st_size or (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError('input handoff changed')
    finally:os.close(f)
    value=json.loads(raw)
    identity={k:process[k] for k in ('pid','startTicks')}
    if type(value) is not dict or set(value)!={'run','token','controller','controllerUid','gattLookupReply'} or value['run']!=run or value['controller']!=identity or value['controllerUid']!=uid:raise RuntimeError('input handoff identity mismatch')
    # Validate target and client identity before passing the actual reply on.
    BorrowedGattView(value['gattLookupReply'],generation=1,control_valid=lambda:False,discover=lambda _:None)
    client=HandoffClient(path=str(state/('h'+run[:16])),run=run,token=value['token'],controller=identity,controller_uid=uid)
    client.gatt_lookup_reply=value['gattLookupReply']
    return client
