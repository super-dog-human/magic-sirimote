"""Touch geometry selected only after opening the verified paired HID device."""
from position_press import SurfaceRegions

# A1513 retains its original measured calibration. A1962 reached Y=-1065
# locally; published captures span X=-1818..-182, Y=-1074..612. Include a
# small edge margin: https://github.com/a-funk/open-appleremote/blob/main/docs/PROTOCOL.md
BOUNDS = {0x0266: (-1768,-200,-1032,440), 0x026d: (-1850,-150,-1100,650)}
_product = None

def bind_product(product):
    global _product
    if type(product) is not int or product not in BOUNDS:
        raise ValueError('Unsupported touch surface product')
    if _product is not None and _product != product:
        raise RuntimeError('Touch surface identity changed')
    _product=product

def regions():
    # The legacy A1513 and pure decoder tests retain their original geometry.
    xmin,xmax,ymin,ymax=BOUNDS[0x0266 if _product is None else _product]
    return SurfaceRegions(x_min=xmin,x_max=xmax,y_min=ymin,y_max=ymax)
