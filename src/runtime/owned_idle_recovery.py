"""Retain an idle receiver for one reconnect cleanup, without enabling input.

The worker closes its input/output resources before entering this path. The
controller still verifies process exit before archiving or launching a receiver.
A crash or unconfirmed cleanup leaves the active journal for external recovery.
"""
import math
import os
import secrets
import time
from receive_diagnostics import diagnostic_result
from recovery_lookup_handoff import validate_reply


def eligible(result):
    source, cleanup = diagnostic_result(result)
    if cleanup or type(source) is not dict or source.get('status') != 'attention':
        return False
    if source.get('previousPhase') != 'receive' or source.get('phase') != 'stop':
        return False
    stats = source.get('readStats')
    if type(stats) is not dict:
        return False
    diagnostic = stats.get('receiveDiagnostics')
    if type(diagnostic) is not dict:
        return False
    failure = diagnostic.get('receiveFailure')
    if type(failure) is dict:
        return (failure.get('stage') == 'read'
                and failure.get('type') == 'OSError' and failure.get('errno') == 5)
    # The connection observer can report idle before read() returns EIO.
    # Admit that ordering only; stale status, lost ownership and policy errors
    # still leave the journal for external recovery. Waiting itself requires
    # live ownership, and resumption still needs a new generation and zero proof.
    return ('receiveFailure' not in diagnostic and stats.get('aborted') is True
            and diagnostic.get('endReason') == 'control-or-policy-ended'
            and diagnostic.get('receiverStopReason') == 'control-lost'
            and diagnostic.get('controlFailure') == 'snapshot'
            and diagnostic.get('watchState') == 'missing')



def validate_receipt(result):
    value = result.get('localRecovery')
    if (result.get('status') != 'attention' or result.get('sensorStopVerified') is not True
            or result.get('journalArchived') is True or result.get('cleanupDiagnostics')
            or type(value) is not dict
            or set(value) != {'generation', 'observedAt', 'gattLookupReply'}
            or type(value['generation']) is not int or value['generation'] < 1
            or type(value['observedAt']) not in (int, float)
            or not math.isfinite(value['observedAt']) or value['observedAt'] < 0):
        raise ValueError('invalid local recovery receipt')
    validate_reply(value['gattLookupReply'])
    return value


def wait_and_recover(*, result, state_path, run, watch, lease, initial_generation,
                     stop, external_feature_guard, clock=time.monotonic,
                     lookup=None, recover=None, records_factory=None, paired_check=None):
    if not eligible(result):
        return result
    from prelaunch_handoff_runtime import lookup_before_input
    from borrowed_recovery_runtime import recover_owned_zero
    from recovery_records import RecoveryRecords
    from postconnect_receiver_device import paired_target
    lookup = lookup or lookup_before_input
    recover = recover or recover_owned_zero
    records_factory = records_factory or RecoveryRecords
    paired_check = paired_check or paired_target
    records = None

    def valid_owner():
        return (not stop.is_set() and watch.is_open() is True
                and lease.held() is True and external_feature_guard() is True)

    class GuardedLease:
        def held(self):
            return valid_owner()

    try:
        if watch.mark_idle() is not True:
            return result
        while valid_owner():
            current = watch.snapshot()
            if type(current) is dict and current.get('generation', 0) > initial_generation:
                break
            stop.wait(.1)
        else:
            return result
        # A distinct attempt retains the normal external recovery latch if this
        # worker fails. No sensor-enable operation is available on this path.
        records = records_factory(state_path, secrets.token_hex(16))
        records({'stage': 'owned-recovery-intent', 'priorRun': run})
        # eligible() admits only a closed input session; valid_owner() and
        # the new generation above remain required. No old request is replayed.
        from pumping_luna_client import renew_failed_native_requests_after_idle
        if renew_failed_native_requests_after_idle():
            records({'stage':'owned-transport-renewed','priorRun':run})
        if not valid_owner():return result
        def record(stage, value):
            records({'stage': 'owned-lookup-' + stage, **value})
        from borrowed_gatt_requester import revalidate_client
        reply,generation=lookup(watch=watch,lease=GuardedLease(),record=record,
                                wait=stop.wait,verify_ready=revalidate_client)
        validate_reply(reply)
        proof = recover(watch=watch, lease=lease, generation=generation,
                        paired_check=paired_check, external_feature_guard=valid_owner,
                        record=records, session_closed=lambda: eligible(result),
                        gatt_lookup_reply=reply)
        current = watch.snapshot()
        if (proof.get('status') != 'recovered' or proof.get('modeZeroVerified') is not True
                or proof.get('priorSessionClosedVerified') is not True or not valid_owner()
                or type(current) is not dict or current.get('generation') != generation):
            return result
        records({**proof, 'stage': 'owned-recovery-zero-confirmed', 'priorRun': run})
        return {**result, 'sensorStopVerified': True, 'journalArchived': False,
                'localRecovery': {'generation': generation, 'observedAt': clock(),
                                  'gattLookupReply': reply}}
    except Exception:
        return result
    finally:
        if records is not None:
            records.close()


