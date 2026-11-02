#!/usr/bin/env python3
"""Read-only environment metadata. Run with TV Python after reviewing this file.

No Bluetooth calls, input stream opens, credential reads, or writes. Running in
SSH describes SSH, not native application permissions. No address/serial output.
"""
import json,os,platform,struct
from pathlib import Path

def inventory():
    inputs=[]
    for p in sorted(Path('/sys/class/input').glob('event[0-9]*'))[:128]:
        try:name=(p/'device/name').read_text().strip()
        except OSError:continue
        # Other device names can contain personal identifiers; omit them.
        if name in ('LGE RCU','ClickableMouse'):
            node=Path('/dev/input')/p.name
            try:
                s=node.stat()
                inputs.append({'name':name,'node':str(node),'uid':s.st_uid,'gid':s.st_gid,'mode':oct(s.st_mode&0o777)})
            except OSError:inputs.append({'name':name,'metadata':'unavailable'})
    return {'readOnly':True,'connectionContext':'current process, not proof of native app access',
        'machine':platform.machine(),'pointerBits':struct.calcsize('P')*8,
        'uid':os.getuid(),'gid':os.getgid(),'groups':os.getgroups(),
        'executablesPresent':{p:Path(p).is_file() for p in ('/usr/bin/python3','/usr/bin/node')},
        'inputMetadata':inputs,'inputStreamsOpened':False,'credentialsRead':False}
if __name__=='__main__':print(json.dumps(inventory(),indent=2))
