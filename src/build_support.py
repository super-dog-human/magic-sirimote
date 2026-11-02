"""Deterministic IPK archives and reviewed ARM32 exec launchers. Build only."""
import gzip,hashlib,io,json,os,struct,subprocess,tarfile,zlib
from pathlib import Path,PurePosixPath
ELF_BASE=0x10000
TEXT_OFFSET=84
TEXT_VA=ELF_BASE+TEXT_OFFSET
EPOCH=1704067200
APP_PATH=''
def icon_png():
    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))
    pixels = b''.join(b'\0' + bytes((38, 78, 110, 255)) * 80 for _ in range(80))
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', 80, 80, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))

def object_text(path):
    raw = path.read_bytes()
    if raw[:7] != b'\x7fELF\x01\x01\x01' or struct.unpack_from('<H', raw, 18)[0] != 40:
        raise ValueError('Unexpected ARM32 object format')
    shoff = struct.unpack_from('<I', raw, 32)[0]
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', raw, 46)
    sections = [struct.unpack_from('<10I', raw, shoff + i * shentsize)
                for i in range(shnum)]
    names_section = sections[shstrndx]
    names = raw[names_section[4]:names_section[4] + names_section[5]]
    text = None
    for section in sections:
        name = names[section[0]:].split(b'\0', 1)[0]
        if section[1] in (4, 9) and section[5]:
            raise ValueError('Unexpected relocation section')
        if name == b'.text':
            text = raw[section[4]:section[4] + section[5]]
    if text is None:
        raise ValueError('Missing launcher text')
    return text

def arm_launcher(out):
    strings = ['/usr/bin/python3', '-I', '-B', APP_PATH + '/native_probe.py']
    addresses = []
    next_address = TEXT_VA + 60
    for value in strings:
        addresses.append(next_address)
        next_address += len(value.encode()) + 1
    asm = ''' .syntax unified
 .arm
 .text
 .global _start
_start:
 ldr r0, py_pointer
 ldr r1, argv_pointer
 mov r2, #0
 mov r7, #11
 svc #0
 mov r7, #1
 mov r0, #127
 svc #0
py_pointer:
 .word PY_ADDRESS
argv_pointer:
 .word ARGV_ADDRESS
argv:
 .word ARGS
'''.replace('PY_ADDRESS', hex(addresses[0])).replace(
        'ARGV_ADDRESS', hex(TEXT_VA + 40)).replace(
        'ARGS', ','.join(hex(value) for value in addresses) + ',0')
    asm += '\n'.join(' .asciz ' + json.dumps(value) for value in strings) + '\n'
    asm_path, obj_path = out / 'entry.S', out / 'entry.o'
    asm_path.write_text(asm)
    command = [os.environ.get('CLANG','clang'), '--target=armv7-linux-gnueabi', '-march=armv7-a',
               '-marm', '-c', str(asm_path), '-o', str(obj_path)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    text = object_text(obj_path)
    expected = struct.pack('<8I', 0xe59f0018, 0xe59f1018, 0xe3a02000,
                           0xe3a0700b, 0xef000000, 0xe3a07001,
                           0xe3a0007f, 0xef000000)
    if text[:32] != expected or struct.unpack_from('<2I', text, 32) != (addresses[0], TEXT_VA + 40):
        raise ValueError('Launcher instructions or argv pointers differ from expected')
    if struct.unpack_from('<5I', text, 40) != (*addresses, 0):
        raise ValueError('Launcher argv vector differs from expected')
    if text[60:] != b''.join(value.encode() + b'\0' for value in strings):
        raise ValueError('Launcher path strings differ from expected')
    ident = b'\x7fELF\x01\x01\x01\x00' + b'\0' * 8
    size = TEXT_OFFSET + len(text)
    header = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 40, 1, TEXT_VA,
                         52, 0, 0x05000000, 52, 32, 1, 0, 0, 0)
    phdr = struct.pack('<8I', 1, 0, ELF_BASE, ELF_BASE, size, size, 5, 0x1000)
    binary = header + phdr + text
    if len(binary) != size:
        raise ValueError('Launcher ELF size mismatch')
    entry = out / 'app/entry'
    entry.write_bytes(binary)
    entry.chmod(0o755)
    return {'source': str(asm_path), 'object': str(obj_path), 'command': command,
            'entrySha256': hashlib.sha256(binary).hexdigest(),
            'entryBytes': len(binary), 'entryFormat': 'ELF32 ARM EABI5 static execve/exit only'}

