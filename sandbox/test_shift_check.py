"""Verify Shift+range checking + yellow background on checked rows."""
import os
import sys
import winreg

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import Qt, QEvent, QPoint, QEventLoop, QTimer
from PyQt5.QtGui import QMouseEvent, QColor
from PyQt5.QtWidgets import QApplication

import clean
import wintools

# ---- Set up a small Orphan-paths fixture so the tree has multiple
# checkable leaves we can range-toggle ----
ROOT = r"Software\__clean_shift_check__"
HIVE = winreg.HKEY_CURRENT_USER


def mk_key(path, default_value=None):
    winreg.CreateKey(HIVE, path)
    if default_value is not None:
        with winreg.OpenKey(HIVE, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, default_value)


try:
    clean.reg_delete_recursive(HIVE, ROOT)
except OSError:
    pass

# 5 orphan leaves under a shared parent (so they all appear as siblings).
for name in ("alpha", "beta", "gamma", "delta", "epsilon"):
    mk_key(ROOT + "\\" + name, default_value=fr"C:\nope\{name}.dll")

app = QApplication.instance() or QApplication([])
SETTINGS = wintools.QSettings(
    os.path.join(os.environ["TEMP"], "wintools-selftest.ini"),
    wintools.QSettings.IniFormat)
SETTINGS.clear()
w = wintools.WintoolsWindow(SETTINGS)
op = dict(w.clean_pages)["Orphan paths"]
# Limit hives so the scan only sees HKCU.
for h_name, cb in op.cb_hives.items():
    cb.setChecked(h_name == "HKCU")
op.cb_deep.setChecked(True)   # deep needed because our fixture isn't a hot-spot
# Bypass the slow-scan confirmation dialog by stubbing QMessageBox.question
from PyQt5.QtWidgets import QMessageBox
orig_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **kw: QMessageBox.Yes)
op.start_scan()
QMessageBox.question = staticmethod(orig_q)

loop = QEventLoop()
op._worker.finished_all.connect(lambda *_: loop.quit())
QTimer.singleShot(60_000, loop.quit)
loop.exec_()
app.processEvents()

# Find our fixture rows
fixture_rows = [r for r in op._rows if ROOT.lower() in r["path"].lower()]
print(f"Fixture rows found: {len(fixture_rows)}")
assert len(fixture_rows) == 5

# All five are checked + bold + yellow BG by default
yellow = QColor(clean.CHECKED_ROW_BG)
for r in fixture_rows:
    item = r["item"]
    assert item.checkState(0) == Qt.Checked, f"{r['path']} not checked"
    bg = item.background(0).color()
    print(f"  {r['path'][-20:]:20}  check={item.checkState(0)}  bg={bg.name()}")
    assert bg == yellow, f"row bg should be yellow, got {bg.name()}"
print("Initial BG yellow: OK")

# Uncheck all to set up the range test
op._bulk_check(Qt.Unchecked)
for r in fixture_rows:
    item = r["item"]
    assert item.checkState(0) == Qt.Unchecked
    bg = item.background(0).color()
    assert bg != yellow or not bg.isValid(), f"row bg should be cleared, got {bg.name()}"
print("Bulk uncheck clears BG: OK")

# Programmatically simulate the shift+range behavior: set anchor on alpha,
# then call mousePressEvent on epsilon with Shift held.
alpha = fixture_rows[0]["item"]
epsilon = fixture_rows[4]["item"]

# First click: set anchor to alpha and check it.
alpha.setCheckState(0, Qt.Checked)
op.tree._check_anchor = alpha

# Issue a Shift+click on epsilon's rect.
rect = op.tree.visualItemRect(epsilon)
pos = rect.center()
ev = QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton,
                 Qt.LeftButton, Qt.ShiftModifier)
op.tree.mousePressEvent(ev)
app.processEvents()

# Now alpha..epsilon should all be Checked + yellow BG.
print()
print("After Shift+click on epsilon:")
for r in fixture_rows:
    item = r["item"]
    bg = item.background(0).color()
    print(f"  {r['path'][-20:]:20}  check={item.checkState(0)}  bg={bg.name()}  yellow={bg == yellow}")
    assert item.checkState(0) == Qt.Checked, f"{r['path']} should be checked after range"
    assert bg == yellow, f"{r['path']} should have yellow BG"
print("Shift+range check + yellow BG: OK")

# Now reverse: anchor on epsilon (currently checked); shift-click alpha;
# expect all five to remain checked (anchor state is Checked).
op.tree._check_anchor = epsilon
rect = op.tree.visualItemRect(alpha)
pos = rect.center()
ev = QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton,
                 Qt.LeftButton, Qt.ShiftModifier)
op.tree.mousePressEvent(ev)
app.processEvents()
for r in fixture_rows:
    assert r["item"].checkState(0) == Qt.Checked
print("Shift+click reverse direction still checks the range: OK")

# Now uncheck via shift+range: anchor = beta (uncheck it first),
# shift-click delta; all of beta..delta should turn off.
beta = fixture_rows[1]["item"]
delta = fixture_rows[3]["item"]
beta.setCheckState(0, Qt.Unchecked)   # state will propagate to BG via signal
app.processEvents()
op.tree._check_anchor = beta
rect = op.tree.visualItemRect(delta)
pos = rect.center()
ev = QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton,
                 Qt.LeftButton, Qt.ShiftModifier)
op.tree.mousePressEvent(ev)
app.processEvents()
states = [(r["path"][-10:], r["item"].checkState(0)) for r in fixture_rows]
print()
print(f"After Shift+uncheck range (beta..delta): {states}")
# Expectation: alpha checked, beta/gamma/delta unchecked, epsilon checked
assert fixture_rows[0]["item"].checkState(0) == Qt.Checked
assert fixture_rows[1]["item"].checkState(0) == Qt.Unchecked
assert fixture_rows[2]["item"].checkState(0) == Qt.Unchecked
assert fixture_rows[3]["item"].checkState(0) == Qt.Unchecked
assert fixture_rows[4]["item"].checkState(0) == Qt.Checked
print("Shift+range uncheck: OK")

# Verify the Registry tab tree also uses CheckRangeTreeWidget
print()
print(f"Registry tree class:    {type(dict(w.clean_pages)["Registry"].tree).__name__}")
print(f"Orphan paths tree class: {type(dict(w.clean_pages)["Orphan paths"].tree).__name__}")
print(f"Files tree class:       {type(dict(w.clean_pages)["Files"].tree).__name__}")
assert type(dict(w.clean_pages)["Registry"].tree).__name__ == "CheckRangeTreeWidget"
assert type(dict(w.clean_pages)["Orphan paths"].tree).__name__ == "CheckRangeTreeWidget"
assert type(dict(w.clean_pages)["Files"].tree).__name__ == "CheckRangeTreeWidget"

# Cleanup
clean.reg_delete_recursive(HIVE, ROOT)
print()
print("STATUS: SUCCESS")
