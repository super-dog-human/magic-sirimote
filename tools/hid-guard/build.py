#!/usr/bin/env python3
"""Build optional guard and isolated test binaries. Never contacts a TV."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig', default='zig', help='Zig 0.13.0 executable')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if subprocess.check_output([args.zig, 'version'], text=True).strip() != '0.13.0':
        raise SystemExit('Use the reviewed Zig 0.13.0 toolchain')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(out/'zig-global'),
               ZIG_LOCAL_CACHE_DIR=str(out/'zig-local'))
    base = [args.zig, 'cc', '-target', 'arm-linux-gnueabi.2.17', '-mcpu=cortex_a9',
            '-O2', '-Wall', '-Wextra', '-Werror', '-s', '-Wl,--gc-sections']
    builds = [
        ('sirimote_hid_guard.c', 'libsirimote-hid-guard.so',
         ['-fPIC', '-shared', '-Wl,-z,relro,-z,now', '-Wl,--version-script=exports.map',
          '-Wl,-soname,libsirimote-hid-guard.so', '-ldl']),
        ('test_guard.c', 'test_guard_arm', ['-UNDEBUG', '-fPIC', '-pie', '-Wl,--version-script=test_exports.map']),
        ('guard_probe.c', 'guard_probe_arm', ['-fPIC', '-pie', '-ldl', '-Wl,--version-script=test_exports.map']),
        ('fake_hid_backend.c', 'fake_hid_backend.so',
         ['-UNDEBUG', '-fPIC', '-shared', '-Wl,--version-script=fake_exports.map']),
        ('elf_interposition_test.c', 'elf_interposition_test_arm', ['-UNDEBUG', '-fPIC', '-pie', '-ldl']),
    ]
    for source, name, flags in builds:
        subprocess.run(base+flags+[source, '-o', str(out/name)], cwd=HERE, env=env, check=True)
    subprocess.run([os.environ.get('CC', 'clang'), '-O2', '-UNDEBUG', '-Wall', '-Wextra',
                    '-Werror', 'test_guard.c', '-o', str(out/'test_guard_host')], cwd=HERE, check=True)
    subprocess.run([str(out/'test_guard_host')], check=True)
    for _, name, _ in builds:
        print(hashlib.sha256((out/name).read_bytes()).hexdigest(), name)


if __name__ == '__main__':
    main()
