"""Contract test for tweaks.RegOp / Tweak and wintools.fuzzy_score.

Registry writes are confined to HKCU\\Software\\wintools-selftest, which is
deleted at the end.  Nothing in the real tweak catalog is applied.
"""

import sys
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import filterkeys  # noqa: E402
import tweaks  # noqa: E402
from tweaks import DELETE, DELETE_KEY, HKCU, D, RegOp, S, Tweak  # noqa: E402
from wintools import fuzzy_score  # noqa: E402

ROOT = r"Software\wintools-selftest"
MISSING = ROOT + r"\does-not-exist"

tweaks._delete_tree(HKCU, ROOT)

try:
    # ---- DWORD round-trip, off = explicit value ----
    op = D(HKCU, ROOT, "dword", 1, 0)
    assert op.available()
    assert op.read() is None
    assert not op.is_on()
    op.write(True)
    assert op.read() == 1, op.read()
    assert op.is_on()
    op.write(False)
    assert op.read() == 0, op.read()
    assert not op.is_on()
    print("dword round-trip ok")

    # ---- REG_SZ round-trip ----
    op = S(HKCU, ROOT, "sz", "506", "510")
    op.write(True)
    assert op.read() == "506", op.read()
    op.write(False)
    assert op.read() == "510", op.read()
    print("sz round-trip ok")

    # ---- DELETE sentinel removes the value ----
    op = D(HKCU, ROOT, "deleteme", 1, DELETE)
    op.write(True)
    assert op.read() == 1
    op.write(False)
    assert op.read() is None, op.read()
    assert not op.is_on()
    op.write(False)  # deleting an absent value must not raise
    print("DELETE sentinel ok")

    # ---- REG_BINARY round-trip ----
    op = RegOp(HKCU, ROOT, "bin", b"\x00\x00\x00\x00", DELETE,
               winreg.REG_BINARY)
    op.write(True)
    assert op.read() == b"\x00\x00\x00\x00", op.read()
    op.write(False)
    assert op.read() is None
    print("binary round-trip ok")

    # ---- DELETE_KEY removes the whole subtree named by off_key ----
    inner = ROOT + r"\clsid\InprocServer32"
    op = S(HKCU, inner, "", "", DELETE_KEY, off_key=ROOT + r"\clsid")
    op.write(True)
    assert op.read() == "", repr(op.read())
    op.write(False)
    assert op.read() is None
    try:
        winreg.OpenKey(HKCU, ROOT + r"\clsid").Close()
        raise AssertionError("clsid key survived DELETE_KEY")
    except FileNotFoundError:
        pass
    print("DELETE_KEY ok")

    # ---- create=False never fabricates a missing key ----
    op = D(HKCU, MISSING, "Start", 4, 3, create=False)
    assert not op.available()
    tw = Tweak("t", "T", "S", "L", [op])
    assert tw.state() is None, tw.state()
    assert tw.apply(True) == 0
    try:
        winreg.OpenKey(HKCU, MISSING).Close()
        raise AssertionError("apply() created a create=False key")
    except FileNotFoundError:
        pass
    print("create=False guard ok")

    # ---- Tweak with several ops is on only when every op is on ----
    a = D(HKCU, ROOT, "a", 1, 0)
    b = D(HKCU, ROOT, "b", 1, 0)
    tw = Tweak("multi", "T", "S", "L", [a, b])
    tw.apply(True)
    assert tw.state() is True, tw.state()
    b.write(False)
    assert tw.state() is False, tw.state()
    tw.apply(False)
    assert a.read() == 0 and b.read() == 0
    print("multi-op state ok")
finally:
    tweaks._delete_tree(HKCU, ROOT)

try:
    winreg.OpenKey(HKCU, ROOT).Close()
    raise AssertionError("selftest key not cleaned up")
except FileNotFoundError:
    pass
print("cleanup ok")

# ---- FilterKeysOp drives the live SPI setting, not just the registry ----
fk_tweak = next(t for t in tweaks.TWEAKS if t.key == "filterkeys")
saved = filterkeys.read_filterkeys()
print(f"filterkeys before: flags=0x{saved.dwFlags:04x} "
      f"delay={saved.iDelayMSec} repeat={saved.iRepeatMSec}")
