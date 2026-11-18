"""Contract test for tweaks.BlackLockScreenOp and write_black_png.
Read-only against the live lock screen; the PNG goes to a scratch path."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtGui import QColor, QImage  # noqa: E402

import tweaks  # noqa: E402

png = os.path.join(os.environ["TEMP"], "wintools-selftest-black.png")
tweaks.write_black_png(png, 64, 36)
img = QImage(png)
assert not img.isNull(), "PNG did not decode"
assert (img.width(), img.height()) == (64, 36), (img.width(), img.height())
assert all(QColor(img.pixel(x, y)).rgb() & 0xFFFFFF == 0
           for x in (0, 31, 63) for y in (0, 17, 35))
os.remove(png)
print("black png ok")

tw = next(t for t in tweaks.TWEAKS if t.key == "blacksignin")
assert (tw.tab, tw.section, tw.label) == ("System", "Appearance", "Black Sign-in Screen")
op = tw.ops[0]
assert isinstance(op, tweaks.BlackLockScreenOp)
state = op.read()
assert state in (True, False), state
assert tw.state() is state
print(f"live state ok: {state}")

assert tweaks._user_sid().startswith("S-1-5-21-"), tweaks._user_sid()
assert tweaks.LOCK_PREV.path == r"Software\wintools"
print("STATUS: SUCCESS")
