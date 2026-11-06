"""Enumerate canonical HID node names without assuming their assigned numbers."""
import errno,os,re
MAX_NODES=256

def valid_index(value):
 return type(value) is int and 0<=value<1048576

def indexes(root,*,listdir=None):
 names=(os.listdir if listdir is None else listdir)(root)
 found=[]
 for name in names:
  if type(name) is not str or re.fullmatch(r'hidraw(0|[1-9][0-9]{0,6})',name) is None:continue
  index=int(name[6:])
  if not valid_index(index):raise OSError(errno.EOVERFLOW,'HID index out of range')
  found.append(index)
  if len(found)>MAX_NODES:raise OSError(errno.EOVERFLOW,'Too many HID nodes')
 if len(found)!=len(set(found)):raise OSError(errno.EINVAL,'Duplicate HID names')
 return sorted(found)