def safe_name(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or str(p) != name or '..' in p.parts or '\\' in name:
        raise ValueError('Unsafe archive path')
    return name

def tar_gz(files, directories, modes, owners):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(directories):
            safe_name(name)
            item = tarfile.TarInfo(name)
            item.type = tarfile.DIRTYPE
            item.mode = modes.get(name, 0o755)
            item.uid, item.gid = owners.get(name, (0, 0))
            item.mtime = EPOCH
            archive.addfile(item)
        for name, data in sorted(files.items()):
            safe_name(name)
            item = tarfile.TarInfo(name)
            item.size = len(data)
            item.mode = modes[name]
            item.uid, item.gid = owners[name]
            item.mtime = EPOCH
            archive.addfile(item, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(filename='', fileobj=compressed, mode='wb', compresslevel=9, mtime=0) as stream:
        stream.write(raw.getvalue())
    return compressed.getvalue()

def make_ar(members):
    data = bytearray(b'!<arch>\n')
    for name, content in members.items():
        data.extend((f'{name + "/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{len(content):<10}`\n').encode())
        data.extend(content)
        if len(content) & 1:
            data.extend(b'\n')
    return bytes(data)

def read_ar(raw):
    if not raw.startswith(b'!<arch>\n'):
        raise ValueError('Bad IPK archive signature')
    parts, offset = {}, 8
    while offset < len(raw):
        header = raw[offset:offset + 60]
        if len(header) != 60 or header[58:60] != b'`\n':
            raise ValueError('Malformed ar member')
        name = header[:16].decode('ascii').strip().rstrip('/')
        size = int(header[48:58])
        start = offset + 60
        content = raw[start:start + size]
        if len(content) != size or name in parts:
            raise ValueError('Bad ar member length or duplicate')
        parts[name] = content
        offset = start + size + size % 2
    if set(parts) != {'debian-binary', 'control.tar.gz', 'data.tar.gz'}:
        raise ValueError('Unexpected IPK members')
    if parts['debian-binary'] != b'2.0\n':
        raise ValueError('Unexpected IPK version')
    return parts

def inspect_tgz(raw):
    records = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        seen = set()
        for item in archive:
            safe_name(item.name)
            if item.name in seen or not (item.isdir() or item.isfile()):
                raise ValueError('Duplicate or unsupported archive entry')
            seen.add(item.name)
            records.append({'path': item.name, 'kind': 'directory' if item.isdir() else 'file',
                            'mode': oct(item.mode), 'uid': item.uid, 'gid': item.gid,
                            'bytes': item.size})
    return records

def node_launcher(out):
    # execve('/usr/bin/node', ['/usr/bin/node', APP_PATH + '/main.js'],
    #        ['NODE_PATH=/usr/lib/nodejs:/usr/lib/node_modules'])
    node='/usr/bin/node'; script=APP_PATH+'/main.js'
    env='NODE_PATH=/usr/lib/nodejs:/usr/lib/node_modules'
    text_va=0x10000+52+32
    ptr_node=text_va+32; ptr_argv=text_va+36; ptr_envp=text_va+40
    argv=text_va+44; envp=text_va+56; strings=text_va+64
    addr_node=strings; addr_script=addr_node+len(node.encode())+1; addr_env=addr_script+len(script.encode())+1
    asm=(
      ' .syntax unified\n .arm\n .text\n .global _start\n_start:\n'
      ' ldr r0, pnode\n ldr r1, pargv\n ldr r2, penvp\n'
      ' mov r7, #11\n svc #0\n mov r7, #1\n mov r0, #127\n svc #0\n'
      f'pnode: .word {addr_node}\npargv: .word {argv}\npenvp: .word {envp}\n'
      f' .word {addr_node}\n .word {addr_script}\n .word 0\n'
      f' .word {addr_env}\n .word 0\n'
      f' .asciz {json.dumps(node)}\n .asciz {json.dumps(script)}\n .asciz {json.dumps(env)}\n')
    asm_path=out/'entry.S';obj_path=out/'entry.o';asm_path.write_text(asm)
    cmd=[os.environ.get('CLANG','clang'),'--target=armv7-linux-gnueabi','-march=armv7-a','-marm','-c',str(asm_path),'-o',str(obj_path)]
    subprocess.run(cmd,check=True,capture_output=True,text=True)
    raw_obj=obj_path.read_bytes()
    if raw_obj[:7]!=b'\x7fELF\x01\x01\x01' or struct.unpack_from('<H',raw_obj,18)[0]!=40:raise ValueError('unexpected ARM object')
    shoff=struct.unpack_from('<I',raw_obj,32)[0];entsize,nsec,names_idx=struct.unpack_from('<HHH',raw_obj,46)
    sections=[struct.unpack_from('<10I',raw_obj,shoff+i*entsize) for i in range(nsec)]
    ns=sections[names_idx];names=raw_obj[ns[4]:ns[4]+ns[5]];text=None
    for sec in sections:
        name=names[sec[0]:].split(b'\0',1)[0]
        if sec[1] in (4,9) and sec[5]:raise ValueError('launcher relocations unexpected')
        if name==b'.text':text=raw_obj[sec[4]:sec[4]+sec[5]]
    if text is None:raise ValueError('launcher text missing')
    # Validate the exact argument/environment vectors and string table.
    if text[:32]!=struct.pack('<8I',0xe59f0018,0xe59f1018,0xe59f2018,0xe3a0700b,0xef000000,0xe3a07001,0xe3a0007f,0xef000000):raise ValueError('launcher instruction mismatch')
    if struct.unpack_from('<3I',text,32)!=(addr_node,argv,envp):raise ValueError('launcher pointer mismatch')
    if struct.unpack_from('<5I',text,44)!=(addr_node,addr_script,0,addr_env,0):raise ValueError('launcher argv/envp mismatch')
    expected=(node+'\0'+script+'\0'+env+'\0').encode()
    if text[64:]!=expected:raise ValueError('launcher strings mismatch')
    ident=b'\x7fELF\x01\x01\x01\x00'+b'\0'*8;elfbase=0x10000;offset=52+32;size=offset+len(text)
    header=struct.pack('<16sHHIIIIIHHHHHH',ident,2,40,1,text_va,52,0,0x05000000,52,32,1,0,0,0)
    phdr=struct.pack('<8I',1,0,elfbase,elfbase,size,size,5,0x1000);binary=header+phdr+text
    if len(binary)!=size:raise ValueError('launcher ELF size mismatch')
    entry=out/'app/entry';entry.write_bytes(binary);entry.chmod(0o755)
    return {'entrySha256':hashlib.sha256(binary).hexdigest(),'entryBytes':len(binary),'entryFormat':'ELF32 ARM EABI5 execve /usr/bin/node with explicit NODE_PATH'}
