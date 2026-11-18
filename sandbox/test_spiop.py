"""Contract test for tweaks.SpiOp / AnimationOp and the visualfx / mousemax tweaks.

Reads every visualfx SPI op live; the only live writes are self-restoring round
trips (mouse speed, drag full windows, screen saver timeout) that put the
original value back in a finally.
"""

import os
import sys
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tweaks  # noqa: E402

by_key = {t.key: t for t in tweaks.TWEAKS}

# ---- the visualfx catalog entry carries the user's table ----
vfx = by_key["visualfx"]
assert (vfx.tab, vfx.section, vfx.label) == ("System", "Appearance",
                                             "Lean Visual Effects")
spi = [op for op in vfx.ops if isinstance(op, (tweaks.SpiOp, tweaks.AnimationOp))]
reg = [op for op in vfx.ops if isinstance(op, tweaks.RegOp)]
assert len(spi) + len(reg) == len(vfx.ops) == 18, (len(spi), len(reg))

# (get, set, on, off, via) straight from the spec table; Animation is its own class
expected_spi = {
    0x1043: (0x1042, 0, 1, "pv"),
    0x1003: (0x1002, 0, 1, "pv"),
    0x1017: (0x1016, 0, 1, "pv"),
    0x1015: (0x1014, 0, 1, "pv"),
    0x101B: (0x101A, 0, 1, "pv"),
    0x1025: (0x1024, 0, 1, "pv"),
    0x0025: (0x0026, 1, 1, "ui"),
    0x1005: (0x1004, 0, 1, "pv"),
    0x004B: (0x004A, 1, 1, "ui"),
    0x1007: (0x1006, 0, 1, "pv"),
}
plain = [op for op in spi if isinstance(op, tweaks.SpiOp)
         and not isinstance(op, tweaks.AnimationOp)]
got_spi = {op.set_: (op.get, op.on, op.off, op.via) for op in plain}
assert got_spi == expected_spi, got_spi
anim = [op for op in spi if isinstance(op, tweaks.AnimationOp)]
assert len(anim) == 1 and (anim[0].on, anim[0].off) == (0, 1)
assert anim[0].path == "SPI 0x0049", anim[0].path

expected_reg = {
    ("TaskbarAnimations", 0, 1), ("EnableAeroPeek", 0, 1),
    ("AlwaysHibernateThumbnails", 1, 1), ("IconsOnly", 0, 0),
    ("ListviewAlphaSelect", 1, 1), ("ListviewShadow", 1, 1),
    ("VisualFXSetting", 3, 0),
}
assert {(op.name, op.on, op.off) for op in reg} == expected_reg
print("visualfx table ok")

# ---- noanimations: every animation switch off, nothing else ----
noanim = by_key["noanimations"]
assert (noanim.tab, noanim.section, noanim.label) == (
    "System", "Appearance", "All Animations Off")
na_spi = {op.set_: (op.get, op.on, op.off, op.via) for op in noanim.ops
          if isinstance(op, tweaks.SpiOp) and not isinstance(op, tweaks.AnimationOp)}
assert na_spi == {
    0x1043: (0x1042, 0, 1, "pv"),   # Settings > Accessibility > Animation effects
    0x1003: (0x1002, 0, 1, "pv"),
    0x1017: (0x1016, 0, 1, "pv"),
    0x1015: (0x1014, 0, 1, "pv"),
    0x1005: (0x1004, 0, 1, "pv"),
    0x1007: (0x1006, 0, 1, "pv"),
}, na_spi
assert sum(isinstance(op, tweaks.AnimationOp) for op in noanim.ops) == 1
assert {(op.name, op.on, op.off) for op in noanim.ops
        if isinstance(op, tweaks.RegOp)} == {("TaskbarAnimations", 0, 1)}
assert len(noanim.ops) == 8, len(noanim.ops)
# shared switches agree with visualfx, so the two steps never fight
vfx_on = {getattr(op, "set_", None) or op.name: op.on for op in vfx.ops}
for op in noanim.ops:
    assert vfx_on[getattr(op, "set_", None) or op.name] == op.on, op.path
assert noanim.state() in (True, False)
print("noanimations ok")

