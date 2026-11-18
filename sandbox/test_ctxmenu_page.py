"""Contract test for ContextMenuPage.

Offscreen, with load_menu / removed / remove / restore stubbed: no shell
menu is built and no registry key is written.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QPixmap  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import ctxmenu  # noqa: E402
from ctxmenu import MenuItem, Removed, Source  # noqa: E402

app = QApplication([])

BUILTIN = Source("builtin", "built-in", "", "", "", "")
UNKNOWN = Source("builtin", "unknown", "", "", "", "")
TERMINAL = Source("extension", "Terminal", "", "{9F156763-7844-4DC4-B2B1-901F640F5155}",
                  "", "all menus")
ZIP = Source("extension", "7-Zip", r"HKLM\Software\Classes\Directory\shellex"
             r"\ContextMenuHandlers\7-Zip", "{23170F69-40C1-278A-1000-000100020000}",
             r"C:\Program Files\7-Zip\7-zip.dll", "all menus")
GIT = Source("command", "git_gui", r"HKLM\Software\Classes\Directory\shell\git_gui",
             "", "", "Directory")
OLD = Source("command", "old", r"HKCU\Software\Classes\Directory\shell\old",
             "", "", "Directory")


def sep():
    return MenuItem("", separator=True)


def leaf(text, verb="", source=None):
    return MenuItem(text.replace("&", ""), text, verb, source=source)


ICON = QPixmap(16, 16)
ICON.fill(Qt.red)
TREE = [
    leaf("&Open", "open", BUILTIN),
    sep(),
    MenuItem("Open in Terminal", "Open in &Terminal", TERMINAL.clsid,
             icon=ICON, source=TERMINAL),
    MenuItem("7-Zip", "7-Zip", "SevenZip", source=ZIP, children=[
        leaf("Add to archive...", "SevenZipCompress", ZIP),
        sep(),
        leaf("Test", "SevenZipTest", ZIP)]),
    leaf("Open Git &GUI here", "git_gui", GIT),
    sep(),
    leaf("Mystery", "?", UNKNOWN),
    leaf("Cu&t", "cut", BUILTIN),
    leaf("P&roperties", "properties", BUILTIN),
]
REMOVED = [
    Removed("command|" + OLD.key, "Old Item", "folder", OLD),
    Removed("command|HKCU\\x", "Other Menu Item", "file", OLD),
]
calls = {"build": [], "remove": [], "restore": []}
fail = {"remove": None}
current = {"tree": TREE}


def fake_build(kind, path):
    calls["build"].append((kind, path))
    if isinstance(fail.get("build"), Exception):
        raise fail["build"]
    return current["tree"]


def fake_remove(source, text, menu, roots=None):
    if fail["remove"]:
        raise fail["remove"]
    calls["remove"].append((source, text, menu))


ctxmenu.load_menu = fake_build
ctxmenu.removed = lambda roots=None: REMOVED
ctxmenu.remove = fake_remove
ctxmenu.restore = lambda entry, roots=None: calls["restore"].append(entry)

page = ctxmenu.ContextMenuPage()
assert calls["build"] == [], "page must not build before it is shown"
page.resize(900, 520)
page.show()
app.processEvents()
assert calls["build"] == [("folder", os.environ["USERPROFILE"])], calls["build"]
page.show()
app.processEvents()
assert len(calls["build"]) == 1, "showing again must not rebuild"
print("lazy build ok")


def top():
    return [page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())]


def label(it):
    return it.text(0)


def payload(it):
    return it.data(0, Qt.UserRole)


def checkable(it):
    return bool(it.flags() & Qt.ItemIsUserCheckable)


def grey(it):
    return it.foreground(0).color().name() in ("#808080", "#7f7f7f", "#888888")


rows = top()
assert [label(r) for r in rows] == [
    "Open", "", "Open in Terminal", "7-Zip", "Open Git GUI here", "",
    "Mystery", "Cut", "Properties", "", "Old Item"], [label(r) for r in rows]
by = {label(r): r for r in rows if label(r)}

# separators: thin, unselectable, no text
for i in (1, 5, 9):
    assert not rows[i].flags() & Qt.ItemIsSelectable, i
    assert not checkable(rows[i]) and payload(rows[i]).separator, i
assert page.tree.isHeaderHidden()

# built-in / unknown rows: greyed, no checkbox, still selectable
for name in ("Open", "Cut", "Properties", "Mystery"):
    it = by[name]
    assert grey(it) and not checkable(it), name
    assert it.data(0, Qt.CheckStateRole) is None, name
    assert it.flags() & Qt.ItemIsSelectable, name

# removable rows: checked = keep, icon from the menu item
for name in ("Open in Terminal", "7-Zip", "Open Git GUI here"):
    it = by[name]
    assert checkable(it) and it.checkState(0) == Qt.Checked, name
    assert not grey(it), name
assert not by["Open in Terminal"].icon(0).isNull()
assert payload(by["Open Git GUI here"]).icon is None

# submenu children sit under their parent, expanded, with no checkbox
zip_row = by["7-Zip"]
assert [label(zip_row.child(i)) for i in range(zip_row.childCount())] == [
    "Add to archive...", "", "Test"]
assert zip_row.isExpanded()
assert not any(checkable(zip_row.child(i)) for i in range(3))

# removed rows come after a separator, struck through, unchecked = still removed
old = by["Old Item"]
assert old.font(0).strikeOut() and checkable(old)
assert old.checkState(0) == Qt.Unchecked
assert isinstance(payload(old), Removed)
assert "Other Menu Item" not in [label(r) for r in rows], "other menu's record shown"
assert page.status.text() == "0 removed   0 restored", page.status.text()
print("rows ok")

# ---- the source grid ----
def grid():
    return {page.grid.item(r, 0).text(): page.grid.item(r, 1).text()
            for r in range(page.grid.rowCount())}


assert page.grid.rowCount() == 5
assert [page.grid.item(r, 0).text() for r in range(5)] == [
    "Source", "Key", "CLSID", "DLL", "Scope"]
assert page.grid.textElideMode() == Qt.ElideMiddle
assert page.grid.showGrid() and "gridline-color" in page.grid.styleSheet()
page.tree.setCurrentItem(zip_row)
assert grid() == {"Source": "extension: 7-Zip", "Key": ZIP.key,
                  "CLSID": ZIP.clsid, "DLL": ZIP.dll, "Scope": "all menus"}, grid()
page.tree.setCurrentItem(zip_row.child(2))
assert grid()["CLSID"] == ZIP.clsid, "child shows its parent's source"
page.tree.setCurrentItem(by["Open Git GUI here"])
assert grid() == {"Source": "command: git_gui", "Key": GIT.key, "CLSID": "",
                  "DLL": "", "Scope": "Directory"}, grid()
page.tree.setCurrentItem(by["Mystery"])
assert grid()["Source"] == "unknown", grid()
page.tree.setCurrentItem(by["Cut"])
assert grid()["Source"] == "built-in", grid()
page.tree.setCurrentItem(old)
assert grid()["Key"] == OLD.key, grid()
print("grid ok")

# ---- pending state ----
by["Open Git GUI here"].setCheckState(0, Qt.Unchecked)
assert page.status.text() == "1 removed   0 restored", page.status.text()
old.setCheckState(0, Qt.Checked)
assert page.status.text() == "1 removed   1 restored", page.status.text()
by["Open in Terminal"].setCheckState(0, Qt.Unchecked)
assert page.status.text() == "2 removed   1 restored", page.status.text()
by["Open in Terminal"].setCheckState(0, Qt.Checked)
by["Open in Terminal"].setCheckState(0, Qt.Checked)
assert page.status.text() == "1 removed   1 restored", page.status.text()

# ---- Preview holds only the rows that are kept ----
def shape(menu):
    out = []
    for a in menu.actions():
        if a.isSeparator():
            out.append("-")
        elif a.menu() is not None:
            out.append((a.text(), shape(a.menu())))
        else:
            out.append(a.text())
    return out


by["Open in Terminal"].setCheckState(0, Qt.Unchecked)
menu = page.preview_menu()
assert shape(menu) == [
    "Open", "-", ("7-Zip", ["Add to archive...", "-", "Test"]), "-",
    "Mystery", "Cut", "Properties"], shape(menu)
by["Open in Terminal"].setCheckState(0, Qt.Checked)
menu = page.preview_menu()
assert shape(menu) == [
    "Open", "-", "Open in Terminal", ("7-Zip", ["Add to archive...", "-", "Test"]),
    "-", "Mystery", "Cut", "Properties"], shape(menu)
assert not [a for a in menu.actions() if a.text() == "Open in Terminal"][0].icon().isNull()
assert "Old Item" not in [a.text() for a in menu.actions()]
print("preview ok")

# ---- Apply removes the unchecked, restores the checked, rebuilds ----
builds = len(calls["build"])
page.btn_apply.click()
assert calls["remove"] == [(GIT, "Open Git GUI here", "folder")], calls["remove"]
assert calls["restore"] == [REMOVED[0]], calls["restore"]
assert len(calls["build"]) == builds + 1, "apply must rebuild"
assert page.status.text() == "1 removed   1 restored", page.status.text()
assert page.tree.topLevelItemCount() == 11
print("apply ok")

# nothing pending: apply does nothing
calls["remove"].clear()
calls["restore"].clear()
page.btn_apply.click()
assert not calls["remove"] and not calls["restore"]
assert page.status.text() == "0 removed   0 restored", page.status.text()

# a refused write is reported, not swallowed
by = {label(r): r for r in top() if label(r)}
by["Open Git GUI here"].setCheckState(0, Qt.Unchecked)
fail["remove"] = PermissionError(5, "Access is denied")
page.btn_apply.click()
assert "Access is denied" in page.status.text(), page.status.text()
fail["remove"] = None
print("refused write reported ok")

# ---- a rebuild error after Apply stays visible next to the counts ----
calls["remove"].clear()
by = {label(r): r for r in top() if label(r)}
by["Open Git GUI here"].setCheckState(0, Qt.Unchecked)
fail["build"] = FileNotFoundError(2, "The system cannot find the path specified")
page.btn_apply.click()
assert calls["remove"] == [(GIT, "Open Git GUI here", "folder")], calls["remove"]
text = page.status.text()
assert "cannot find the path" in text and "1 removed   0 restored" in text, text
fail["build"] = None
page.btn_reload.click()
print("rebuild error after apply ok")

# ---- rows sharing one source toggle together ----
SEND = Source("extension", "Send to", "", "{7BA4C740-9E81-11CF-99D3-00AA004AE837}",
              "", "all menus")
SHARED = [
    leaf("&Open", "open", BUILTIN),
    sep(),
    MenuItem("7-Zip", "7-Zip", "SevenZip", source=ZIP, children=[
        leaf("Add to archive...", "SevenZipCompress", ZIP)]),
    MenuItem("CRC SHA", "CRC SHA", "SevenZip.Checksum", source=ZIP),
    MenuItem("Send to", "Send to", "", source=SEND, children=[
        leaf("Desktop", "", SEND),
        MenuItem("7-Zip Zip", "7-Zip Zip", "", source=ZIP)]),
    leaf("Open Git GUI here", "git_gui", GIT),
]
current["tree"] = SHARED
page.reload()
by = {label(r): r for r in top() if label(r)}
calls["remove"].clear()
calls["restore"].clear()
assert page.status.text() == "0 removed   0 restored", page.status.text()
by["CRC SHA"].setCheckState(0, Qt.Unchecked)
assert by["7-Zip"].checkState(0) == Qt.Unchecked, "shared source did not follow"
assert by["Send to"].checkState(0) == Qt.Checked
assert by["Open Git GUI here"].checkState(0) == Qt.Checked
assert page.status.text() == "1 removed   0 restored", page.status.text()
menu = page.preview_menu()
assert shape(menu) == ["Open", "-", ("Send to", ["Desktop"]), "Open Git GUI here"], \
    shape(menu)
by["7-Zip"].setCheckState(0, Qt.Checked)
assert by["CRC SHA"].checkState(0) == Qt.Checked, "re-check did not follow"
assert page.status.text() == "0 removed   0 restored", page.status.text()
menu = page.preview_menu()
assert shape(menu) == [
    "Open", "-", ("7-Zip", ["Add to archive..."]), "CRC SHA",
    ("Send to", ["Desktop", "7-Zip Zip"]), "Open Git GUI here"], shape(menu)
by["7-Zip"].setCheckState(0, Qt.Unchecked)
page.btn_apply.click()
assert calls["remove"] == [(ZIP, "7-Zip, CRC SHA", "folder")], calls["remove"]
current["tree"] = TREE
page.reload()
print("shared source toggles together ok")

# ---- menu combo and path field ----
kinds = [page.cmb_menu.itemText(i) for i in range(page.cmb_menu.count())]
assert kinds == ["Folder", "File", "Folder background", "Drive", "New"], kinds
calls["build"].clear()
for text, kind, path in (
        ("File", "file", os.path.join(os.environ["SystemRoot"], "win.ini")),
        ("Folder background", "background", os.environ["USERPROFILE"]),
        ("Drive", "drive", "C:\\"),
        ("Folder", "folder", os.environ["USERPROFILE"])):
    page.cmb_menu.setCurrentText(text)
    assert page.edt_path.text() == path, (text, page.edt_path.text())
    assert calls["build"][-1] == (kind, path), calls["build"][-1]
page.edt_path.setText(r"C:\Windows")
page.btn_reload.click()
assert calls["build"][-1] == ("folder", r"C:\Windows"), calls["build"][-1]
print("combo and path ok")

# ---- a menu that cannot be built is a status error, not a crash ----
fail["build"] = FileNotFoundError(2, "The system cannot find the path specified")
page.btn_reload.click()
assert "cannot find the path" in page.status.text(), page.status.text()
assert page.tree.topLevelItemCount() == 0
assert page.btn_browse is not None and page.btn_preview is not None
fail["build"] = None
page.btn_reload.click()
assert page.tree.topLevelItemCount() == 11

# ---- a helper that timed out lists nothing and says so ----
fail["build"] = TimeoutError("menu helper timed out")
page.btn_reload.click()
assert page.status.text() == "menu helper timed out", page.status.text()
assert page.tree.topLevelItemCount() == 0
fail["build"] = None
page.btn_reload.click()
assert page.tree.topLevelItemCount() == 11
print("helper timeout reported, nothing listed ok")

print("STATUS: SUCCESS")
