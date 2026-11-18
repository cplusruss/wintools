"""Contract test for tweaks.AlwaysOnOp and the alwayson tweak.

The live active scheme is only read (its values are recorded first and compared
at the end).  Every write goes to a duplicate of the active scheme that is
deleted in a finally.  PowerSetActiveScheme is never reached: AlwaysOnOp._apply
is replaced by a recorder and powrprof's entry point is replaced by a raiser.
"""

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tweaks  # noqa: E402

# ---- independent powrprof access (not the code under test) ----
pp = ctypes.WinDLL("powrprof")
k32 = ctypes.WinDLL("kernel32")
k32.LocalFree.argtypes = [ctypes.c_void_p]
k32.LocalFree.restype = ctypes.c_void_p
VP = ctypes.c_void_p
for name in ("PowerReadACValueIndex", "PowerReadDCValueIndex",
             "PowerReadACDefaultIndex", "PowerReadDCDefaultIndex"):
    fn = getattr(pp, name)
    fn.restype = wt.DWORD
    fn.argtypes = [VP, VP, VP, VP, ctypes.POINTER(wt.DWORD)]
for name in ("PowerWriteACValueIndex", "PowerWriteDCValueIndex"):
    fn = getattr(pp, name)
    fn.restype = wt.DWORD
    fn.argtypes = [VP, VP, VP, VP, wt.DWORD]
pp.PowerGetActiveScheme.restype = wt.DWORD
pp.PowerGetActiveScheme.argtypes = [VP, ctypes.POINTER(VP)]
pp.PowerDuplicateScheme.restype = wt.DWORD
pp.PowerDuplicateScheme.argtypes = [VP, VP, ctypes.POINTER(VP)]
pp.PowerDeleteScheme.restype = wt.DWORD
pp.PowerDeleteScheme.argtypes = [VP, VP]

G16 = ctypes.c_ubyte * 16
ERROR_FILE_NOT_FOUND = 2
AC, DC = "AC", "DC"
READ = {AC: pp.PowerReadACValueIndex, DC: pp.PowerReadDCValueIndex}
READ_DEFAULT = {AC: pp.PowerReadACDefaultIndex, DC: pp.PowerReadDCDefaultIndex}
WRITE = {AC: pp.PowerWriteACValueIndex, DC: pp.PowerWriteDCValueIndex}


def guid(text):
    return G16.from_buffer_copy(uuid.UUID(text).bytes_le)


def text_of(ptr):
    return "{" + str(uuid.UUID(bytes_le=ctypes.string_at(ptr, 16))) + "}"


def get_index(fn, scheme, sub, st):
    """value, or None when the setting is absent (rc 2); anything else fails"""
    val = wt.DWORD()
    rc = fn(None, ctypes.byref(guid(scheme)), ctypes.byref(guid(sub)),
            ctypes.byref(guid(st)), ctypes.byref(val))
    if rc == ERROR_FILE_NOT_FOUND:
        return None
    assert rc == 0, rc
    return val.value


def put_index(tag, scheme, sub, st, val):
    rc = WRITE[tag](None, ctypes.byref(guid(scheme)), ctypes.byref(guid(sub)),
                    ctypes.byref(guid(st)), val)
    assert rc == 0, rc


def active_scheme():
    out = VP()
    assert pp.PowerGetActiveScheme(None, ctypes.byref(out)) == 0
    try:
        return text_of(out.value)
    finally:
        k32.LocalFree(out)


def snapshot(scheme):
    """AC/DC value of every always-on setting the scheme has"""
    vals = {(sub, st, tag): get_index(READ[tag], scheme, sub, st)
            for sub, st in tweaks.ALWAYS_ON for tag in (AC, DC)}
    return {k: v for k, v in vals.items() if v is not None}


def scheme_list():
    """GUIDs (no braces) that powercfg /list shows"""
    return subprocess.run(["powercfg", "/list"], capture_output=True,
                          text=True, check=True).stdout.lower().replace("{", "")


