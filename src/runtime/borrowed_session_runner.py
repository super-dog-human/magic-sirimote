"""Finite borrowed-sensor runner; composition, not a TV service.

The caller owns the watcher, lease and durable journal and must stop/inspect
those resources independently. This runner never reconnects or retries.
"""

def run_once(prepare, receive, *, classify=lambda _:None, before_stop=None):
    if not callable(prepare) or not callable(receive) or not callable(classify):
        raise ValueError('callable dependencies required')
    if before_stop is not None and not callable(before_stop):raise ValueError('invalid stop callback')
    def safe_classify(exc):
        # Diagnostics must never prevent a potentially enabled sensor stopping.
        try:
            return classify(exc)
        except BaseException:
            return None
    try:
        session = prepare()
    except Exception as exc:
        # Preserve only caller-classified fixed diagnostic data.
        return {'status': 'attention', 'phase': 'prepare', 'sensorStopVerified': False, 'diagnostic': safe_classify(exc)}
    phase = 'start'
    failure = None
    diagnostic = None
    try:
        ready = session.start()
        if type(ready) is not dict or ready.get('status') != 'active':
            raise RuntimeError('sensor start unconfirmed')
        phase = 'receive'
        received = receive(session)
        if type(received) is not dict or received.get('status') != 'complete':
            raise RuntimeError('receive unconfirmed')
    except BaseException as exc:
        failure = type(exc).__name__
        if isinstance(exc,Exception):diagnostic=safe_classify(exc)
    if before_stop is not None:
        try:
            before_stop()
        except BaseException as exc:
            failure = type(exc).__name__
            diagnostic = safe_classify(exc)
    try:
        stop = session.stop()
    except Exception:
        return {'status': 'attention', 'phase': 'stop', 'sensorStopVerified': False, 'previousPhase': phase, 'errorType': failure, 'diagnostic': diagnostic}
    if (type(stop) is not dict or stop.get('status') != 'stopped'
            or stop.get('modeZeroVerified') is not True
            or stop.get('gattDisconnectCalls') != 0
            or stop.get('clientOwnership') != 'unproven'):
        return {'status': 'attention', 'phase': 'stop', 'sensorStopVerified': False, 'previousPhase': phase, 'errorType': failure, 'diagnostic': diagnostic}
    if failure is not None:
        return {'status': 'attention', 'phase': phase, 'sensorStopVerified': True,
                'errorType': failure, 'diagnostic': diagnostic}
    summary={k:received[k] for k in ('bytesReceived','rotations','motionGateOpened','endReason') if k in received}
    return {'status': 'complete', 'sensorStopVerified': True,'receiveSummary':summary}
