"""Check the interfaces used by the guard, without model/firmware allowlists."""
from pathlib import Path
import struct
import subprocess


def elf_info(data):
    if data[:4] != b'\x7fELF' or len(data) < 52 or data[4] not in (1, 2) or data[5] not in (1, 2):
        raise RuntimeError('Expected an ELF executable/library')
    bits, endian = data[4], '<' if data[5] == 1 else '>'
    def unpack(fmt, offset):
        try: return struct.unpack_from(endian + fmt, data, offset)
        except struct.error as error: raise RuntimeError('Incomplete ELF metadata') from error
    if bits == 1:
        header = unpack('HHIIIIIHHHHHH', 16)
        section_format, symbol_format = 'IIIIIIIIII', 'IIIBBH'
    else:
        header = unpack('HHIQQQIHHHHHH', 16)
        section_format, symbol_format = 'IIQQQQIIQQ', 'IBBHQQ'
    machine, flags = header[1], header[6]
    offset, size, count = header[5], header[10], header[11]
    if size < struct.calcsize(endian + section_format) or not 0 < count < 65536:
        raise RuntimeError('ELF section metadata is unavailable')
    sections = [unpack(section_format, offset + n * size) for n in range(count)]
    def content(section):
        start, length = section[4:6]
        if start + length > len(data): raise RuntimeError('Incomplete ELF section')
        return data[start:start + length]
    imports = set()
    for section in sections:
        if section[1] != 11: continue  # SHT_DYNSYM
        link, entry_size = section[6], section[9]
        if link >= len(sections) or entry_size < struct.calcsize(endian + symbol_format):
            raise RuntimeError('Invalid ELF dynamic symbol table')
        strings = content(sections[link]); symbols = content(section)
        if len(symbols) % entry_size: raise RuntimeError('Incomplete ELF symbol table')
        for n in range(0, len(symbols), entry_size):
            symbol = struct.unpack_from(endian + symbol_format, symbols, n)
            name, index = symbol[0], symbol[5] if bits == 1 else symbol[3]
            if index == 0 and name < len(strings):
                imports.add(strings[name:].split(b'\0', 1)[0].decode('ascii', 'replace'))
    # The ARM float calling convention must agree; other flags need not be identical.
    return {'abi': (bits, data[5], machine, flags & 0x600 if machine == 40 else 0), 'imports': imports}


def validate_elf(executable, library):
    target, guard = elf_info(executable), elf_info(library)
    if target['abi'] != guard['abi']:
        raise RuntimeError('The input service and guard use different CPU/ABI formats; a matching guard build is required')
    if 'open64' not in target['imports']:
        raise RuntimeError('The input service does not expose the open64 interface used by this fix')


def check_runtime(directory):
    directory = Path(directory)
    validate_elf(Path('/usr/sbin/bthidmanager').read_bytes(), (directory/'libsirimote-hid-guard.so').read_bytes())
    # Isolated loader test: opens /dev/null, never a Bluetooth device or input service.
    result = subprocess.run([str(directory/'guard_probe_arm'), str(directory/'libsirimote-hid-guard.so')],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError('The guard cannot load on this TV: '+result.stderr[-600:])