# ---- the documented GUIDs (Microsoft power setting pages / powercfg /aliases) ----
assert tweaks.SUB_SLEEP == "{238c9fa8-0aad-41ed-83f4-97be242c8f20}"
assert tweaks.STANDBYIDLE == "{29f6c1db-86da-48c5-9fdb-f2b67b1f44da}"
assert tweaks.HIBERNATEIDLE == "{9d7815a6-7ee4-497e-8888-515a05f02364}"
assert tweaks.HYBRIDSLEEP == "{94ac6d29-73ce-41a6-809f-6363ba21b47e}"
assert tweaks.SUB_DISK == "{0012ee47-9041-4b5d-9b77-535fba8b1442}"
assert tweaks.DISKIDLE == "{6738e2c4-e8a5-4a42-b16a-e040e769756e}"
assert tweaks.SUB_USB == "{2a737441-1930-4402-8d77-b2bebba308a3}"
assert tweaks.USBSUSPEND == "{48e6b7a6-50f5-4782-a5d4-53bb8f07e226}"
assert tweaks.ALWAYS_ON == (
    (tweaks.SUB_SLEEP, tweaks.STANDBYIDLE),
    (tweaks.SUB_SLEEP, tweaks.HIBERNATEIDLE),
    (tweaks.SUB_SLEEP, tweaks.HYBRIDSLEEP),
    (tweaks.SUB_DISK, tweaks.DISKIDLE),
    (tweaks.SUB_USB, tweaks.USBSUSPEND)), tweaks.ALWAYS_ON
print("guid constants ok")

# ---- catalog entry and duck type ----
by_key = {t.key: t for t in tweaks.TWEAKS}
tw = by_key["alwayson"]
assert (tw.tab, tw.section, tw.label) == ("System", "Performance",
                                          "Always On Power")
assert len(tw.ops) == 1 and isinstance(tw.ops[0], tweaks.AlwaysOnOp)
live_op = tw.ops[0]
assert live_op.on is True and live_op.off is False and live_op.off_key is None
assert live_op.path and isinstance(live_op.path, str)
assert live_op.scheme is None
for attr in ("available", "read", "is_on", "write"):
    assert callable(getattr(live_op, attr)), attr
print("catalog entry ok")

# ---- errors surface as OSError carrying the powrprof code ----
tweaks._power_check(0)
try:
    tweaks._power_check(5)
    raise AssertionError("non-zero return did not raise")
except OSError as e:
    assert e.winerror == 5, e
g3 = [tweaks.guid(t) for t in ("{381b4222-f694-41f0-9685-ff5bb260df2e}", tweaks.SUB_SLEEP,
                                tweaks.STANDBYIDLE)]
assert tweaks._index(lambda *a: 2, *g3) is None
try:
    tweaks._index(lambda *a: 5, *g3)
    raise AssertionError("rc 5 did not raise")
except OSError as e:
    assert e.winerror == 5, e
print("power errors ok")

# ---- live scheme: read-only ----
active = active_scheme()
live_before = snapshot(active)
assert live_before, "no always-on setting exists in the active scheme"
assert live_op.available() is True
assert live_op.read() in (True, False) and live_op.is_on() == live_op.read()
assert live_op.read() == all(v == 0 for v in live_before.values()), live_before
assert tw.state() == live_op.read()
assert snapshot(active) == live_before and active_scheme() == active
print(f"live read ok: scheme {active} {live_before}")

# ---- write() against a scratch duplicate of the active scheme ----
out = VP()
assert pp.PowerDuplicateScheme(None, ctypes.byref(guid(active)),
                               ctypes.byref(out)) == 0
scratch = text_of(out.value)
k32.LocalFree(out)


def boom(*_a):
    raise AssertionError("PowerSetActiveScheme must never run in a test")


