"""Contract test for the tab/toolbar icons, the View-menu tab layout
(position, icon size, text) and the persisted window settings.

Builds the window offscreen against a scratch INI file; no tweak is applied.
"""

import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import QSize, Qt  # noqa: E402
from PyQt5.QtGui import QKeySequence  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication, QLineEdit, QTabBar, QTabWidget)

import tweaks  # noqa: E402
import wintools  # noqa: E402

app = QApplication([])

# ---- every icon ships all frames; a missing one fails loudly ----
names = [f"tab_{k}" for k in ("initcfg", "installer", "repeat", "keydiag",
                              "system", "gpu", "hardware", "files", "registry",
                              "orphans", "uninstall", "startup", "envedit", "ctxmenu", "empty",
                              "largest")]
names += [f"act_{k}" for k in ("refresh", "find", "import", "export",
                               "explorer")]
for n in names:
    sizes = {s.width() for s in wintools.icon(n).availableSizes()}
    assert {16, 24, 32, 48, 256} <= sizes, (n, sorted(sizes))
try:
    wintools.icon("tab_nope")
    raise AssertionError("missing icon did not raise")
except FileNotFoundError:
    pass
print(f"icons ok: {len(names)} files, 16-256 px frames")

INI = os.path.join(os.environ["TEMP"], "wintools-selftest-tabs.ini")
settings = wintools.QSettings(INI, wintools.QSettings.IniFormat)
settings.clear()
win = wintools.WintoolsWindow(settings)
win.resize(1000, 640)
win.show()
app.processEvents()

tabs = win.tabs
bar = tabs.tabBar()
assert isinstance(bar, wintools.SideTabBar)
for i in range(tabs.count()):
    assert not tabs.tabIcon(i).isNull(), i
    assert bar.tabData(i) == tabs.tabText(i), i
print(f"tab icons ok: {tabs.count()} tabs")

# ---- toolbar / menu actions ----
for act in (win.act_refresh, win.act_find, win.act_import, win.act_export,
            win.act_explorer):
    assert not act.icon().isNull(), act.text()
keys = [k.toString() for k in win.act_find.shortcuts()]
assert {"Ctrl+F", "Ctrl+K", "Ctrl+Space"} <= set(keys), keys
assert QKeySequence("F5") in win.act_refresh.shortcuts()
print("actions ok")

# ---- keypad +/- step tabs and wrap, even from a focused text field ----
QApplication.setActiveWindow(win)
n = tabs.count()
tabs.setCurrentIndex(n - 1)
tabs.setFocus()
app.processEvents()
QTest.keyClick(tabs, Qt.Key_Plus, Qt.KeypadModifier)
assert tabs.currentIndex() == 0, tabs.currentIndex()
QTest.keyClick(tabs, Qt.Key_Minus, Qt.KeypadModifier)
assert tabs.currentIndex() == n - 1, tabs.currentIndex()
QTest.keyClick(tabs, Qt.Key_Minus, Qt.KeypadModifier)
assert tabs.currentIndex() == n - 2, tabs.currentIndex()
QTest.keyClick(tabs, Qt.Key_Plus)  # main-row + is not bound
assert tabs.currentIndex() == n - 2, tabs.currentIndex()
edit = QLineEdit(tabs.currentWidget())
edit.show()
edit.setFocus()
app.processEvents()
QTest.keyClick(edit, Qt.Key_Minus, Qt.KeypadModifier)
assert edit.text() == "" and tabs.currentIndex() == n - 3, (edit.text(), tabs.currentIndex())
QTest.keyClick(edit, Qt.Key_Plus, Qt.KeypadModifier)
assert edit.text() == "" and tabs.currentIndex() == n - 2, (edit.text(), tabs.currentIndex())
QTest.keyClick(edit, Qt.Key_Minus)                   # main-row - still types
assert edit.text() == "-", edit.text()
edit.deleteLater()
print("keypad tab stepping ok")

# ---- status panes ----
on = sum(p.enabled_count() for _n, p in win.pages
         if isinstance(p, wintools.TweakPage))
assert win.lbl_count.text() == f"{on} of {len(tweaks.TWEAKS)} enabled", \
    win.lbl_count.text()
assert win.lbl_mode.text() in ("admin", "not admin")
win._report("probe")
assert win.statusBar().currentMessage() == "probe"
print(f"status ok: {win.lbl_count.text()}  {win.lbl_mode.text()}")


def pick(group, data):
    act = next(a for a in group.actions() if a.data() == data)
    act.trigger()
    app.processEvents()


# ---- tab position: side bars lay labels out horizontally ----
shapes = {"top": QTabBar.RoundedNorth, "left": QTabBar.RoundedWest,
          "right": QTabBar.RoundedEast}
for key, where in (("top", QTabWidget.North), ("left", QTabWidget.West),
                   ("right", QTabWidget.East)):
    pick(win.grp_tab_pos, key)
    assert tabs.tabPosition() == where, key
    assert bar.shape() == shapes[key], (key, bar.shape())
    # the label stays horizontal on every side: wider than tall
    hint = bar.tabSizeHint(0)
    assert hint.width() > hint.height(), (key, hint)
    assert bar.width() >= hint.width(), (key, bar.width(), hint)
    assert not win.grab().isNull()
    assert settings.value("tab_position") == key
print("tab positions ok: top / left / right")

# ---- icon size and text on/off ----
for px in wintools.TAB_ICON_SIZES:
    pick(win.grp_tab_icon, px)
    assert tabs.iconSize() == QSize(px, px), px
    assert settings.value("tab_icon_size", type=int) == px
win.act_tab_text.setChecked(False)
assert all(tabs.tabText(i) == "" for i in range(tabs.count()))
assert bar.tabData(4) == "System"
win.act_tab_text.setChecked(True)
assert tabs.tabText(4) == "System"
print("icon size / text toggle ok")

# ---- persistence: position, size, text, geometry, last tab ----
pick(win.grp_tab_pos, "left")
pick(win.grp_tab_icon, 32)
win.act_tab_text.setChecked(False)
tabs.setCurrentIndex(3)
win.close()
app.processEvents()
assert settings.value("tab_index", type=int) == 3
win2 = wintools.WintoolsWindow(settings)
assert win2.tabs.currentIndex() == 3
assert win2.tabs.tabPosition() == QTabWidget.West
assert win2.tabs.iconSize() == QSize(32, 32)
assert win2.tabs.tabText(0) == "" and win2.tabs.tabBar().tabData(0) == "Initial Config"
assert win2.size() == win.size(), (win2.size(), win.size())
print("persistence ok")

# ---- a stale setting falls back to the first choice ----
settings.setValue("tab_position", "sideways")
settings.setValue("tab_icon_size", 7)
win3 = wintools.WintoolsWindow(settings)
assert win3.tabs.tabPosition() == QTabWidget.North
assert win3.tabs.iconSize() == QSize(16, 16)
print("stale settings ok")

for w in (win2, win3):
    w.close()
app.processEvents()
settings.clear()
settings.sync()
os.remove(INI)
assert re.match(r"\d+ of \d+ enabled", win3.lbl_count.text())
print("STATUS: SUCCESS")
