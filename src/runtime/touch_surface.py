"""Touch geometry selected only after opening the verified paired HID device."""
from position_press import SurfaceRegions

# 2026-11-06: two perimeter/axis passes on each local remote reached the same
# X=-1818..-182 and Y minimum=-1074; observed Y maxima were 598/597.
# These are observed contact extents, not guaranteed hardware limits. Use the
# previously working A1962 envelope (with edge margin) for BOTH models; the
# old A1513 five-position calibration wrongly rejected valid outer contacts.
COMMON_BOUNDS = (-1850,-150,-1100,650)
BOUNDS = {0x0266: COMMON_BOUNDS, 0x026d: COMMON_BOUNDS}
_product = None

def bind_product(product):
    global _product
    if type(product) is not int or product not in BOUNDS:
        raise ValueError('Unsupported touch surface product')
    if _product is not None and _product != product:
        raise RuntimeError('Touch surface identity changed')
    _product=product

def regions():
    # Product binding still verifies identity; geometry is common to both.
    xmin,xmax,ymin,ymax=BOUNDS[0x0266 if _product is None else _product]
    return SurfaceRegions(x_min=xmin,x_max=xmax,y_min=ymin,y_max=ymax)


def current_product():
    """Return only the product verified while opening the paired HID device."""
    return _product
