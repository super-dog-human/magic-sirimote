"""Single-use LS2 entry point. No listener or persistent root installation."""
import json
import os
from pathlib import Path
import signal
import time


def execute(base, run):
    base = Path(base)
    # Use the TV's own clock and staged file time, not the Mac's wall clock.
    age = time.time() - (base / 'runner.py').stat().st_mtime
    if not 0 <= age <= 25:
        raise RuntimeError('Temporary service expired')
    fd = os.open(base / 'claimed', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    boot = Path('/proc/sys/kernel/random/boot_id')
    before = boot.read_text().strip()
    report = {'run': run, 'rootUid': os.geteuid()}

    def timeout(*_):
        raise TimeoutError('Temporary maintenance timed out')

    signal.signal(signal.SIGALRM, timeout)
    # Finish before the page's independent 65-second cleanup, including a slow
    # service launch. A late activation must never extend root execution.
    signal.alarm(max(1, int(55 - age)))
    try:
        if os.geteuid() != 0:
            raise RuntimeError('Temporary root is unavailable on this TV')
        scope = {'__name__': 'sirimote_maintenance'}
        exec(compile((base / 'operation.py').read_text(), str(base / 'operation.py'), 'exec'), scope)
        report['result'] = scope['result']
    except Exception as error:
        detail = (getattr(error, 'stderr', '') or getattr(error, 'stdout', '') or '')[-900:]
        report['error'] = str(error) + ' ' + detail
    finally:
        signal.alarm(0)
        report['sameBoot'] = boot.read_text().strip() == before
        fd = os.open(base / 'report.pending', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, 'w') as out:
            os.fchmod(out.fileno(), 0o644)
            json.dump(report, out)
        os.link(base / 'report.pending', base / 'report.json')
        (base / 'report.pending').unlink()