applied = []
try:
    assert scratch != active and scratch.strip("{}") in scheme_list()
    with mock.patch.object(tweaks._powrprof, "PowerSetActiveScheme", boom), \
            mock.patch.object(tweaks.AlwaysOnOp, "_apply",
                              lambda self, scheme: applied.append(scheme)):
        op = tweaks.AlwaysOnOp(scheme=scratch)
        present = list(live_before)
        # seed every setting AC and DC away from its always-on value
        for sub, st, tag in present:
            put_index(tag, scratch, sub, st,
                      1 if st in (tweaks.HYBRIDSLEEP, tweaks.USBSUSPEND) else 123)
        assert op.available() is True
        assert op.read() is False and op.is_on() is False

        defaults = {k: get_index(READ_DEFAULT[k[2]], scratch,
                                 k[0], k[1]) for k in present}
        assert all(v is not None for v in defaults.values()), defaults

        op.write(True)
        got = snapshot(scratch)
        assert got == {k: 0 for k in present}, got
        assert op.read() is True and op.is_on() is True
        print("write(True) ok: every AC/DC value is 0")

        # one DC value off: not on
        put_index(DC, scratch, tweaks.SUB_DISK, tweaks.DISKIDLE, 600)
        assert op.read() is False
        put_index(DC, scratch, tweaks.SUB_DISK, tweaks.DISKIDLE, 0)
        assert op.read() is True

        op.write(False)
        got = snapshot(scratch)
        assert got == defaults, (got, defaults)
        assert op.read() is False and op.is_on() is False
        assert any(v != 0 for v in defaults.values()), defaults
        print(f"write(False) ok: Balanced defaults restored {defaults}")

        # off on a non-Balanced scheme puts back that scheme's own defaults
        # (High performance never sleeps on AC; Balanced's 900 s would be wrong)
        high_perf = "{8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c}"
        out2 = VP()
        assert pp.PowerDuplicateScheme(None, ctypes.byref(guid(high_perf)),
                                       ctypes.byref(out2)) == 0
        hp = text_of(out2.value)
        k32.LocalFree(out2)
        try:
            hp_op = tweaks.AlwaysOnOp(scheme=hp)
            hp_defaults = {k: get_index(READ_DEFAULT[k[2]], hp, k[0], k[1])
                           for k in present}
            hp_op.write(True)
            hp_op.write(False)
            assert snapshot(hp) == hp_defaults, (snapshot(hp), hp_defaults)
            assert hp_defaults[(tweaks.SUB_SLEEP, tweaks.STANDBYIDLE, AC)] == 0, \
                hp_defaults
        finally:
            pp.PowerDeleteScheme(None, ctypes.byref(guid(hp)))
        print("write(False) on High performance ok: its own defaults restored")

        # an injected scheme is never applied; the active one is
        assert applied == [], applied

        # a setting this scheme does not have is skipped, not created
        ghost = "{00000000-1111-2222-3333-444444444444}"
        with mock.patch.object(tweaks, "ALWAYS_ON", tweaks.ALWAYS_ON
                               + ((tweaks.SUB_SLEEP, ghost),)):
            op.write(True)
            assert op.read() is True
            op.write(False)
            assert op.read() is False
        assert get_index(READ[AC], scratch, tweaks.SUB_SLEEP, ghost) is None
        assert get_index(READ[DC], scratch, tweaks.SUB_SLEEP, ghost) is None
        assert snapshot(scratch) == defaults
        print("missing setting skipped ok")

        # every setting missing: not available, state None, apply is a no-op
        with mock.patch.object(tweaks, "ALWAYS_ON",
                               ((tweaks.SUB_SLEEP, ghost),)):
            assert op.available() is False
            nothing = tweaks.Tweak("ghostpower", "System", "Performance",
                                   "Ghost", [op])
            assert nothing.state() is None
            nothing.apply(True)
        assert snapshot(scratch) == defaults
        print("no settings present ok")

        # the active-scheme path applies exactly once (writes still go to scratch)
        applied.clear()
        with mock.patch.object(tweaks.AlwaysOnOp, "_scheme",
                               lambda self: tweaks.guid(scratch)):
            tweaks.AlwaysOnOp().write(True)
        assert [bytes(a) for a in applied] == [bytes(tweaks.guid(scratch))], applied
        assert snapshot(scratch) == {k: 0 for k in present}
        print("apply on the active scheme ok")
finally:
    rc = pp.PowerDeleteScheme(None, ctypes.byref(guid(scratch)))
    assert rc == 0, rc
assert scratch.strip("{}") not in scheme_list()
assert active.strip("{}") in scheme_list()
print("scratch scheme deleted")

# ---- the live scheme never moved ----
assert active_scheme() == active
assert snapshot(active) == live_before, (snapshot(active), live_before)
print("live scheme unchanged ok")

print("STATUS: SUCCESS")
