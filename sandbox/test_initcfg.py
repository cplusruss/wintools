"""Contract test for initcfg (New PC step list, desktop cleanup, InitConfigPage).

Nothing here touches this machine's real settings or desktop: the page is
built against the live catalog read-only, and every run-through uses stub
tweaks plus a scratch folder under %TEMP%.
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

import clean  # noqa: E402
import initcfg  # noqa: E402
import tweaks  # noqa: E402
import winclassic  # noqa: E402
from wintools import TweakPage  # noqa: E402

app = QApplication([])
# the New PC warning is covered by test_confirm_guards.py
mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Yes).start()
by_key = {t.key: t for t in (*tweaks.TWEAKS, *winclassic.STEPS)}

# ---- the step list ----
keys = initcfg.NEWPC_KEYS
assert len(keys) == len(set(keys)), [k for k in keys if keys.count(k) > 1]
assert len(keys) == 7 + 2 + 6 + 4 + 7 + 16 + 6 + 6 == 54, len(keys)
missing = [k for k in keys if k not in by_key]
assert not missing, missing
assert keys[:7] == ("blackdesktop", "blacksignin", "visualfx",
                    "noanimations", "mousemax", "screensaver", "desktopicons")
assert keys[7:9] == ("alwayson", "hibernate")
assert keys[9:15] == ("taskbarleft", "taskbarsearch", "taskview", "widgets",
                      "chat", "stickers")
tv = by_key["taskview"]
assert (tv.tab, tv.section, tv.label) == ("Taskbar", "Taskbar", "Hide Task View Button")
assert [(op.path, op.name, op.on, op.off) for op in tv.ops] == [
    (tweaks.ADVANCED, "ShowTaskViewButton", 0, 1)], tv.ops
assert keys[-7:] == ("logonanimation", "defenderep", "explorerpatcher", "openshell",
                     "windhawk", "taskbartweaker", "classicappearance"), keys[-7:]
EXCLUDED_SECTIONS = {"Security", "Windows Update", "Services", "Storage",
                     "Gaming", "Performance"}
EXCLUDED_KEYS = {"perf", "location", "backgroundapps", "cloudclipboard"}
# Performance is excluded except the one tweak listed by key
LISTED_DESPITE_SECTION = {"alwayson"}
for k in keys:
    assert (by_key[k].section not in EXCLUDED_SECTIONS
            or k in LISTED_DESPITE_SECTION), (k, by_key[k].section)
    assert k not in EXCLUDED_KEYS, k
assert [k for k in keys if by_key[k].section in EXCLUDED_SECTIONS] == ["alwayson"]
assert by_key["alwayson"].section == "Performance"
assert "perf" not in keys
assert initcfg.STEPS == (*keys[:7], initcfg.RECYCLE, *keys[7:], initcfg.RESTART)
print(f"step list ok: {len(keys)} tweaks + 2 actions")

# ---- the new catalog entries ----
appearance = ("darkmode", "blackdesktop", "blacksignin", "visualfx",
              "noanimations", "mousemax", "screensaver", "desktopicons")
for k in appearance:
    assert (by_key[k].tab, by_key[k].section) == ("System", "Appearance"), k
labels = {k: by_key[k].label for k in appearance}
assert labels == {
    "darkmode": "Dark Mode", "blackdesktop": "Black Desktop",
    "blacksignin": "Black Sign-in Screen", "visualfx": "Lean Visual Effects",
    "noanimations": "All Animations Off",
    "mousemax": "Max Mouse Speed", "screensaver": "Blank Screen Saver 10 min",
    "desktopicons": "Desktop: Recycle Bin Only",
}, labels
assert (by_key["alwayson"].tab, by_key["alwayson"].label) == (
    "System", "Always On Power")
hib = by_key["hibernate"]
assert [(op.path, op.name, op.on, op.off) for op in hib.ops] == [
    (r"SYSTEM\CurrentControlSet\Control\Power", "HibernateEnabled", 0, 1)], hib.ops
assert not [t.key for t in tweaks.TWEAKS
            if t.section == "Appearance" and t.key not in appearance]
sys_tab = dict(tweaks.tabs())["System"]
assert "Appearance" in [s for s, _ in sys_tab]
print("appearance section ok")

for k in ("darkmode", "blackdesktop"):
    for op in by_key[k].ops:
        assert op.off_key is None and op.path, k
        assert op.available() is True
        assert op.read() in (True, False), (k, op.read())
        assert op.is_on() in (True, False)
        assert callable(op.write)
    assert by_key[k].state() in (True, False), k
assert isinstance(by_key["darkmode"].ops[0], tweaks.DarkModeOp)
assert isinstance(by_key["blackdesktop"].ops[0], tweaks.BlackDesktopOp)
print("custom op duck type ok")

icons = by_key["desktopicons"].ops
hide = {op.name: (op.on, op.off) for op in icons}
guids_hidden = ("{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
                "{59031a47-3f72-44a7-89c5-5595fe6b30ee}",
                "{F02C1A0D-BE21-4350-88B0-7367FC96EF3C}",
                "{5399E694-6CE5-4D6C-8FCE-1D8870FDCBA0}",
                "{2cc5ca98-6485-489a-920e-b3e88a6ccce3}")
assert len(icons) == 7, len(icons)
for g in guids_hidden:
    assert hide[g] == (1, tweaks.DELETE), g
assert hide["{645FF040-5081-101B-9F08-00AA002F954E}"] == (0, tweaks.DELETE)
assert hide["HideIcons"] == (0, tweaks.DELETE)
assert {op.path for op in icons if op.name != "HideIcons"} == {
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons"
    r"\NewStartPanel"}
assert all(op.hive == tweaks.HKCU for op in icons)
print("desktopicons table ok")

# ---- desktop folders ----
dirs = initcfg.desktop_dirs()
assert len(dirs) == 2 and dirs[0] != dirs[1], dirs
assert all(os.path.isdir(d) for d in dirs), dirs
assert dirs[1].lower().endswith(r"public\desktop"), dirs
try:
    initcfg.known_folder("{00000000-0000-0000-0000-000000000000}")
    raise AssertionError("unknown folder id did not raise")
except OSError:
    pass
print(f"desktop_dirs ok: {dirs}")

# ---- desktop_items / recycle against a scratch folder only ----
with tempfile.TemporaryDirectory(prefix="wintools-selftest-initcfg-") as scratch:
    user = os.path.join(scratch, "user")
    public = os.path.join(scratch, "public")
    for d in (user, public):
        os.makedirs(d)
        Path(d, "Desktop.ini").write_text("[.ShellClassInfo]\n")
    Path(user, "wintools-selftest-a.txt").write_text("a")
    Path(user, "wintools-selftest-b.lnk").write_text("b")
    os.makedirs(os.path.join(user, "wintools-selftest-folder"))
    Path(user, "wintools-selftest-folder", "inner.txt").write_text("i")
    Path(public, "wintools-selftest-c.txt").write_text("c")

    items = initcfg.desktop_items([user, public])
    names = [os.path.basename(p) for p in items]
    assert items == sorted(items)
    assert sorted(names) == ["wintools-selftest-a.txt", "wintools-selftest-b.lnk",
                             "wintools-selftest-c.txt", "wintools-selftest-folder"], names
    assert all(os.path.isabs(p) for p in items)
    print(f"desktop_items ok: {len(items)} items, desktop.ini kept out")

    # one bad path must not stop the rest
    ghost = os.path.join(user, "wintools-selftest-ghost.txt")
    recycled, failed = initcfg.recycle([ghost, *items])
    assert recycled == items, recycled
    assert [p for p, _e in failed] == [ghost], failed
    assert isinstance(failed[0][1], str) and failed[0][1], failed
    assert sorted(os.listdir(user)) == ["Desktop.ini"], os.listdir(user)
    assert sorted(os.listdir(public)) == ["Desktop.ini"], os.listdir(public)
    assert initcfg.desktop_items([user, public]) == []
    print(f"recycle ok: {len(recycled)} recycled, {len(failed)} failed, "
          "desktop.ini kept")

    # never destroy silently: the shell must warn before a permanent delete
    # (item too big for the bin, no bin on the volume), and an item the user
    # declines or the shell aborts is a failure, not a recycle
    seen_ops = []

    def aborting(op):
        seen_ops.append((op.wFunc, op.fFlags, op.pFrom))
        op.fAnyOperationsAborted = True
        return 0

    big = os.path.join(user, "wintools-selftest-big.bin")
    Path(big).write_text("x")
    with mock.patch.object(clean, "_file_op", aborting):
        recycled, failed = initcfg.recycle([big])
    func, flags, src = seen_ops[0]
    assert func == clean.FO_DELETE, func
    for flag in (clean.FOF_ALLOWUNDO, clean.FOF_WANTNUKEWARNING,
                 clean.FOF_NOCONFIRMATION):
        assert flags & flag, (hex(flags), hex(flag))
    assert src == big, src
    assert recycled == [] and [p for p, _e in failed] == [big], (recycled, failed)
    assert os.path.exists(big)
    with mock.patch.object(clean, "_file_op", lambda op: 0x78):
        recycled, failed = initcfg.recycle([big])
    assert recycled == [] and failed and failed[0][1], failed
    print("recycle never destroys silently ok")

# ---- the page against the live catalog: read-only ----
reports, calls = [], []
page = initcfg.InitConfigPage(
    reports.append, lambda: calls.append("refresh"),
    lambda: calls.append("restart"))
grid = page.grid
assert grid.rowCount() == len(keys) + 2, grid.rowCount()
assert [grid.horizontalHeaderItem(c).text() for c in range(3)] == [
    "Step", "Section", "State"]
assert page.btn.text() == "New PC" and page.btn.isEnabled()
assert all(grid.item(r, 0).flags() & Qt.ItemIsUserCheckable
           for r in range(grid.rowCount()))
assert all(grid.item(r, 0).checkState() == Qt.Checked
           for r in range(grid.rowCount()))
assert page.checked_steps() == list(initcfg.STEPS)

WORD = {True: "on", False: "off", None: "n/a"}
for r, step in enumerate(initcfg.STEPS):
    if step in (initcfg.RECYCLE, initcfg.RESTART):
        continue
    tw = by_key[step]
    assert grid.item(r, 0).text() == tw.label, (step, grid.item(r, 0).text())
    assert grid.item(r, 1).text() == tw.section
    state = tw.state()
    assert grid.item(r, 2).text() == WORD[state], (step, grid.item(r, 2).text())
    for c in range(3):
        brush = grid.item(r, c).background()
        if state is None:
            assert brush.style() == Qt.NoBrush, (step, c)
        else:
            want = TweakPage.LIME if state else TweakPage.PINK
            assert brush.color() == want, (step, c, brush.color().name())
r_rec = initcfg.STEPS.index(initcfg.RECYCLE)
assert initcfg.STEPS[r_rec - 1] == "desktopicons"
assert initcfg.STEPS[r_rec - 2] == "screensaver"
assert initcfg.STEPS[r_rec + 1:r_rec + 4] == ("alwayson", "hibernate", "taskbarleft")
assert grid.item(r_rec, 0).text() == "Recycle Desktop Items"
n_live = len(initcfg.desktop_items(initcfg.desktop_dirs()))
assert grid.item(r_rec, 2).text() == f"{n_live} item" + ("" if n_live == 1 else "s")
assert grid.item(r_rec, 0).background().style() == Qt.NoBrush
r_res = initcfg.STEPS.index(initcfg.RESTART)
assert r_res == grid.rowCount() - 1
assert grid.item(r_res, 0).text() == "Restart Explorer"
assert grid.item(r_res, 2).text() == ""
print("page rows ok: all checked, states read")

# unchecking drops a step from the plan; nothing else changes
r_w = initcfg.STEPS.index("widgets")
grid.item(r_w, 0).setCheckState(Qt.Unchecked)
grid.item(r_rec, 0).setCheckState(Qt.Unchecked)
plan = page.checked_steps()
assert "widgets" not in plan and initcfg.RECYCLE not in plan
assert plan == [s for s in initcfg.STEPS if s not in ("widgets", initcfg.RECYCLE)]
assert not calls and not reports, (calls, reports)
print("plan ok: unchecking removes a step, no apply performed")
page.shutdown()

# ---- worker semantics: errors recorded, never stop the run ----
order = []


def ok():
    order.append("ok")
    return ""


def denied():
    order.append("denied")
    raise PermissionError(5, "Access is denied")


def partial():
    order.append("partial")
    return "2 task(s) unchanged"


def broken():
    order.append("broken")
    raise ValueError("boom")


worker = initcfg.NewPcWorker([("A", ok), ("B", denied), ("C", partial),
                              ("E", broken), ("D", ok)])
seen = []
worker.progress.connect(seen.append, Qt.DirectConnection)
worker.start()
worker.wait()
assert order == ["ok", "denied", "partial", "broken", "ok"], order
assert worker.errors == ["B: Access is denied", "C: 2 task(s) unchanged",
                         "E: ValueError: boom"], worker.errors
assert seen == [1, 2, 3, 4, 5], seen
print("worker ok")

# ---- end-to-end run on stub tweaks + a scratch desktop ----
log = []


class StubOp:
    on, off, off_key, path = True, False, None, "stub"

    def __init__(self, name, fail=False):
        self.name, self.fail, self.val = name, fail, False

    def available(self):
        return True

    def read(self):
        return self.val

    def is_on(self):
        return self.val

    def write(self, on):
        if self.fail:
            log.append(f"fail {self.name}")
            raise PermissionError(5, "Access is denied")
        self.val = on
        log.append(f"write {self.name}")


stubs = [tweaks.Tweak(f"stub_{n}", "System", "Appearance", f"Stub {n.upper()}",
                      [StubOp(n, fail=(n == "b"))]) for n in "abc"]
STUB_STEPS = ("stub_a", "stub_b", initcfg.RECYCLE, "stub_c", initcfg.RESTART)


def wait_for(cond, what):
    end = time.time() + 20
    while not cond():
        app.processEvents()
        assert time.time() < end, f"timed out waiting for {what}"
        time.sleep(0.01)


def make_page(restart):
    # mirrors WintoolsWindow.refresh_all, which re-reads this page's states
    def refresh():
        calls.append("refresh")
        page.refresh_states()
    page = initcfg.InitConfigPage(reports.append, refresh, restart)
    return page


with tempfile.TemporaryDirectory(prefix="wintools-selftest-initcfg-") as scratch, \
        mock.patch.object(initcfg, "STEPS", STUB_STEPS), \
        mock.patch.object(tweaks, "TWEAKS", [*tweaks.TWEAKS, *stubs]):
    desk = os.path.join(scratch, "desk")
    os.makedirs(desk)
    Path(desk, "Desktop.ini").write_text("x")
    for n in "xyz":
        Path(desk, f"wintools-selftest-{n}.txt").write_text(n)

    def seed():
        for n in "xyz":
            Path(desk, f"wintools-selftest-{n}.txt").write_text(n)

    with mock.patch.object(initcfg, "desktop_dirs", lambda: [desk]):
        # Yes: all five steps run, the failed one is reported, restart is last
        calls.clear()
        reports.clear()
        log.clear()
        page = make_page(lambda: (log.append("restart"), calls.append("restart")))
        assert page.grid.rowCount() == 5
        assert page.grid.item(2, 2).text() == "3 items", page.grid.item(2, 2).text()
        with mock.patch.object(QMessageBox, "question",
                               return_value=QMessageBox.Yes) as q:
            page.btn.click()
            assert not page.btn.isEnabled()
            assert page.status.text() == "0 of 5", page.status.text()
            wait_for(page.btn.isEnabled, "worker")
        assert q.call_count == 1 and "3 desktop items" in q.call_args[0][2], \
            q.call_args
        # Enter on the destructive prompt must mean No
        assert q.call_args[0][3:5] == (QMessageBox.Yes | QMessageBox.No,
                                       QMessageBox.No), q.call_args
        assert log == ["write a", "fail b", "write c", "restart"], log
        assert os.listdir(desk) == ["Desktop.ini"], os.listdir(desk)
        assert page.status.text() == "4 applied   1 failed   Stub B: Access is denied", \
            page.status.text()
        assert reports and reports[-1] == page.status.text(), reports
        assert calls == ["restart", "refresh"], calls
        assert page.grid.item(0, 2).text() == "on"
        assert page.grid.item(1, 2).text() == "off"
        assert page.grid.item(3, 2).text() == "on"
        assert page.grid.item(2, 2).text() == "0 items"
        print(f"stub run (yes) ok: {page.status.text()}")

        # No: only the recycle step is skipped
        seed()
        calls.clear()
        reports.clear()
        log.clear()
        for s in stubs:
            s.ops[0].val = False
        page.refresh_states()
        with mock.patch.object(QMessageBox, "question",
                               return_value=QMessageBox.No):
            page.btn.click()
            assert page.status.text() == "0 of 4", page.status.text()
            wait_for(page.btn.isEnabled, "worker")
        assert len(os.listdir(desk)) == 4, os.listdir(desk)
        assert page.status.text() == "3 applied   1 failed   Stub B: Access is denied", \
            page.status.text()
        print(f"stub run (no) ok: {page.status.text()}")

        # unchecked steps are not applied; no confirm without the recycle step
        calls.clear()
        log.clear()
        for r in (0, 1, 2, 4):
            page.grid.item(r, 0).setCheckState(Qt.Unchecked)
        with mock.patch.object(QMessageBox, "question") as q:
            page.btn.click()
            wait_for(page.btn.isEnabled, "worker")
        assert not q.called
        assert log == ["write c"], log
        assert "restart" not in calls and "refresh" in calls, calls
        assert page.status.text() == "1 applied   0 failed", page.status.text()
        print(f"stub run (subset) ok: {page.status.text()}")
        page.shutdown()
        # a 'finished' already queued when the window closed must be a no-op
        calls.clear()
        page._finish()
        assert not calls, calls
        print("late finished after shutdown ok")
print("STATUS: SUCCESS")
