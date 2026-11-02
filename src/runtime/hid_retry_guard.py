"""Bound a read-only HID re-scan to the same live connected generation."""
def make_guard(*,watch,lease,stop,feature,generation):
 if type(generation) is not int or generation<=0 or not callable(getattr(watch,'snapshot',None)) or not callable(getattr(lease,'held',None)) or not callable(getattr(stop,'is_set',None)) or not callable(feature):raise ValueError('invalid retry context')
 def guard():
  try:
   if stop.is_set() or lease.held() is not True or feature() is not True:return False
   current=watch.snapshot()
   return type(current) is dict and current.get('generation')==generation and lease.held() is True and not stop.is_set()
  except Exception:return False
 return guard
