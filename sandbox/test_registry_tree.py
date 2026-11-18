"""Verify the new regedit-style tree view in the Registry tab.

Same fixture as test_registry.py but exercises the UI tree:
    HKCU\\Software\\__clean_test_zone__\\a\\b\\c\\key_match_me        (match)
    HKCU\\Software\\__clean_test_zone__\\a\\b\\c\\sibling_innocent(v) (anchor)
    HKCU\\Software\\__clean_test_zone__\\x\\y\\z\\match_me             (match)
    HKCU\\Software\\__clean_test_zone__\\keepers\\anchor(v)            (anchor)

Asserts:
  * Both matches appear as leaves with an *unchecked* checkbox (opt-in) + bold font.
  * Intermediate path nodes (a, a\\b, a\\b\\c, x, x\\y, x\\y\\z, Software,
    __clean_test_zone__, ...) are present and navigable.
  * Empty-parent nodes (x, x\\y, x\\y\\z) get italic + (empty after delete)
    suffix and an *unchecked* checkbox (opt-in).
  * a, a\\b, a\\b\\c do NOT get the empty marker (sibling_innocent survives).
  * _checked_targets() is initially empty; opted-in nodes join it.
"""
import os
import sys
import winreg

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import Qt, QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication

import clean
import wintools

ROOT = r"Software\__clean_test_zone__"
HIVE = winreg.HKEY_CURRENT_USER


def mk_key(path, value=None):
    winreg.CreateKey(HIVE, path)
    if value is not None:
        with winreg.OpenKey(HIVE, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "v", 0, winreg.REG_SZ, value)


# Tear down any leftovers.
try:
    clean.reg_delete_recursive(HIVE, ROOT)
except OSError:
    pass

mk_key(ROOT + r"\a\b\c\key_match_me")
mk_key(ROOT + r"\a\b\c\sibling_innocent", value="hello")
mk_key(ROOT + r"\x\y\z\match_me")
mk_key(ROOT + r"\keepers\anchor", value="keep")

app = QApplication.instance() or QApplication([])
SETTINGS = wintools.QSettings(
    os.path.join(os.environ["TEMP"], "wintools-selftest.ini"),
    wintools.QSettings.IniFormat)
SETTINGS.clear()
w = wintools.WintoolsWindow(SETTINGS)
reg = dict(w.clean_pages)["Registry"]

# Drive a search programmatically.
reg.input.setText("match_me")
# Limit to HKCU to keep the test fast.
for name, cb in reg.cb_hives.items():
    cb.setChecked(name == "HKCU")
reg.start_search()

loop = QEventLoop()
reg._worker.finished_all.connect(lambda *_: loop.quit())
QTimer.singleShot(60_000, loop.quit)
loop.exec_()
# Allow the queued finished_all handler to mark empty parents.
app.processEvents()

print(f"Match rows recorded: {len(reg._rows)}")
zone_rows = [r for r in reg._rows if ROOT.lower() in r["path"].lower()]
print(f"  within test zone:  {len(zone_rows)}")
assert len(zone_rows) == 2, "expected 2 matches in the test zone"

# Sanity: hive root exists and is expanded
assert "HKCU" in reg._hive_items, "HKCU root missing from tree"
hive_root = reg._hive_items["HKCU"]
print(f"HKCU root children: {hive_root.childCount()}  expanded={hive_root.isExpanded()}")
assert hive_root.isExpanded()

# Walk to the matched leaves and check their state.
key_match_path = ROOT + r"\a\b\c\key_match_me"
xyz_match_path = ROOT + r"\x\y\z\match_me"
for p in (key_match_path, xyz_match_path):
    node = reg._path_nodes[("HKCU", p)]
    print(f"  match leaf {p}")
    print(f"    check={node.checkState(0)}  bold={node.font(0).bold()} italic={node.font(0).italic()}")
    assert node.checkState(0) == Qt.Unchecked, "match leaf should be Unchecked"
    assert node.font(0).bold(), "match leaf should be bold"

# Empty-parent nodes (x cascade): unchecked, italic, suffix.
for p in (ROOT + r"\x", ROOT + r"\x\y", ROOT + r"\x\y\z"):
    node = reg._path_nodes.get(("HKCU", p))
    assert node is not None, f"node missing for {p}"
    fl = node.flags()
    assert fl & Qt.ItemIsUserCheckable, f"empty parent {p} should be checkable"
    print(f"  empty parent {p}  check={node.checkState(0)}  italic={node.font(0).italic()}  text={node.text(0)!r}")
    assert node.checkState(0) == Qt.Unchecked, f"empty parent {p} should be Unchecked"
    assert node.font(0).italic(), f"empty parent {p} should be italic"
    assert "(empty after delete)" in node.text(0)

# Non-empty parents (a cascade): NOT marked.
for p in (ROOT + r"\a", ROOT + r"\a\b", ROOT + r"\a\b\c"):
    node = reg._path_nodes.get(("HKCU", p))
    assert node is not None, f"node missing for {p}"
    fl = node.flags()
    print(f"  nav parent  {p}  checkable={bool(fl & Qt.ItemIsUserCheckable)}  italic={node.font(0).italic()}")
    assert not (fl & Qt.ItemIsUserCheckable), f"non-empty parent {p} should NOT be checkable"
    assert not node.font(0).italic(), f"non-empty parent {p} should not be italic"

# Initial checked-target set is empty: matches and empty parents are opt-in.
zone_targets = [t for t in reg._checked_targets() if ROOT.lower() in t[1].lower()]
print(f"Initial checked targets in zone: {zone_targets}")
assert zone_targets == []

# Opt-in: check one match and the deepest empty parent (x\\y\\z).
for p in (key_match_path, ROOT + r"\x\y\z"):
    reg._path_nodes[("HKCU", p)].setCheckState(0, Qt.Checked)
app.processEvents()
zone_targets = [t for t in reg._checked_targets() if ROOT.lower() in t[1].lower()]
print(f"After opting in: targets = {zone_targets}")
assert sorted(zone_targets) == sorted([("HKCU", key_match_path), ("HKCU", ROOT + r"\x\y\z")])

# Cleanup
clean.reg_delete_recursive(HIVE, ROOT)
print()
print("STATUS: SUCCESS")
