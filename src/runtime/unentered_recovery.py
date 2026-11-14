"""Retire an expired recovery dispatch that never reached sensor I/O.

The original uncertain sensor journal remains for the ordinary recovery path.
A recovery-controller record is the last archived file, so an interrupted
archive resumes using the same process-bound destination names.
"""
import state_permissions
import os
import stat
import time
from pathlib import Path
from orphan_reconcile import _read, _identity, _ended
from controller_start_record import read_record
from recovery_lookup_handoff import validate_reply
from receiver_result_receipt import APP


def retire(*, run, controller_state, receiver_state, controller_app,
           receiver_app, proof, prior, state_uid=5999, group=5000,
           now_ms=None, native_idle=None):
    """Return False if there is no takeover record; otherwise prove and archive."""
    if native_idle is None:
        from control_processes import processes
        native_idle = lambda: not processes()['ui']
    clock = (lambda: int(time.time() * 1000)) if now_ms is None else lambda: now_ms
    owner = os.getuid()
    try:
        record = read_record(receiver_state, run, name='recovery-controller-start.json',
                             state_uid=state_uid, group=group, historical=True)
    except FileNotFoundError:
        return False
    process = record['process']
    if (process['pid'] == os.getpid() or
            process['status'].get('Uid', '').split() != [str(owner)] * 4 or
            process['status'].get('CapEff') != '0000000000000000'):
        raise RuntimeError('unentered recovery controller invalid')
    suffix = '-unentered-' + run + '-' + str(process['pid']) + '-' + str(process['startTicks']) + '.json'
    c = os.open(controller_state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    b = os.open(receiver_state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for fd in (c, b):
            info = os.fstat(fd)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != state_uid or
                    info.st_gid != group or stat.S_IMODE(info.st_mode) not in state_permissions.directory_modes()):
                raise RuntimeError('unsafe recovery archive directory')

        def absent():
            names = os.listdir(b)
            return not any(n == 'recovery-active' or n.startswith((
                'receiver-recovery-start-' + run, 'receiver-recovery-result-' + run,
                'recovery-' + run + '-')) for n in names)

        def eligible():
            return (proof() is True and absent() and native_idle() is True and
                    _ended(process, controller_app, ignore_current=True) and
                    _ended(prior['process'], receiver_app))

        if not absent():
            raise RuntimeError('recovery entry already recorded')
        if not eligible():
            raise RuntimeError('unentered recovery proof unavailable')
        rows = []

        def row(fd, name, mode):
            dest = name[:-5] + suffix
            names = os.listdir(fd)
            if name in names and dest in names:
                raise RuntimeError('duplicate recovery archive')
            source = name if name in names else dest
            value, info = _read(fd, source, owner, group, mode, historical=True)
            if value.get('run') != run:
                raise RuntimeError('unentered recovery run differs')
            rows.append([fd, source, dest, info])
            return value

        request = row(b, 'recovery-request.json', 0o660)
        if (set(request) != {'schema', 'appId', 'run', 'expiresEpochMs', 'priorProcess', 'gattLookupReply'} or
                type(request['schema']) is not int or request['schema'] != 2 or request['appId'] != APP or
                request['priorProcess'] != prior['process'] or type(request['expiresEpochMs']) is not int or
                request['expiresEpochMs'] <= 0 or type(clock()) is not int):
            raise RuntimeError('unentered recovery request invalid')
        if request['expiresEpochMs'] >= clock():
            raise RuntimeError('unentered recovery request not expired')
        validate_reply(request['gattLookupReply'])
        for kind in ('intent', 'reply', 'stable'):
            value = row(c, 'recovery-gatt-' + run + '-' + kind + '.json', 0o640)
            if kind == 'reply':
                if (set(value) != {'run', 'reply', 'ownership'} or value['ownership'] != 'unproven' or
                        value['reply'] != request['gattLookupReply']):
                    raise RuntimeError('unentered recovery lookup differs')
            elif set(value) != {'run', 'generation'} or type(value['generation']) is not int or value['generation'] < 1:
                raise RuntimeError('unentered recovery generation invalid')
        if 'recovery-gatt-' + run + '-unknown.json' in os.listdir(c):
            raise RuntimeError('unentered recovery lookup uncertain')
        anchor = row(b, 'recovery-controller-start.json', 0o660)
        if anchor != record or rows[-1][1] != 'recovery-controller-start.json':
            raise RuntimeError('unentered recovery anchor changed')
        # All evidence is validated before any rename. No sensor state is inferred.
        for index, (fd, source, dest, info) in enumerate(rows):
            if not eligible() or request['expiresEpochMs'] >= clock():
                raise RuntimeError('unentered recovery proof changed')
            for other_fd, other_source, _, other_info in rows:
                if _identity(os.stat(other_source, dir_fd=other_fd, follow_symlinks=False)) != _identity(other_info):
                    raise RuntimeError('unentered recovery evidence changed')
            if source != dest:
                if dest in os.listdir(fd):
                    raise RuntimeError('duplicate recovery archive')
                os.rename(source, dest, src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
                after = os.stat(dest, dir_fd=fd, follow_symlinks=False)
                if (after.st_dev, after.st_ino, after.st_size) != (info.st_dev, info.st_ino, info.st_size):
                    raise RuntimeError('unentered recovery archive changed')
                rows[index] = [fd, dest, dest, after]
        return True
    finally:
        os.close(b)
        os.close(c)
