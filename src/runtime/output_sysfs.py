"""Read the kernel event-device index as a hint; never grant output authority."""
import math,os,re,stat,time
from pathlib import Path

class InventoryUnavailable(RuntimeError):
    pass

def inventory(root='/sys/class/input'):
    directory=Path(root)
    before=directory.stat()
    if not stat.S_ISDIR(before.st_mode):raise InventoryUnavailable('sysfs directory unavailable')
    result={}
    with os.scandir(directory) as entries:
        for entry in entries:
            if not entry.name.startswith('event'):continue
            if not re.fullmatch(r'event(?:0|[1-9][0-9]{0,2})',entry.name):raise InventoryUnavailable('event name invalid')
            index=int(entry.name[5:])
            if index>=128 or index in result:raise InventoryUnavailable('event index outside inventory')
            path=directory/entry.name;identity=path.stat()
            if not stat.S_ISDIR(identity.st_mode):raise InventoryUnavailable('event directory unavailable')
            def read(relative,limit):
                with (path/relative).open('rb') as stream:value=stream.read(limit+1)
                if len(value)>limit:raise InventoryUnavailable('event metadata oversized')
                return value.decode('utf-8').rstrip('\n')
            dev=read('dev',64);name=read('device/name',256)
            if dev!='13:'+str(64+index) or not name or '\0' in name:raise InventoryUnavailable('event metadata invalid')
            result[index]=(name,identity.st_dev,identity.st_ino)
    after=directory.stat()
    if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino) or not result:
        raise InventoryUnavailable('sysfs index incomplete')
    return result


def unregistered(index):
    if type(index) is not int or not 0<=index<128:return False
    try:
        # A populated kernel character index must be visible before absence
        # can distinguish a static unbound /dev node from an actual device.
        if not stat.S_ISDIR(os.stat('/sys/dev/char').st_mode):return False
        os.stat('/sys/dev/char/1:3')
        os.lstat('/sys/dev/char/13:'+str(64+index))
    except FileNotFoundError as error:
        return error.filename=='/sys/dev/char/13:'+str(64+index)
    except OSError:return False
    return False


def wait_for_mouse(delay,*,wait,guard,clock=time.monotonic,read=None):
    """Interrupt a retry delay on a kernel hint; never open or authorize input.

    Only used after a complete scan found exactly one key sink and no mouse.
    Missing sysfs retains the ordinary delay. A positive hint always leads to
    another complete device validation, including capabilities and identity.
    """
    if type(delay) not in (int,float) or not math.isfinite(delay) or not 0<delay<=1:
        raise ValueError('invalid pointer readiness wait')
    read=inventory if read is None else read
    started=clock();previous=started;deadline=started+delay
    for _ in range(21):
        now=clock()
        if not math.isfinite(now) or now<previous:raise RuntimeError('pointer readiness clock changed')
        if now>=deadline or guard() is not True:return False
        previous=now
        try:
            found=any(value[0]=='ClickableMouse' for value in read().values())
        except (OSError,ValueError,InventoryUnavailable):
            remaining=deadline-clock()
            if remaining>0 and guard() is True:wait(min(delay,remaining))
            return False
        if found:return True
        remaining=deadline-clock()
        if remaining<=0:return False
        wait(min(.05,remaining))
    # Bound metadata reads even if the supplied wait returns without waiting.
    remaining=deadline-clock()
    if remaining>0 and guard() is True:wait(min(delay,remaining))
    return False
