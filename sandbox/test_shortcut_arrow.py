"""Contract test for the shortcutarrow tweak.

Its Shell Icons\\29 value must name an icon that is fully transparent at every
size Explorer draws overlays at; any opaque pixel shows as a square on each
shortcut. The probe must also see opaque pixels in a known non-blank icon,
so a blank render cannot pass by accident.
"""

import ctypes
import os
import sys
import winreg
from ctypes import wintypes as wt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication  # noqa: E402

import clean  # noqa: E402
import tweaks  # noqa: E402

app = QApplication([])
user32 = ctypes.windll.user32
user32.PrivateExtractIconsW.argtypes = [
    wt.LPCWSTR,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(wt.HICON),
    ctypes.POINTER(wt.UINT),
    wt.UINT,
    wt.UINT,
]


def opaque_pixels(spec, size):
    path, idx = os.path.expandvars(spec).rsplit(",", 1)
    h = wt.HICON()
    n = user32.PrivateExtractIconsW(
        path, int(idx), size, size, ctypes.byref(h), None, 1, 0
    )
    assert n == 1 and h, f"{spec} @{size}: icon not found"
    img = clean._hicon_to_qpixmap(h.value, size).toImage()
    user32.DestroyIcon(h)
    return sum(
        1
        for y in range(img.height())
        for x in range(img.width())
        if img.pixelColor(x, y).alpha() > 0
    )


tw = next(t for t in tweaks.TWEAKS if t.key == "shortcutarrow")
(op,) = tw.ops
assert (op.hive, op.path, op.name, op.kind, op.off) == (
    tweaks.HKLM,
    tweaks.EXPLORER + r"\Shell Icons",
    "29",
    winreg.REG_EXPAND_SZ,
    tweaks.DELETE,
), op

assert opaque_pixels(r"%SystemRoot%\System32\imageres.dll,197", 32) > 0
for size in (16, 32, 48, 256):
    n = opaque_pixels(op.on, size)
    assert n == 0, f"{op.on} @{size}: {n} opaque pixels"
print(f"shortcutarrow ok: {op.on} is transparent at 16/32/48/256")
