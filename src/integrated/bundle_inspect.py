"""Inspect the installed bundle from the service jail, without device calls."""
import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'runtime'))
import runtime_bundle as bundle


def main():
    bundle.select('controller')
    result = {'schema': 1, 'uid': os.getuid(), 'gid': os.getgid(),
              'rolesVerified': {}, 'runtimeActivationAvailable': False,
              'bluetoothCalls': 0, 'inputEventsWritten': 0}
    for role in ('controller', 'receiver'):
        try:
            result['rolesVerified'][role] = bundle.package_matches(
                bundle.role_path(role, ''), bundle.PACKAGE, bundle.read_pin(role))
        except (OSError, RuntimeError, ValueError) as error:
            result['rolesVerified'][role] = False
            result[role + 'Error'] = type(error).__name__
            if isinstance(error, FileNotFoundError):
                result[role + 'MissingPath'] = str(error.filename)
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    main()