try:
    fk_tweak.apply(True)
    flags = filterkeys.read_filterkeys().dwFlags
    assert fk_tweak.state() is True, fk_tweak.state()
    assert not flags & filterkeys.FKF_FILTERKEYSON, hex(flags)
    assert not flags & filterkeys.FKF_HOTKEYACTIVE, hex(flags)
    assert flags & filterkeys.FKF_AVAILABLE, hex(flags)

    fk_tweak.apply(False)
    flags = filterkeys.read_filterkeys().dwFlags
    assert fk_tweak.state() is False, fk_tweak.state()
    assert flags & filterkeys.FKF_HOTKEYACTIVE, hex(flags)

    # An active FilterKeys must read as "not removed" even with the hotkey off.
    filterkeys.set_filterkeys(True, 250, 30, persist=False)
    assert not filterkeys.is_removed()
    assert fk_tweak.state() is False, fk_tweak.state()
finally:
    filterkeys.write_filterkeys(saved, persist=True)
back = filterkeys.read_filterkeys()
assert back.dwFlags == saved.dwFlags, (hex(back.dwFlags), hex(saved.dwFlags))
assert back.iRepeatMSec == saved.iRepeatMSec
print("filterkeys op ok, original restored")

# ---- catalog integrity ----
keys = [t.key for t in tweaks.TWEAKS]
assert len(keys) == len(set(keys)), \
    [k for k in keys if keys.count(k) > 1]
for t in tweaks.TWEAKS:
    assert t.ops or t.tasks, t.key
    assert t.tab in tweaks.TAB_ORDER, (t.key, t.tab)
    for op in t.ops:
        if op.off is DELETE_KEY:
            assert op.off_key or op.path, t.key

flat = [tw for _tab, secs in tweaks.tabs() for _s, items in secs for tw in items]
assert len(flat) == len(tweaks.TWEAKS), (len(flat), len(tweaks.TWEAKS))
assert {t.key for t in flat} == set(keys)
print(f"catalog ok: {len(keys)} tweaks, {len(tweaks.TAB_ORDER)} tabs")

# ---- fuzzy_score ----
assert fuzzy_score("", "anything") == 0
assert fuzzy_score("zzz", "taskbar") == -1
sub = fuzzy_score("widget", "Taskbar -> Taskbar -> Disable Widgets")
seq = fuzzy_score("dwgt", "Taskbar -> Taskbar -> Disable Widgets")
assert sub > seq > 0, (sub, seq)
early = fuzzy_score("disable", "Disable Chat")
late = fuzzy_score("disable", "Taskbar -> Taskbar -> Disable Chat")
assert early > late, (early, late)
print(f"fuzzy_score ok: substring={sub} subsequence={seq}")

# ---- UCPD.sys denies writes to these values to every process (even SYSTEM),
# so no tweak may target them; the supported policies are used instead ----
UCPD_PROTECTED = {"TaskbarDa", "ShellFeedsTaskbarViewMode", "IsFeedsAvailable",
                  "DeviceRegion"}
hits = [(t.key, op.name) for t in tweaks.TWEAKS for op in t.ops
        if isinstance(op, RegOp) and (op.name in UCPD_PROTECTED
                                       or "UserChoice" in op.path)]
assert not hits, hits
by_key = {t.key: t for t in tweaks.TWEAKS}
assert [(op.hive, op.path, op.name, op.on, op.off)
        for op in by_key["widgets"].ops] == [
    (tweaks.HKLM, r"SOFTWARE\Policies\Microsoft\Dsh", "AllowNewsAndInterests",
     0, DELETE)], by_key["widgets"].ops
# taskbar weather is the Widgets button on 11 and News & Interests on 10, both
# already covered; a separate weather tweak would only duplicate them
assert "taskbarweather" not in by_key
assert [(op.hive, op.path, op.name, op.on, op.off)
        for op in by_key["newsinterests"].ops] == [
    (tweaks.HKLM, tweaks.POL + r"\Windows Feeds", "EnableFeeds", 0, DELETE)], \
    by_key["newsinterests"].ops
print("no UCPD-protected writes ok")

# ---- a scheduled task this machine doesn't have is not a failed change ----
ghost = Tweak("ghosttasks", "T", "Sec", "Ghost", [],
              tasks=[r"\wintools-selftest\does-not-exist"])
assert tweaks.task_disabled(ghost.tasks[0]) is None
assert ghost.apply(True) == 0, ghost.apply(True)
print("absent task ok")

print("STATUS: SUCCESS")
