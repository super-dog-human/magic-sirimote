"""Prove a disappeared hidraw node is not currently registered in sysfs.

This is point-in-time evidence only. The caller must recheck after opening an
independently identified target and must not accept an incomplete scan for any
other reason. Nothing is deleted or written.
"""
import errno,os,stat

def unregistered(*,index,major,minor,lstat=os.lstat,stat_fn=os.stat):
 if any(type(x) is not int or x<0 for x in (index,major,minor)) or index>=32:return False
 def absent(path):
  try:lstat(path)
  except OSError as e:
   if e.errno==errno.ENOENT:return True
   raise
  return False
 def same(a,b):return (a.st_dev,a.st_ino,a.st_rdev,a.st_mode)==(b.st_dev,b.st_ino,b.st_rdev,b.st_mode)
 try:
  root=stat_fn('/sys/dev/char');null=stat_fn('/dev/null')
  if not stat.S_ISDIR(root.st_mode) or not stat.S_ISCHR(null.st_mode):return False
  # Demonstrate that the sysfs character-device index is populated.
  if absent('/sys/dev/char/%d:%d'%(os.major(null.st_rdev),os.minor(null.st_rdev))):return False
  node=lstat('/dev/hidraw%d'%index)
  if not stat.S_ISCHR(node.st_mode) or (os.major(node.st_rdev),os.minor(node.st_rdev))!=(major,minor):return False
  if not absent('/sys/dev/char/%d:%d'%(major,minor)) or not absent('/sys/class/hidraw/hidraw%d'%index):return False
  if not same(node,lstat('/dev/hidraw%d'%index)):return False
  return absent('/sys/dev/char/%d:%d'%(major,minor)) and absent('/sys/class/hidraw/hidraw%d'%index)
 except OSError:return False
