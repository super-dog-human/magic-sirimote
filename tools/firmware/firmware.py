#!/usr/bin/env python3
"""Fetch and validate the one tested A1513 target. Never opens a device."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile

URL = ('https://updates.cdn-apple.com/2019/ios/041-44746-201908730-71130D66-AFC7-11E9-83A5-4D41F70D717D/'
       'com_apple_MobileAsset_MobileAccessoryUpdate_WirelessRemoteFirmware/'
       'faab68bc0c5b473c11e836677f9ae189e0aced51.zip')
ARCHIVE_SHA256 = 'd744170c7a26686687af184d3dc1dd5c03f15240f7d455633c2a40f64465d168'
ARCHIVE_SIZE = 238607
VERSIONS = {1: 0x0257, 0x20: 0x0370, 0x30: 0x0120, 0x31: 0x0018, 0x40: 0x0815}
COMPONENTS = {
    'main': ('AssetData/main_app_0257_evtdvtpvt.bin.au.sig', 166214,
             'a4287261b4376c3842e9a3cdd3e006623f2ad6135c5f35600fab6264e0c594ad'),
    'radio': ('AssetData/radio_app_0120_evtdvtpvt.bin.au.sig', 27988,
              '18b1bcc03df8e27b4f2389c615275d73c5b298d16a5f6f5d7c27fa28618b5aec'),
}
# Public verification key extracted from BOTH Main0241 and Main0257. This is
# not an independent Apple certificate chain. The exact archive hash is pinned.
MODULUS = int(
    'd879627e3d548f90a66ac32ebebeae2f9a7c46d74c9f61aa078cc33532725133f6af39a26d9ad8de49d46dc5c6276b1ed6fbbee1fbcd35fecc14b3bdf4b510b4695b1f831a78360ad82c9008818c4259453d96442e2b9199bc0b4d2626857e915d73f201a65a454ec3fe946b1a8c2053dc02f9d657e9ab80557d350ef2ef1560b0f40f7df00a0fd18b5fe0ef84b202f3d3853f6b8323e0bcedf0999529ab3cd0bf71ec95adefc8b924e116097f2382cdbe609adf48c4a528c5f14ea3ad8bef562bc51acc19f4d352f4ac4cd131a8195148599ca38bb8261243cd35a3afc8a39a2116b61cb009892fe50915466902861961463e321080db02f313ffe122cda917', 16)
DIGEST_PREFIX = bytes.fromhex('3031300d060960864801650304020105000420')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def crc(data):
    """STM32 word-fed CRC; partial final word follows the firmware's byte loop."""
    value = 0xffffffff
    for i in range(0, len(data), 4):
        chunk = data[i:i + 4]
        value ^= int.from_bytes(chunk, 'little' if len(chunk) == 4 else 'big')
        for _ in range(32):
            value = ((value << 1) ^ (0x04c11db7 if value & 0x80000000 else 0)) & 0xffffffff
    return value


def validate_component(data):
    require(len(data) >= 416, 'truncated signed component')
    magic, fmt, kind, version, size, checksum, product, hardware = struct.unpack_from('<HHHHIIHH', data)
    require((magic, fmt, product, hardware) == (0xa2c7, 0x100, 0x266, 0x11), 'component identity/header differs')
    require(len(data) == size + 416, 'component length mismatch')
    require(crc(data[:124]) == struct.unpack_from('<I', data, 124)[0], 'header CRC mismatch')
    require(crc(data[128:128 + size]) == checksum, 'payload CRC mismatch')
    digest_offset = struct.unpack_from('<I', data, 0x2c)[0]
    signature_offset = struct.unpack_from('<I', data, 0x34)[0]
    require(digest_offset == 128 + size and signature_offset == digest_offset + 32, 'signature layout differs')
    digest = hashlib.sha256(data[:digest_offset]).digest()
    require(data[digest_offset:signature_offset] == digest, 'payload SHA256 mismatch')
    signature = int.from_bytes(data[signature_offset:], 'big')
    require(signature < MODULUS, 'invalid RSA signature integer')
    decoded = pow(signature, 65537, MODULUS).to_bytes(256, 'big')
    block = b'\x00\x01' + b'\xff' * (256 - 3 - len(DIGEST_PREFIX) - 32) + b'\x00' + DIGEST_PREFIX + digest
    require(decoded == block, 'RSA signature mismatch')
    return kind, version


def validate_archive(path):
    path = Path(path)
    # Read a bounded, immutable snapshot; validate and extract from those same bytes.
    with path.open('rb') as source:
        raw = source.read(ARCHIVE_SIZE + 1)
    require(len(raw) == ARCHIVE_SIZE, 'archive size differs from the tested 0x0257 package')
    require(hashlib.sha256(raw).hexdigest() == ARCHIVE_SHA256, 'archive SHA256 mismatch; file was not accepted')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len({entry.filename for entry in entries}) == len(entries), 'duplicate ZIP names')
        require(sum(entry.file_size for entry in entries) <= 4_000_000, 'expanded ZIP exceeds limit')
        require(archive.testzip() is None, 'ZIP CRC failure')
        versions = {}
        for entry in entries:
            if not entry.filename.endswith('.bin.au.sig'):
                continue
            kind, version = validate_component(archive.read(entry))
            require(kind not in versions, 'duplicate component type')
            versions[kind] = version
        require(versions == VERSIONS, 'unexpected firmware component versions')
        payloads = {}
        for name, (entry, size, digest) in COMPONENTS.items():
            data = archive.read(entry)
            require(len(data) == size and hashlib.sha256(data).hexdigest() == digest, 'unexpected ' + name + ' component')
            payloads[name] = data
    return payloads


def acquire(manual, cache):
    if manual is not None:
        path = Path(manual).expanduser().resolve()
        return path, validate_archive(path)  # No network and no change to supplied file.
    cache = Path(cache).expanduser().resolve()
    path = cache / 'a1513-0257.zip'
    if path.exists():
        return path, validate_archive(path)  # Do not silently replace corrupt cache entries.
    cache.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.download-', suffix='.zip', dir=cache)
    os.close(fd)
    try:
        print('Downloading the pinned 0x0257 package from Apple...', flush=True)
        subprocess.run(['/usr/bin/curl', '--fail', '--show-error', '--location',
                        '--proto', '=https', '--proto-redir', '=https', '--max-redirs', '3',
                        '--connect-timeout', '10', '--max-time', '60', '--max-filesize', '2000000',
                        '--output', temporary, URL], check=True)
        payloads = validate_archive(temporary)
        # Publish only verified bytes, without replacing an existing concurrent result.
        try:
            os.link(temporary, path)
        except FileExistsError:
            payloads = validate_archive(path)
        return path, payloads
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware', type=Path)
    parser.add_argument('--cache-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        archive, payloads = acquire(args.firmware, args.cache_dir)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, data in payloads.items():
            (args.output_dir / (name + '.bin')).write_bytes(data)
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        parser.exit(1, 'STOP: ' + str(error) + '\n')
    print('Validated archive:', archive)
    print('PASS: pinned SHA256, ZIP/firmware CRCs and RSA signatures. Prepared main and radio only.')


if __name__ == '__main__':
    main()