# ---- duck type shared with FilterKeysOp / BlackLockScreenOp ----
for op in spi:
    assert op.off_key is None
    assert op.path and op.path.startswith("SPI 0x"), op.path
    assert op.available() is True
assert plain[0].path == f"SPI 0x{plain[0].set_:04X}"
print("duck type ok")

# ---- every read() answers live without error ----
for op in spi:
    val = op.read()
    assert isinstance(val, int), (op.path, val)
    assert op.is_on() == (val == op.on), op.path
print("live reads ok: " + " ".join(f"{op.path[4:]}={op.read()}" for op in spi))
assert vfx.state() in (True, False), vfx.state()

# ---- a refused call surfaces as OSError, not a silent default ----
try:
    tweaks.SpiOp(0x7FFF, 0x7FFF, 0, 1, "pv").read()
    raise AssertionError("SPI failure did not raise")
except OSError as e:
    assert e.winerror, e
print("failure raises OSError ok")

# ---- mousemax: one live round trip, original restored in a finally ----
mouse = by_key["mousemax"]
assert (mouse.tab, mouse.section) == ("System", "Appearance")
op = mouse.ops[0]
assert isinstance(op, tweaks.SpiOp)
assert (op.get, op.set_, op.on, op.off, op.via) == (0x0070, 0x0071, 20, 10, "pv")
orig = op.read()
assert 1 <= orig <= 20, orig
flip = op.off if orig == op.on else op.on
try:
    op.write(flip == op.on)
    assert op.read() == flip, (op.read(), flip)
    assert op.is_on() == (flip == op.on)
finally:
    op._set(orig)
assert op.read() == orig, (op.read(), orig)
print(f"mouse speed round trip ok: {orig} -> {flip} -> {orig}")

# ---- the uiParam SET path: window-contents-while-dragging round trip ----
drag = next(o for o in plain if o.set_ == 0x0025)
orig = drag.read()
try:
    drag._set(1 - orig)
    assert drag.read() == 1 - orig, (drag.read(), orig)
finally:
    drag._set(orig)
assert drag.read() == orig, (drag.read(), orig)
print(f"drag full windows round trip ok: {orig} -> {1 - orig} -> {orig}")

# ---- screensaver: Blank saver, 10 minutes (SystemParametersInfo screen saver rows) ----
ss = by_key["screensaver"]
assert (ss.tab, ss.section, ss.label) == ("System", "Appearance",
                                          "Blank Screen Saver 10 min")
assert len(ss.ops) == 3, ss.ops
exe, ss_active, ss_timeout = ss.ops
blank = os.path.join(os.environ["SystemRoot"], "System32", "scrnsave.scr")
assert os.path.isfile(blank), blank
assert isinstance(exe, tweaks.RegOp)
assert (exe.hive, exe.path, exe.name, exe.kind) == (
    tweaks.HKCU, r"Control Panel\Desktop", "SCRNSAVE.EXE", winreg.REG_SZ)
assert exe.on == blank and exe.off is tweaks.DELETE, (exe.on, exe.off)
for op, want in ((ss_active, (0x0010, 0x0011, 1, 0, "ui")),
                 (ss_timeout, (0x000E, 0x000F, 600, 600, "ui"))):
    assert isinstance(op, tweaks.SpiOp)
    assert (op.get, op.set_, op.on, op.off, op.via) == want, op.path
    assert op.read() in range(0, 100000)
assert ss_active.read() in (0, 1), ss_active.read()
assert ss.state() in (True, False), ss.state()
print("screensaver table ok")

# ---- the timeout SET path: one round trip, original restored in a finally ----
# (the active state and SCRNSAVE.EXE are never written live)
orig = ss_timeout.read()
assert orig > 0, orig
try:
    ss_timeout._set(orig + 60)
    assert ss_timeout.read() == orig + 60, (ss_timeout.read(), orig)
finally:
    ss_timeout._set(orig)
assert ss_timeout.read() == orig, (ss_timeout.read(), orig)
print(f"screen saver timeout round trip ok: {orig} -> {orig + 60} -> {orig}")

print("STATUS: SUCCESS")
