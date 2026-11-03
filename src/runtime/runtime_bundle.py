"""Fixed paths and code attestation for two roles inside one installed package.

Legacy entrypoints never select a bundle. A bundled launcher selects its role
before importing runtime modules. Selection cannot change once inspected.
"""
import hashlib
import json
import re
from pathlib import Path

APP = 'org.magicsirimote.app'
SERVICE = APP + '.service'
ROOT = Path('/media/developer/apps/usr/palm/services') / SERVICE
PACKAGE = Path('/media/developer/apps/usr/palm/packages') / APP
_role = None
_frozen = False


def select(role):
    global _role
    if _frozen or _role is not None or role not in ('controller', 'receiver'):
        raise RuntimeError('Runtime role cannot be selected')
    _role = role


def active():
    global _frozen
    _frozen = True
    return _role is not None


def app_id(legacy):
    return APP if active() else legacy


def role_path(role, legacy):
    if role not in ('controller', 'receiver'):
        raise ValueError('Unknown runtime role')
    return ROOT / 'roles' / role if active() else Path(legacy)


def current_path(legacy):
    return ROOT / 'roles' / _role if active() else Path(legacy)


def package_path(legacy):
    return PACKAGE if active() else Path(legacy)


def validate_pin(pin, role):
    if (type(pin) is not dict or set(pin) != {'schema', 'appId', 'role', 'files', 'serviceInfoSha256'}
            or pin['schema'] != 'bundled-role-v1' or pin['appId'] != APP
            or role not in ('controller', 'receiver') or pin['role'] != role
            or type(pin['files']) is not dict or not 1 <= len(pin['files']) <= 200):
        raise ValueError('Invalid bundled role pin')
    if not {'services.json', 'package.json', 'roles/' + role + '/native_probe.py'} <= set(pin['files']):
        raise ValueError('Incomplete bundled role pin')
    for name, digest in pin['files'].items():
        if (type(name) is not str or not re.fullmatch(r'[A-Za-z0-9_./-]+', name)
                or any(p in ('', '.', '..') for p in name.split('/'))
                or type(digest) is not str or not re.fullmatch(r'[a-f0-9]{64}', digest)):
            raise ValueError('Invalid bundled file pin')
    if type(pin['serviceInfoSha256']) is not str or not re.fullmatch(r'[a-f0-9]{64}', pin['serviceInfoSha256']):
        raise ValueError('Invalid service metadata pin')
    return pin


def read_pin(role):
    from local_attestation import _read_file
    if not active():
        raise RuntimeError('Bundled role not selected')
    raw = _read_file(ROOT, 'pins/' + role + '.json', 32768)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate pin field')
            result[key] = value
        return result
    return validate_pin(json.loads(raw, object_pairs_hook=unique), role)


def package_matches(app_path, pkg_path, pin):
    """Verify installed service code and metadata within its filesystem jail."""
    from local_attestation import _directory, _read_file
    role = pin.get('role') if type(pin) is dict else None
    validate_pin(pin, role)
    role_dir = Path(app_path)
    root = role_dir.parent.parent
    if role_dir.name != role or role_dir.parent.name != 'roles' or root.name != SERVICE or Path(pkg_path).name != APP:
        return False
    _directory(root); _directory(root / 'roles'); _directory(role_dir)
    for name, digest in pin['files'].items():
        if hashlib.sha256(_read_file(root, name)).hexdigest() != digest:
            return False
    # The service jail cannot see usr/palm/packages. Its own package.json
    # and services.json are installed metadata, and both are pinned above.
    info_raw = _read_file(root, 'package.json')
    if hashlib.sha256(info_raw).hexdigest() != pin['serviceInfoSha256']:
        return False
    info = json.loads(info_raw)
    service = json.loads(_read_file(root, 'services.json'))
    return (info.get('name') == SERVICE
            and service.get('id') == SERVICE and service.get('services') == [{'name': SERVICE}])
