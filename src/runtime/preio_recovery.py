"""Retire a finished recovery that failed before any device command.

Keep the uncertain original session intact. A subsequent attempt must obtain
fresh connection information and independently read/stop the sensor.
"""
import os
import stat
import time
from pathlib import Path
from orphan_reconcile import _read, _identity, _ended
from recovery_lookup_handoff import validate_reply
from receiver_result_receipt import APP
from receiver_request_auth import CONTROLLER


def retire(*, run, controller_state, receiver_state, controller_app,
           receiver_app, proof, prior, state_uid=5999, group=5000,
           now_ms=None, native_idle=None):
    if native_idle is None:
        from control_processes import processes
        native_idle = lambda: not processes()['ui']
    now = (lambda: int(time.time()*1000)) if now_ms is None else lambda: now_ms
    owner = os.getuid()
    receiver_uid = int(prior['process']['status']['Uid'].split()[0])
    if receiver_uid <= 0 or prior['process']['status']['Uid'].split() != [str(receiver_uid)]*4:
        raise RuntimeError('invalid prior receiver owner')
    c = os.open(controller_state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    b = os.open(receiver_state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    pending = 'recovery-preio-pending-' + run
    archive = None
    try:
        for fd in (c, b):
            s = os.fstat(fd)
            if s.st_uid != state_uid or s.st_gid != group or stat.S_IMODE(s.st_mode) not in (0o770, 0o775):
                raise RuntimeError('unsafe recovery archive directory')
        try:
            archive = os.open(pending, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=b)
        except FileNotFoundError:
            pass
        if archive is not None:
            s = os.fstat(archive)
            if s.st_uid != owner or s.st_gid != group or stat.S_IMODE(s.st_mode) != 0o750:
                raise RuntimeError('unsafe preio archive')
        rows = []
        def row(fd, prefix, name, mode, optional=False, expected_owner=None):
            dest = prefix + name
            live = name in os.listdir(fd)
            saved = archive is not None and dest in os.listdir(archive)
            if live and saved:
                raise RuntimeError('duplicate preio evidence')
            if not live and not saved:
                if optional: return None
                raise RuntimeError('preio evidence missing')
            origin, source = (fd, name) if live else (archive, dest)
            value, info = _read(origin, source, owner if expected_owner is None else expected_owner, group, mode, historical=True)
            rows.append([origin, source, dest, info, value])
            return value
        start = row(b, 'b-', 'receiver-recovery-start-'+run+'.json', 0o640, expected_owner=receiver_uid)
        result = row(b, 'b-', 'receiver-recovery-result-'+run+'.json', 0o640, expected_owner=receiver_uid)
        if (set(start) != {'schema','appId','run','stage','process','rawReportsPersisted'}
                or start.get('schema') != 1 or start.get('appId') != APP or start.get('run') != run
                or start.get('stage') != 'starting' or start.get('rawReportsPersisted') is not False):
            raise RuntimeError('invalid preio start')
        process = start['process']
        if (type(process) is not dict or set(process) != {'pid','startTicks','status'}
                or type(process.get('status')) is not dict
                or process['status'].get('Uid','').split() != [str(receiver_uid)]*4
                or process['status'].get('CapEff') != '0000000000000000'):
            raise RuntimeError('invalid preio process')
        if (set(result) != {'schema','appId','run','status','diagnostic','frameCounts','readStats','phase','previousPhase','failureType','sensorStopVerified','journalArchived','featureExclusivity','counts','process','rawReportsPersisted'}
                or result.get('schema') != 1 or result.get('appId') != APP or result.get('run') != run
                or result.get('status') != 'attention' or result.get('process') != process
                or any(result.get(k) is not False for k in ('sensorStopVerified','journalArchived','rawReportsPersisted'))
                or any(result.get(k) is not None for k in ('phase','previousPhase','frameCounts','readStats','counts'))):
            raise RuntimeError('preio failure unconfirmed')
        intent = row(b, 'b-', 'recovery-'+run+'-1.json', 0o640, expected_owner=receiver_uid)
        if (set(intent) != {'run','stage','priorSensorState','priorOutcome'}
                or intent.get('run') != run or intent.get('stage') != 'recovery-intent'
                or intent.get('priorSensorState') != 'uncertain'
                or intent.get('priorOutcome') != prior['priorOutcome']):
            raise RuntimeError('preio intent differs')
        request = row(b, 'b-', 'recovery-request.json', 0o660)
        if (set(request) != {'schema','appId','run','expiresEpochMs','priorProcess','gattLookupReply'}
                or request.get('schema') != 2 or request.get('appId') != APP or request.get('run') != run
                or request.get('priorProcess') != prior['process']
                or type(request.get('expiresEpochMs')) is not int or request['expiresEpochMs'] >= now()):
            raise RuntimeError('preio request invalid or unexpired')
        validate_reply(request['gattLookupReply'])
        for kind in ('intent','reply','stable'):
            value = row(c, 'c-', 'recovery-gatt-'+run+'-'+kind+'.json', 0o640)
            if kind == 'reply':
                if value != {'run':run,'reply':request['gattLookupReply'],'ownership':'unproven'}:
                    raise RuntimeError('preio lookup differs')
            elif set(value) != {'run','generation'} or value.get('run') != run or type(value.get('generation')) is not int or value['generation'] < 1:
                raise RuntimeError('invalid preio generation')
        takeover = row(b, 'b-', 'recovery-controller-start.json', 0o660, optional=True)
        controller = takeover or row(b, 'b-', 'controller-start.json', 0o660)
        # The original controller record is checked, but must never be moved.
        if takeover is None: rows.pop()
        if (set(controller) != {'schema','appId','run','process'} or controller.get('schema') != 1
                or controller.get('appId') != CONTROLLER or controller.get('run') != run or type(controller.get('process')) is not dict
                or controller['process'].get('status',{}).get('Uid','').split() != [str(owner)]*4):
            raise RuntimeError('invalid preio controller')
        allowed = {r[2] for r in rows}
        def valid():
            names = os.listdir(b)
            if any(n.startswith('recovery-'+run+'-') and n != 'recovery-'+run+'-1.json' for n in names): return False
            if 'recovery-active' in names or 'recovery-gatt-'+run+'-unknown.json' in os.listdir(c): return False
            if archive is not None and any(n not in allowed for n in os.listdir(archive)): return False
            if (proof() is not True or native_idle() is not True
                    or not _ended(process, receiver_app)
                    or not _ended(controller['process'], controller_app, ignore_current=True)
                    or request['expiresEpochMs'] >= now()): return False
            for origin, source, dest, info, value in rows:
                if _identity(os.stat(source, dir_fd=origin, follow_symlinks=False)) != _identity(info): return False
                original_fd = b if dest.startswith('b-') else c
                if origin == archive and dest[2:] in os.listdir(original_fd): return False
            return True
        if not valid(): raise RuntimeError('preio retirement proof unavailable')
        if archive is None:
            os.mkdir(pending, 0o750, dir_fd=b)
            archive = os.open(pending, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=b)
            os.fchmod(archive, 0o750); os.fsync(b)
        # Keep the request until last: every interrupted archive still blocks a
        # new dispatch and can be resumed from the retained original bytes.
        rows.sort(key=lambda r: r[2] == 'b-recovery-request.json')
        for index, (origin, source, dest, info, value) in enumerate(rows):
            if not valid(): raise RuntimeError('preio retirement proof changed')
            if origin != archive:
                os.rename(source, dest, src_dir_fd=origin, dst_dir_fd=archive)
                os.fsync(origin); os.fsync(archive)
                rows[index] = [archive,dest,dest,os.stat(dest,dir_fd=archive,follow_symlinks=False),value]
        if not valid(): raise RuntimeError('preio retirement proof changed')
        dest = 'recovery-preio-retired-'+run+'-'+str(process['pid'])+'-'+str(process['startTicks'])
        if dest in os.listdir(b): raise RuntimeError('preio archive exists')
        os.rename(pending, dest, src_dir_fd=b, dst_dir_fd=b); os.fsync(b)
        return True
    finally:
        if archive is not None: os.close(archive)
        os.close(b); os.close(c)