def recover_missing_target(*, result, prior_recovery, state_path, run, watch, lease,
                           stop, external_feature_guard, clock=time.monotonic,
                           recover=None, records_factory=None, paired_check=None):
    """Confirm zero before exiting a resumed worker whose device node is absent.

    Reuse only the fresh connection lookup from this worker's preceding idle
    recovery. Never reuse its old zero proof: input initialization has run since.
    The controller must still verify exit before launching a fresh app.
    """
    source, cleanup = diagnostic_result(result)
    if (cleanup or type(source) is not dict or source is not result or result.get('status') != 'attention'
            or result.get('diagnostic') != 'target-not-present'
            or result.get('setupStage') != 'open-target'
            or result.get('resourcesClosed') is not True):
        return result
    from borrowed_recovery_runtime import recover_owned_zero
    from recovery_records import RecoveryRecords
    from postconnect_receiver_device import paired_target
    recover = recover or recover_owned_zero
    records_factory = records_factory or RecoveryRecords
    paired_check = paired_check or paired_target
    records = None
    try:
        prior = validate_receipt(prior_recovery)
        generation = prior['generation']
        def owner():
            current = watch.snapshot()
            return (not stop.is_set() and watch.is_open() is True
                    and lease.held() is True and external_feature_guard() is True
                    and type(current) is dict and current.get('generation') == generation)
        if not owner() or not 0 <= clock() - prior['observedAt'] <= 5:
            return result
        records = records_factory(state_path, secrets.token_hex(16))
        if records({'stage': 'owned-recovery-intent', 'priorRun': run}) is not True:
            return result
        proof = recover(watch=watch, lease=lease, generation=generation,
                        paired_check=paired_check, external_feature_guard=owner,
                        record=records, session_closed=lambda: result.get('resourcesClosed') is True,
                        gatt_lookup_reply=prior['gattLookupReply'])
        if (proof.get('status') != 'recovered' or proof.get('modeZeroVerified') is not True
                or proof.get('priorSessionClosedVerified') is not True or not owner()):
            return result
        if records({**proof, 'stage': 'owned-recovery-zero-confirmed', 'priorRun': run}) is not True:
            return result
        return {**result, 'sensorStopVerified': True, 'journalArchived': False,
                'localRecovery': {'generation': generation, 'observedAt': clock(),
                                  'gattLookupReply': prior['gattLookupReply']}}
    except Exception:
        return result
    finally:
        if records is not None:
            records.close()


def accept_recovery(cycle, *, clock=time.monotonic):
    """Consume a fresh cleanup receipt only after the original worker exits."""
    from receiver_result_reader import read_receipt
    from receiver_process_observer import observed_process_ended
    from recovery_records import archive_uncertain
    from receiver_handoff_archive import archive
    import receiver_package_attestation as package
    try:
        receipt = read_receipt(cycle.receiver_state, cycle.run)
    except FileNotFoundError:
        return None
    if 'localRecovery' not in receipt:
        return None
    value = validate_receipt(receipt)
    def proof():
        current = cycle.watch.snapshot()
        return (receipt['process'] == cycle.live['process']
                and cycle.lease.held() is True and cycle.watch.is_open() is True
                and 0 <= clock() - value['observedAt'] <= 5
                and type(current) is dict and current.get('generation') == value['generation']
                and observed_process_ended(cycle.live, app_path=cycle.receiver_app) is True
                and package.package_matches(cycle.receiver_app, cycle.receiver_package, cycle.pin) is True)
    if not proof():
        return None
    owner = int(receipt['process']['status']['Uid'].split()[0])
    if archive_uncertain(cycle.receiver_state, cycle.run, owner_uid=owner, proof=proof) is not True:
        raise RuntimeError('owned recovery archive unconfirmed')
    result = {'run': cycle.run, 'status': 'recovered', 'modeZeroVerified': True,
              'oldReceiverExitVerified': True, 'journalArchived': True,
              'generation': value['generation'], 'priorReceiptStatus': 'attention'}
    if archive(cycle.receiver_state, cycle.run, owner_uid=os.getuid()) is not True:
        raise RuntimeError('owned recovery handoff archive failed')
    if cycle.intent.archive_recovered(result, independent_proof=proof) is not True:
        raise RuntimeError('owned recovery launch archive failed')
    if cycle.lookup_cache is not None:
        cycle.lookup_cache.remember(value['gattLookupReply'], watch=cycle.watch,
                                    lease=cycle.lease, generation=value['generation'])
    cycle.finished = True
    return {**result, 'launchIntentArchived': True}
