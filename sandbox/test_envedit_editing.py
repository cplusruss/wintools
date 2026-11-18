"""Contract test for editing on the Environment tab (envedit.py): layout, keyboard, drag-and-drop
resolver, clipboard, undo/redo, inline variables, browse, duplicates and read-only trees.

Both scopes point at scratch keys under HKCU\\Software\\wintools-selftest-env-editing and
snapshots go to a temp folder; the real Environment keys are compared before and after, and the
broadcast, the folder dialog and os.startfile are stubbed.
"""

import os
import shutil
import sys
import tempfile
import winreg
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PyQt5.QtGui import QDropEvent  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QAbstractItemDelegate, QAbstractItemView, QApplication, QFileDialog, QLabel, QLineEdit,
    QPushButton, QSplitter,
)

import clean  # noqa: E402
import envedit  # noqa: E402

app = QApplication.instance() or QApplication([])
HKCU = winreg.HKEY_CURRENT_USER
BASE = r"Software\wintools-selftest-env-editing"
SYS, USR = BASE + r"\System", BASE + r"\User"
SNAPS = Path(tempfile.mkdtemp(prefix="wintools-env-edit-snaps-"))
roots = envedit.Roots(system=(HKCU, SYS), user=(HKCU, USR), snapshots=SNAPS)
WINDIR = os.environ["SystemRoot"]
CTRL, SHIFT, NONE = Qt.ControlModifier, Qt.ShiftModifier, Qt.NoModifier
D = [r"C:\a", r"C:\b", r"C:\c", r"C:\d", r"C:\e"]          # the DIRS list
SZ, EXPAND = winreg.REG_SZ, winreg.REG_EXPAND_SZ
BANNED = ("Folder or file not found", "Duplicate entry", "Refers to an undefined %variable%")


def values(key):
    with winreg.OpenKey(HKCU, key) as k:
        out, i = {}, 0
        while True:
            try:
                n, v, t = winreg.EnumValue(k, i)
            except OSError:
                return out
            out[n] = (v, t)
            i += 1


def teardown():
    try:
        clean.reg_delete_recursive(HKCU, BASE)
    except OSError:
        pass


def top(tree, name):
    return next(it for it in envedit.EnvPage._top(tree) if it.text(0) == name)


def var(tree, name):
    it = top(tree, name)
    it.setExpanded(True)
    return it


def texts(item):
    return [item.child(i).text(1) for i in range(item.childCount())]


def select(tree, *items):
    tree.clearSelection()
    tree.setCurrentItem(items[0])
    for it in items[1:]:
        it.setSelected(True)


def press(tree, key, mod=NONE):
    QTest.keyClick(tree, key, mod)


def editor(tree):
    eds = [e for e in tree.viewport().findChildren(QLineEdit) if not e.isHidden()]
    return eds[0] if eds else None


def editing(tree):
    return tree.state() == QAbstractItemView.EditingState and editor(tree) is not None


def commit(tree, text):
    ed = editor(tree)
    ed.setText(text)
    tree.commitData(ed)
    tree.closeEditor(ed, QAbstractItemDelegate.NoHint)


def escape(tree):
    tree.closeEditor(editor(tree), QAbstractItemDelegate.RevertModelCache)


def at(tree, item, frac):
    r = tree.visualItemRect(item)
    return QPoint(r.left() + 20, r.top() + int(r.height() * frac))


def menu_texts(menu):
    return [a.text().split("\t")[0] for a in menu.actions() if not a.isSeparator()]


def menu_action(menu, label):
    return next(a for a in menu.actions() if a.text().split("\t")[0] == label)


def selected_texts(tree):
    return sorted(it.text(1) for it in tree.selectedItems())


def scratch_page(system=None, user=None, admin=True):
    """A fresh page over freshly seeded scratch keys."""
    teardown()
    for key, vals in ((SYS, system or {}), (USR, user or {})):
        with winreg.CreateKey(HKCU, key) as k:
            for name, (v, t) in vals.items():
                winreg.SetValueEx(k, name, 0, t, v)
    p = envedit.EnvPage(roots=roots)
    if not admin:
        p.can_write_system = lambda: False
    p.resize(1100, 700)
    p.show()
    app.processEvents()
    return p


broadcasts = []
envedit.broadcast = lambda: broadcasts.append(1) or True
before_real = envedit.load().as_json()
saved_environ = dict(os.environ)
real_dialog, real_startfile = QFileDialog.getExistingDirectory, os.startfile
teardown()
for key, vals in ((SYS, {"Path": (fr"{WINDIR}\system32;%SystemRoot%;C:\nope\missing", EXPAND),
                         "ComSpec": (r"%SystemRoot%\system32\cmd.exe", EXPAND),
                         "TOOL_HOME": (r"C:\nope\tool", SZ)}),
                  (USR, {"Path": (fr"{WINDIR}\System32", EXPAND),
                         "TEMP": (r"%USERPROFILE%\AppData\Local\Temp", EXPAND),
                         "DIRS": (";".join(D), SZ),
                         "DUPS": (r"C:\x;c:\X\;C:\y", SZ),
                         "PLAIN": ("plain", SZ)})):
    with winreg.CreateKey(HKCU, key) as k:
        for name, (v, t) in vals.items():
            winreg.SetValueEx(k, name, 0, t, v)

try:
    page = envedit.EnvPage(roots=roots)
    page.resize(1100, 700)
    page.show()
    app.processEvents()
    sys_tree, usr_tree = page.trees["system"], page.trees["user"]
    clip = QApplication.clipboard()

    def fresh():
        page.reload()
        return var(usr_tree, "DIRS")

    # ---- layout and titles ----
    split = page.findChild(QSplitter)
    assert split.orientation() == Qt.Horizontal
    assert split.widget(0).isAncestorOf(sys_tree) and split.widget(1).isAncestorOf(usr_tree)
    assert split.widget(0).x() < split.widget(1).x(), "System is not left of User"
    assert {"System variables", "User variables"} <= {lbl.text() for lbl in page.findChildren(QLabel)}
    assert page.lbl_admin.text() == "", page.lbl_admin.text()
    print("layout ok")

    # ---- Insert opens an inline editor; an empty commit removes the row ----
    dirs = fresh()
    assert texts(dirs) == D
    h = len(page._hist)
    select(usr_tree, dirs.child(1))
    press(usr_tree, Qt.Key_Insert)
    assert texts(dirs) == D[:2] + [""] + D[2:], texts(dirs)
    assert editing(usr_tree) and usr_tree.currentItem() is dirs.child(2)
    commit(usr_tree, r"C:\new")
    with_new = D[:2] + [r"C:\new"] + D[2:]
    assert texts(dirs) == with_new, texts(dirs)
    assert len(page._hist) == h + 1 and page.pending()
    press(usr_tree, Qt.Key_Insert)
    assert texts(dirs)[3] == "" and editing(usr_tree)
    commit(usr_tree, "")
    assert texts(dirs) == with_new and len(page._hist) == h + 1, "empty commit left a row or history"
    press(usr_tree, Qt.Key_Insert)
    escape(usr_tree)
    assert texts(dirs) == with_new and len(page._hist) == h + 1, "Escape left a blank row"
    select(usr_tree, dirs)
    press(usr_tree, Qt.Key_Insert)
    assert texts(dirs) == with_new + [""] and editing(usr_tree), "Insert on a variable is not at its end"
    escape(usr_tree)
    assert texts(dirs) == with_new
    select(usr_tree, dirs.child(0))
    page.btn_add_entry.click()
    assert editing(usr_tree) and texts(dirs)[1] == "", "Add entry did not open an editor"
    escape(usr_tree)
    page.reload()
    plain = var(usr_tree, "PLAIN")
    select(usr_tree, plain)
    press(usr_tree, Qt.Key_Insert)
    assert texts(plain) == ["plain", ""], texts(plain)
    commit(usr_tree, r"C:\p2")
    assert page.current().user["plain"].value == r"plain;C:\p2"
    page.add_variable("user", "EMPTYV", "")
    emptyv = top(usr_tree, "EMPTYV")
    select(usr_tree, emptyv)
    press(usr_tree, Qt.Key_Insert)
    escape(usr_tree)
    assert emptyv.childCount() == 0 and emptyv.text(1) == "", "an emptied variable shows a count"
    assert page.current().user["emptyv"].value == ""
    select(usr_tree, emptyv)
    page.add_entry(tree=usr_tree)                  # no text: the editor opens, like Insert
    assert editing(usr_tree)
    escape(usr_tree)
    print("insert ok")

    # ---- F2 / Enter edit the value column ----
    dirs = fresh()
    select(usr_tree, dirs.child(0))
    h = len(page._hist)
    press(usr_tree, Qt.Key_F2)
    assert editing(usr_tree) and editor(usr_tree).text() == D[0]
    editor(usr_tree).setText(r"C:\f2")
    QTest.keyClick(editor(usr_tree), Qt.Key_Return)    # a real Return: the editor commits, the tree stays out
    app.processEvents()
    assert not editing(usr_tree) and dirs.child(0).text(1) == r"C:\f2" and len(page._hist) == h + 1
    press(usr_tree, Qt.Key_Return)
    assert editing(usr_tree)
    escape(usr_tree)
    assert dirs.child(0).text(1) == r"C:\f2"
    plain = var(usr_tree, "PLAIN")
    select(usr_tree, plain)
    press(usr_tree, Qt.Key_F2)
    assert editing(usr_tree) and editor(usr_tree).text() == "plain"
    escape(usr_tree)
    print("edit keys ok")

    # ---- Del ----
    dirs = fresh()
    select(usr_tree, dirs.child(0), dirs.child(1))
    h = len(page._hist)
    press(usr_tree, Qt.Key_Delete)
    assert texts(dirs) == D[2:], texts(dirs)
    assert usr_tree.currentItem() is dirs.child(0) and dirs.child(0).text(1) == D[2]
    assert len(page._hist) == h + 1
    press(usr_tree, Qt.Key_Delete)
    assert texts(dirs) == D[3:] and usr_tree.currentItem().text(1) == D[3], "repeated Del stalled"
    select(usr_tree, dirs.child(0), dirs.child(1))
    press(usr_tree, Qt.Key_Delete)
    assert texts(dirs) == [] and usr_tree.currentItem() is not None
    assert page.current().user["dirs"].value == "", "an emptied list kept its count as the value"
    dirs = fresh()
    plain = var(usr_tree, "PLAIN")
    select(usr_tree, plain)
    press(usr_tree, Qt.Key_Delete)
    assert "plain" not in page.current().user and usr_tree.currentItem() is not None
    assert [c.label for c in page.pending()] == ["remove user PLAIN"]
    print("del ok")

    # ---- Ctrl+Up / Ctrl+Down / Ctrl+Home / Ctrl+End on a block ----
    dirs = fresh()
    select(usr_tree, dirs.child(2), dirs.child(3))
    h = len(page._hist)
    press(usr_tree, Qt.Key_Down, CTRL)
    down = [D[0], D[1], D[4], D[2], D[3]]
    assert texts(dirs) == down, texts(dirs)
    assert selected_texts(usr_tree) == sorted(D[2:4]), "selection left the moved block"
    assert len(page._hist) == h + 1
    press(usr_tree, Qt.Key_Down, CTRL)
    assert texts(dirs) == down and len(page._hist) == h + 1, "moved past the end"
    press(usr_tree, Qt.Key_Up, CTRL)
    assert texts(dirs) == D
    press(usr_tree, Qt.Key_Up, CTRL)
    press(usr_tree, Qt.Key_Up, CTRL)
    up = [D[2], D[3], D[0], D[1], D[4]]
    assert texts(dirs) == up, texts(dirs)
    n = len(page._hist)
    press(usr_tree, Qt.Key_Up, CTRL)
    assert texts(dirs) == up and len(page._hist) == n, "moved past the top"
    press(usr_tree, Qt.Key_End, CTRL)
    assert texts(dirs) == down, texts(dirs)
    press(usr_tree, Qt.Key_Home, CTRL)
    assert texts(dirs) == up and selected_texts(usr_tree) == sorted(D[2:4])
    dirs = fresh()
    select(usr_tree, dirs.child(1))
    page.btn_down.click()
    assert texts(dirs) == [D[0], D[2], D[1], D[3], D[4]]
    page.btn_up.click()
    assert texts(dirs) == D
    select(usr_tree, dirs.child(0), dirs.child(2))
    press(usr_tree, Qt.Key_Down, CTRL)
    assert texts(dirs) == [D[1], D[0], D[3], D[2], D[4]], "each selected entry shifts by one"
    select(usr_tree, dirs, dirs.child(0))
    n = len(page._hist)
    press(usr_tree, Qt.Key_Down, CTRL)
    assert len(page._hist) == n, "a variable row in the selection moved"
    print("move ok")

    # ---- move_entries and the drop resolver ----
    dirs = fresh()
    a, b, c, d, e = (dirs.child(i) for i in range(5))
    dups, plain = var(usr_tree, "DUPS"), var(usr_tree, "PLAIN")
    app.processEvents()
    assert usr_tree.drop_target([b], at(usr_tree, d, 0.2)) == (dirs, 3)
    assert usr_tree.drop_target([b], at(usr_tree, d, 0.8)) == (dirs, 4)
    assert usr_tree.drop_target([b, a], at(usr_tree, e, 0.8)) == (dirs, 5)
    assert usr_tree.drop_target([b], at(usr_tree, dirs, 0.5)) == (dirs, 5), "drop on the variable row appends"
    empty = QPoint(10, usr_tree.viewport().height() - 3)
    assert usr_tree.itemAt(empty) is None
    assert usr_tree.drop_target([b], empty) is None, "top-level drop accepted"
    assert usr_tree.drop_target([b], at(usr_tree, dups.child(0), 0.5)) is None, "cross-variable drop accepted"
    assert usr_tree.drop_target([b], at(usr_tree, dups, 0.5)) is None, "drop on another variable accepted"
    assert usr_tree.drop_target([b], at(usr_tree, plain, 0.5)) is None
    assert usr_tree.drop_target([b, dups.child(0)], at(usr_tree, d, 0.2)) is None, "mixed parents accepted"
    assert usr_tree.drop_target([dirs], at(usr_tree, d, 0.2)) is None, "a dragged variable row accepted"
    assert usr_tree.drop_target([], at(usr_tree, d, 0.2)) is None
    spath = var(sys_tree, "Path")
    assert sys_tree.drop_target([b], at(sys_tree, spath.child(0), 0.5)) is None, "drop from the other tree accepted"

    h = len(page._hist)
    assert page.move_entries([b], 3) is True
    assert texts(dirs) == [D[0], D[2], D[1], D[3], D[4]], texts(dirs)
    assert selected_texts(usr_tree) == [D[1]] and len(page._hist) == h + 1
    assert page.move_entries([dirs.child(0), dirs.child(1)], 5) is True
    assert texts(dirs) == [D[1], D[3], D[4], D[0], D[2]], texts(dirs)
    assert page.move_entries([dirs.child(2), dirs.child(0)], 1) is True   # tree order is kept
    assert texts(dirs) == [D[1], D[4], D[3], D[0], D[2]], texts(dirs)
    dirs = fresh()
    dups = var(usr_tree, "DUPS")
    first = [dirs.child(0), dirs.child(1)]
    n = len(page._hist)
    assert all(page.move_entries(first, i) is False for i in (0, 1, 2)) and len(page._hist) == n, "no-op recorded"
    for bad in (([dirs.child(0), dups.child(0)], 0), ([dirs], 0), ([dirs.child(0)], 6), ([], 0)):
        try:
            page.move_entries(*bad)
        except ValueError:
            continue
        raise AssertionError(f"move_entries accepted {bad}")
    # dropEvent resolves the target and moves; the source rows must not be removed by the view
    b, d = dirs.child(1), dirs.child(3)
    app.processEvents()
    usr_tree._drag_items = [b]
    mime = QMimeData()
    ev = QDropEvent(QPointF(at(usr_tree, d, 0.2)), Qt.MoveAction | Qt.CopyAction, mime, Qt.LeftButton, NONE)
    usr_tree.dropEvent(ev)
    usr_tree._drag_items = []
    assert texts(dirs) == [D[0], D[2], D[1], D[3], D[4]], texts(dirs)
    assert ev.dropAction() == Qt.CopyAction, "a Move result would make the view delete the source rows"
    print("drag ok")

    # ---- clipboard ----
    dirs = fresh()
    select(usr_tree, dirs.child(1), dirs.child(2))
    press(usr_tree, Qt.Key_C, CTRL)
    assert clip.text() == f"{D[1]}\n{D[2]}", repr(clip.text())
    usr_tree.setCurrentItem(dirs.child(3))
    press(usr_tree, Qt.Key_V, CTRL)
    assert texts(dirs) == D[:4] + [D[1], D[2]] + D[4:], texts(dirs)
    assert selected_texts(usr_tree) == sorted([D[1], D[2]]) and usr_tree.currentItem() is dirs.child(5)
    clip.setText("a;b\nc")
    select(usr_tree, dirs.child(0))
    press(usr_tree, Qt.Key_V, CTRL)
    assert texts(dirs)[:5] == [D[0], "a", "b", "c", D[1]], texts(dirs)
    clip.setText(" ;\n; ")
    n = len(page._hist)
    press(usr_tree, Qt.Key_V, CTRL)
    assert len(page._hist) == n, "pasting only separators changed something"
    dirs = fresh()
    select(usr_tree, dirs.child(1), dirs.child(2))
    press(usr_tree, Qt.Key_X, CTRL)
    assert texts(dirs) == [D[0], D[3], D[4]] and clip.text() == f"{D[1]}\n{D[2]}", clip.text()
    dirs = fresh()
    select(usr_tree, dirs)
    press(usr_tree, Qt.Key_C, CTRL)
    assert clip.text() == ";".join(D), repr(clip.text())
    plain = var(usr_tree, "PLAIN")
    select(usr_tree, plain)
    press(usr_tree, Qt.Key_C, CTRL)
    assert clip.text() == "plain"
    clip.setText(r"C:\v1;C:\v2")
    press(usr_tree, Qt.Key_V, CTRL)
    assert page.current().user["plain"].value == r"plain;C:\v1;C:\v2", "paste on a single value"
    dirs = fresh()
    select(usr_tree, dirs)
    clip.setText(r"C:\end")
    press(usr_tree, Qt.Key_V, CTRL)
    assert texts(dirs) == D + [r"C:\end"], "paste on a variable is not at its end"
    print("clipboard ok")

    # ---- undo / redo ----
    dirs = fresh()
    base = page.current().as_json()
    assert len(page._hist) == 1 and page._hpos == 0
    select(usr_tree, dirs.child(0))
    page.add_entry(r"C:\u1", tree=usr_tree)                       # 1
    select(usr_tree, dirs.child(4))
    press(usr_tree, Qt.Key_Delete)                                # 2: removes D[3]
    page.add_variable("user", "UNDO_V", "1")                      # 3
    after3 = page.current().as_json()
    assert len(page._hist) == 4 and page.pending()
    press(usr_tree, Qt.Key_Z, CTRL)
    assert "undo_v" not in page.current().user and page._hpos == 2
    assert top(usr_tree, "DIRS").isExpanded(), "undo lost the expansion"
    press(usr_tree, Qt.Key_Z, CTRL)
    assert texts(top(usr_tree, "DIRS")) == [D[0], r"C:\u1"] + D[1:], texts(top(usr_tree, "DIRS"))
    press(usr_tree, Qt.Key_Z, CTRL)
    assert page.current().as_json() == base and not page.pending(), "three undos did not reach saved"
    assert "No unsaved changes" in page.status.text() and not page.btn_save.isEnabled()
    press(usr_tree, Qt.Key_Z, CTRL)
    assert page.current().as_json() == base and page._hpos == 0, "undo past the start"
    press(usr_tree, Qt.Key_Y, CTRL)
    assert r"C:\u1" in texts(top(usr_tree, "DIRS")) and page.pending()
    press(usr_tree, Qt.Key_Z, CTRL | SHIFT)
    assert texts(top(usr_tree, "DIRS")) == [D[0], r"C:\u1", D[1], D[2], D[4]], "Ctrl+Shift+Z did not redo"
    press(usr_tree, Qt.Key_Y, CTRL)
    assert page.current().as_json() == after3
    press(usr_tree, Qt.Key_Y, CTRL)
    assert page.current().as_json() == after3 and page._hpos == 3, "redo past the end"
    press(usr_tree, Qt.Key_Z, CTRL)
    press(usr_tree, Qt.Key_Z, CTRL)
    page.add_variable("user", "OTHER_V", "2")                     # a new mutation after undo
    assert len(page._hist) == page._hpos + 1 == 3, "the redo tail survived a new mutation"
    cur = page.current().as_json()
    press(usr_tree, Qt.Key_Y, CTRL)
    assert page.current().as_json() == cur and "UNDO_V" not in cur["user"]
    page.reload()
    assert len(page._hist) == 1 and page._hpos == 0, "reload kept history"
    press(usr_tree, Qt.Key_Z, CTRL)
    assert not page.pending()
    # an open line editor keeps its own Ctrl+Z
    dirs = fresh()
    select(usr_tree, dirs.child(0))
    page.add_entry(r"C:\u2", tree=usr_tree)
    select(usr_tree, top(usr_tree, "DIRS").child(0))
    press(usr_tree, Qt.Key_F2)
    h, pos = len(page._hist), page._hpos
    press(usr_tree, Qt.Key_Z, CTRL)
    QTest.keyClick(editor(usr_tree), Qt.Key_Z, CTRL)
    assert editing(usr_tree) and page._hpos == pos and len(page._hist) == h, "tree undo ran under an editor"
    escape(usr_tree)
    # a rename survives undo and redo
    page.reload()
    dups = var(usr_tree, "DUPS")
    select(usr_tree, dups)
    usr_tree.editItem(dups, 0)
    commit(usr_tree, "DUPS2")
    assert sorted(c.label for c in page.pending()) == ["add user DUPS2", "remove user DUPS"], page.pending()
    press(usr_tree, Qt.Key_Z, CTRL)
    assert not page.pending()
    press(usr_tree, Qt.Key_Y, CTRL)
    assert page.current().as_json() == page._hist[1].as_json() and page.pending()
    print("undo ok")

    # ---- variables ----
    page.reload()
    h = len(page._hist)
    it = page.add_variable("user")
    assert it is not None and editing(usr_tree) and usr_tree.currentItem() is it, "no inline name editor"
    commit(usr_tree, "NEWV")
    assert editing(usr_tree) and editor(usr_tree).text() == "", "the value editor did not follow the name"
    commit(usr_tree, "val")
    assert not editing(usr_tree) and page.current().user["newv"].value == "val"
    assert page.current().user["newv"].kind == SZ and len(page._hist) == h + 1, "an add took more than one step"
    press(usr_tree, Qt.Key_Z, CTRL)
    assert "newv" not in page.current().user
    press(usr_tree, Qt.Key_Y, CTRL)
    assert page.current().user["newv"].value == "val"
    page.add_variable("user")
    commit(usr_tree, "WITHP")
    commit(usr_tree, r"%SystemRoot%\x")
    assert page.current().user["withp"].kind == EXPAND
    page.add_variable("user")
    commit(usr_tree, "NOVAL")
    escape(usr_tree)                                              # the name stays, the value is empty
    assert page.current().user["noval"].value == "" and len(page._hist) == h + 3
    h = len(page._hist)
    page.add_variable("user")
    commit(usr_tree, "newv")
    assert not editing(usr_tree) and len(page._top(usr_tree)) == len(page.current().user), "dup row stayed"
    assert page.status.text().startswith("newv already exists"), page.status.text()
    assert len(page._hist) == h
    page.add_variable("user")
    commit(usr_tree, "")
    assert not editing(usr_tree) and len(page._top(usr_tree)) == len(page.current().user)
    page.add_variable("user")
    escape(usr_tree)
    assert len(page._top(usr_tree)) == len(page.current().user) and len(page._hist) == h
    plain = top(usr_tree, "PLAIN")
    usr_tree.editItem(plain, 0)
    commit(usr_tree, "NEWV")
    assert plain.text(0) == "PLAIN" and page.status.text().startswith("NEWV already exists"), page.status.text()
    assert page.current().user["plain"].value == "plain" and len(page._hist) == h, "a rejected rename recorded"
    usr_tree.editItem(plain, 0)
    commit(usr_tree, "")
    assert plain.text(0) == "PLAIN" and "plain" in page.current().user, "a blank name deleted the variable"
    usr_tree.editItem(plain, 0)
    commit(usr_tree, "RENAMED")
    assert "renamed" in page.current().user and len(page._hist) == h + 1
    assert page.add_variable("user", "newv", "x") is None and page.status.text().startswith("newv already exists")
    print("variables ok")

    # ---- remove duplicates ----
    dirs = fresh()
    dups = var(usr_tree, "DUPS")
    select(usr_tree, dups)
    h = len(page._hist)
    page.btn_dups.click()
    assert texts(dups) == [r"C:\x", r"C:\y"], texts(dups)
    assert page.status.text().startswith("Removed 1 duplicate entry"), page.status.text()
    assert len(page._hist) == h + 1
    select(usr_tree, dirs)
    clip.setText(f"{D[0].lower()}\\;{D[1]}")
    press(usr_tree, Qt.Key_V, CTRL)
    clip.setText(r"C:\X")
    select(usr_tree, dups)
    press(usr_tree, Qt.Key_V, CTRL)
    usr_tree.clearSelection()
    assert page.remove_duplicates(usr_tree) == 3
    assert texts(dirs) == D and texts(dups) == [r"C:\x", r"C:\y"], (texts(dirs), texts(dups))
    assert page.status.text().startswith("Removed 3 duplicate entries"), page.status.text()
    assert page.remove_duplicates(usr_tree) == 0 and page.status.text().startswith("Removed 0 duplicate entries")
    print("duplicates ok")

    # ---- browse and open in explorer ----
    dirs = fresh()
    ask, answer = [], ["C:/Tools/new dir"]

    def fake_dialog(*args, **kwargs):
        ask.append(args)
        return answer[0]

    QFileDialog.getExistingDirectory = staticmethod(fake_dialog)
    upath = var(usr_tree, "Path")
    select(usr_tree, upath)
    page.add_entry("%SystemRoot%", tree=usr_tree)
    exp = upath.child(upath.childCount() - 1)
    assert exp.text(1) == "%SystemRoot%"
    select(usr_tree, dirs.child(1))
    h = len(page._hist)
    page.browse_entry(usr_tree)
    assert dirs.child(1).text(1) == r"C:\Tools\new dir", dirs.child(1).text(1)
    assert ask[-1][2] == "", "a missing entry should start the dialog nowhere"
    assert len(page._hist) == h + 1
    select(usr_tree, exp)
    answer[0] = ""
    page.browse_entry(usr_tree)
    assert exp.text(1) == "%SystemRoot%" and len(page._hist) == h + 1, "cancel changed the entry"
    assert os.path.normcase(ask[-1][2]) == os.path.normcase(WINDIR), ask[-1]
    answer[0] = "D:/Added"
    select(usr_tree, dirs.child(0))
    page.add_folder(usr_tree)
    assert texts(dirs) == [D[0], r"D:\Added", r"C:\Tools\new dir"] + D[2:], texts(dirs)
    select(usr_tree, dirs)
    page.btn_folder.click()
    assert dirs.child(dirs.childCount() - 1).text(1) == r"D:\Added"
    answer[0] = ""
    n = dirs.childCount()
    page.add_folder(usr_tree)
    assert dirs.childCount() == n, "a cancelled Add folder inserted"
    started = []
    os.startfile = started.append
    select(usr_tree, exp)
    page.open_in_explorer(usr_tree)
    assert len(started) == 1 and os.path.normcase(started[0]) == os.path.normcase(WINDIR), started
    select(usr_tree, dirs.child(0))
    page.open_in_explorer(usr_tree)
    assert len(started) == 1 and page.status.text().startswith(f"not found: {D[0]}"), page.status.text()
    print("browse ok")

    # ---- context menus ----
    dirs = fresh()
    select(usr_tree, dirs.child(3))
    entry_menu = page.build_menu(usr_tree, dirs.child(3))
    assert menu_texts(entry_menu) == [
        "Insert above", "Insert below", "Edit", "Browse...", "Open in Explorer", "Copy", "Cut", "Paste",
        "Delete", "Move to top", "Move to bottom"], menu_texts(entry_menu)
    assert menu_action(entry_menu, "Delete").text().endswith("Del"), "shortcut not shown"
    var_menu = page.build_menu(usr_tree, dirs)
    assert menu_texts(var_menu) == ["Add entry", "Add folder...", "Edit", "Copy", "Paste", "Delete",
                                    "Add variable"], menu_texts(var_menu)
    assert menu_texts(page.build_menu(usr_tree, None)) == ["Add variable"]
    select(usr_tree, dirs)
    assert menu_texts(page.build_menu(usr_tree, None)) == ["Add variable", "Paste"]
    usr_tree.clearSelection()
    usr_tree.selectionModel().clearCurrentIndex()
    assert menu_texts(page.build_menu(usr_tree, None)) == ["Add variable"]
    select(usr_tree, dirs.child(3))
    menu_action(entry_menu, "Move to top").trigger()
    assert texts(dirs) == [D[3], D[0], D[1], D[2], D[4]], texts(dirs)
    menu_action(entry_menu, "Move to bottom").trigger()
    assert texts(dirs) == [D[0], D[1], D[2], D[4], D[3]], texts(dirs)
    menu_action(entry_menu, "Insert above").trigger()
    assert texts(dirs)[4] == "" and editing(usr_tree)
    escape(usr_tree)
    select(usr_tree, dirs.child(0))
    menu_action(entry_menu, "Delete").trigger()
    assert texts(dirs) == [D[1], D[2], D[4], D[3]], texts(dirs)
    menu_action(var_menu, "Add variable").trigger()
    assert editing(usr_tree)
    escape(usr_tree)
    print("menus ok")

    # ---- read-only system tree ----
    ro = envedit.EnvPage(roots=roots)
    ro.can_write_system = lambda: False
    ro.resize(1100, 700)
    ro.show()
    app.processEvents()
    rs, ru = ro.trees["system"], ro.trees["user"]
    assert ro.lbl_admin.text() == "system read-only", ro.lbl_admin.text()
    rpath = var(rs, "Path")
    app.processEvents()
    snap_json = ro.current().as_json()
    h = len(ro._hist)
    clip.setText(r"C:\paste")
    select(rs, rpath.child(1))
    for k, m in ((Qt.Key_Delete, NONE), (Qt.Key_Insert, NONE), (Qt.Key_F2, NONE), (Qt.Key_Return, NONE),
                 (Qt.Key_X, CTRL), (Qt.Key_V, CTRL), (Qt.Key_Up, CTRL), (Qt.Key_Down, CTRL),
                 (Qt.Key_Home, CTRL), (Qt.Key_End, CTRL), (Qt.Key_Z, CTRL), (Qt.Key_Y, CTRL)):
        QTest.keyClick(rs, k, m)
        assert ro.current().as_json() == snap_json and rs.state() != QAbstractItemView.EditingState, (k, m)
        assert clip.text() == r"C:\paste", f"key {k} touched the clipboard"
    assert len(ro._hist) == h
    assert rs.drop_target([rpath.child(1)], at(rs, rpath.child(0), 0.2)) is None, "read-only drop accepted"
    assert ro.move_entries([rpath.child(1)], 0) is False and ro.current().as_json() == snap_json
    for btn in (ro.btn_delete, ro.btn_add_entry, ro.btn_folder, ro.btn_up, ro.btn_down, ro.btn_clean,
                ro.btn_dups, ro.btn_add_var):
        assert not btn.isEnabled(), btn.text()
    assert ro.remove_duplicates(rs) == 0 and ro.remove_missing(rs) == 0
    assert ro.current().as_json() == snap_json
    select(rs, rpath.child(1))
    QTest.keyClick(rs, Qt.Key_C, CTRL)
    assert clip.text() == rpath.child(1).text(1)
    assert sorted(menu_texts(ro.build_menu(rs, rpath.child(1)))) == ["Copy", "Open in Explorer"]
    assert menu_texts(ro.build_menu(rs, rpath)) == ["Copy"]
    assert menu_texts(ro.build_menu(rs, None)) == []
    rdirs = var(ru, "DIRS")
    select(ru, rdirs.child(0))
    QTest.keyClick(ru, Qt.Key_Insert)
    assert editing(ru), "the user tree must stay writable"
    escape(ru)
    # a system change cannot be saved without elevation
    dirs = fresh()
    sp = var(sys_tree, "Path")
    select(sys_tree, sp.child(2))
    press(sys_tree, Qt.Key_Delete)
    page.can_write_system = lambda: False
    msg = page.save(confirm=False)
    del page.can_write_system
    assert msg == "Not saved: system variables are read-only", msg
    assert page.status.text().startswith(msg)
    assert values(SYS)["Path"][0].endswith("missing"), "a read-only save wrote"
    print("read-only ok")

    # ---- save after a sequence of edits writes exactly the expected values ----
    dirs = fresh()
    sp = var(sys_tree, "Path")
    select(sys_tree, sp.child(2))
    press(sys_tree, Qt.Key_Delete)
    clip.setText(r"C:\Tools\bin;C:\Tools\sbin")
    select(sys_tree, sp.child(1))
    press(sys_tree, Qt.Key_V, CTRL)
    select(usr_tree, dirs.child(3), dirs.child(4))
    press(usr_tree, Qt.Key_Up, CTRL)
    select(usr_tree, dirs.child(0))
    press(usr_tree, Qt.Key_Delete)
    page.add_variable("user")
    commit(usr_tree, "SAVED_VAR")
    commit(usr_tree, r"%USERPROFILE%\x")
    select(usr_tree, var(usr_tree, "DUPS"))
    page.remove_duplicates(usr_tree)
    assert page.save(confirm=False) == ""
    sv, uv = values(SYS), values(USR)
    assert sv["Path"] == (fr"{WINDIR}\system32;%SystemRoot%;C:\Tools\bin;C:\Tools\sbin", EXPAND), sv["Path"]
    assert sv["TOOL_HOME"] == (r"C:\nope\tool", SZ), "untouched value changed"
    assert uv["DIRS"] == (r"C:\b;C:\d;C:\e;C:\c", SZ), uv["DIRS"]
    assert uv["DUPS"] == (r"C:\x;C:\y", SZ), uv["DUPS"]
    assert uv["SAVED_VAR"] == (r"%USERPROFILE%\x", EXPAND), uv["SAVED_VAR"]
    assert uv["PLAIN"] == ("plain", SZ) and uv["Path"] == (fr"{WINDIR}\System32", EXPAND)
    page._refresh_thread.join(5)
    app.processEvents()
    assert broadcasts and not page.pending()
    assert len(page._hist) == 1, "save kept history"
    print("save ok:", page.status.text())

    # ---- no explainer strings ----
    page.reload()
    sel_dirs = var(usr_tree, "DIRS")
    select(usr_tree, sel_dirs)
    clip.setText(sel_dirs.child(0).text(1))
    press(usr_tree, Qt.Key_V, CTRL)                               # a duplicate
    page.add_entry(r"%NOPE_VAR_XYZ%\y", tree=usr_tree)            # an undefined variable; DIRS also has missing ones
    tips = []
    for tree in page.trees.values():
        for t in page._top(tree):
            for itm in [t] + [t.child(i) for i in range(t.childCount())]:
                tips += [itm.toolTip(0), itm.toolTip(1)]
    hits = [tip for tip in tips if any(b in tip for b in BANNED)]
    assert not hits, hits
    assert any(tip.lower().endswith("windows") for tip in tips), "the expanded-value tooltip is gone"
    for btn in page.findChildren(QPushButton):
        assert btn.toolTip() == "", (btn.text(), btn.toolTip())
    print("strings ok")

    # ---- list-ness is a flag on the row, never read back from the displayed text ----
    UP = {"Path": (r"C:\u", EXPAND)}
    p = scratch_page(user={**UP, "SEMI": (";", SZ)})
    assert not p.pending() and p.current().user["semi"].value == ";", "a lone ';' is not kept as saved"
    p.add_variable("user", "OTHER", "1")
    assert p.save(confirm=False) == "" and values(USR)["SEMI"] == (";", SZ), values(USR)["SEMI"]
    p = scratch_page(user={**UP, "PLAIN": ("x", SZ)})
    top(p.trees["user"], "PLAIN").setText(1, ";")
    assert p.current().user["plain"].value == "", p.current().user["plain"].value
    assert top(p.trees["user"], "PLAIN").childCount() == 0
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "C:/z")
    for how in ("insert", "entry", "paste", "folder"):
        p = scratch_page(user={"Path": (r"C:\a;C:\b", EXPAND)})
        ut = p.trees["user"]
        upath = var(ut, "Path")
        select(ut, upath.child(0), upath.child(1))
        p.delete_selected(ut)
        assert p.current().user["path"].value == ""
        select(ut, upath)
        if how == "insert":
            press(ut, Qt.Key_Insert)
            assert texts(upath) == [""] and editing(ut), (how, texts(upath))
            commit(ut, r"C:\z")
        elif how == "entry":
            p.add_entry(r"C:\z", ut)
        elif how == "paste":
            clip.setText(r"C:\z")
            p.paste(ut)
        else:
            p.add_folder(ut)
        assert texts(upath) == [r"C:\z"], (how, texts(upath))
        assert p.current().user["path"].value == r"C:\z", how
    p = scratch_page(user=UP)
    ut = p.trees["user"]
    p.add_variable("user")
    commit(ut, "PSModulePath")
    assert editing(ut)
    commit(ut, r"C:\mods")
    assert p.current().user["psmodulepath"].value == r"C:\mods"
    assert texts(top(ut, "PSModulePath")) == [r"C:\mods"]
    assert p.save(confirm=False) == "" and values(USR)["PSModulePath"] == (r"C:\mods", SZ)
    p = scratch_page(user=UP)
    ut = p.trees["user"]
    ps = p.add_variable("user", "PSModulePath", "")
    ps.setText(1, r"C:\mods")
    assert p.current().user["psmodulepath"].value == r"C:\mods" and texts(ps) == [r"C:\mods"]
    p = scratch_page(user={**UP, "ABC": ("keepme", SZ)})
    ut = p.trees["user"]
    abc = top(ut, "ABC")
    abc.setText(0, "PATHEXT")
    assert p.current().user["pathext"].value == "keepme" and texts(abc) == ["keepme"], texts(abc)
    p = scratch_page(user={"Path": (r"C:\a", EXPAND)})
    ut = p.trees["user"]
    upath = var(ut, "Path")
    select(ut, upath.child(0))
    p.delete_selected(ut)
    upath.setText(0, "FOO")
    assert p.current().user["foo"].value == "", p.current().user["foo"].value
    p = scratch_page(user={"Path": (r"C:\a;C:\b", EXPAND)})
    ut = p.trees["user"]
    upath = var(ut, "Path")
    ut.editItem(upath, 1)
    assert not editing(ut), "the value cell of a list with entries opened an editor"
    select(ut, upath.child(0), upath.child(1))
    p.delete_selected(ut)
    ut.editItem(upath, 1)
    assert editing(ut), "the value cell of an emptied list must take a value"
    escape(ut)
    print("list flag ok")

    # ---- the bottom buttons follow the active tree ----
    SYSV = {"Path": (r"C:\a", EXPAND), "S1": ("s", SZ)}
    USRV = {**UP, "U1": ("u", SZ)}
    p = scratch_page(system=SYSV, user=USRV)
    st, ut = p.trees["system"], p.trees["user"]
    select(st, top(st, "S1"))
    select(ut, top(ut, "U1"))
    ut.setFocus()
    p.btn_delete.click()
    assert [i.text(0) for i in p._top(ut)] == ["Path"] and [i.text(0) for i in p._top(st)] == ["Path", "S1"]
    p = scratch_page(system=SYSV, user=USRV, admin=False)
    st, ut = p.trees["system"], p.trees["user"]
    select(st, top(st, "S1"))
    assert not p.btn_delete.isEnabled() and not p.btn_add_var.isEnabled()
    select(ut, top(ut, "U1"))
    assert p.btn_delete.isEnabled() and p.btn_add_var.isEnabled(), "a stale System selection ruled the buttons"
    QTest.mouseClick(st.viewport(), Qt.LeftButton, NONE, at(st, top(st, "S1"), 0.5))
    assert not p.btn_delete.isEnabled() and not p.btn_add_var.isEnabled(), "a click did not activate the tree"
    print("active tree ok")

    # ---- a row keeps its own registry kind ----
    p = scratch_page(user={**UP, "PCT": ("50%", SZ), "LIT": (r"%NOT_EXPANDED%\x", SZ), "V": ("1", SZ)})
    ut = p.trees["user"]
    assert not p.pending(), [c.label for c in p.pending()]
    top(ut, "V").setText(1, "2")
    assert p.save(confirm=False) == ""
    uv = values(USR)
    assert uv["PCT"] == ("50%", SZ) and uv["LIT"] == (r"%NOT_EXPANDED%\x", SZ), uv
    top(ut, "PCT").setText(1, "60%")
    assert p.current().user["pct"].kind == EXPAND, "an edited value with % stays REG_SZ"
    p = scratch_page(user={**UP, "X": ("x", EXPAND)})
    assert not p.pending() and p.current().user["x"].kind == EXPAND, "REG_EXPAND_SZ without % lost its kind"
    print("kinds ok")

    # ---- a list whose entries are unchanged keeps its saved raw value ----
    RAWS = {"Path": (r"C:\a;C:\b;", EXPAND), "Pad": (r"C:\p1; C:\p2;;", SZ), "E": (";;", SZ)}
    p = scratch_page(system=RAWS, user={**UP, "V": ("1", SZ)})
    assert not p.pending() and "No unsaved changes" in p.status.text(), [c.label for c in p.pending()]
    p = scratch_page(system=RAWS, user={**UP, "V": ("1", SZ)}, admin=False)
    top(p.trees["user"], "V").setText(1, "2")
    assert p.save(confirm=False) == "" and values(USR)["V"] == ("2", SZ), "a raw system value blocked the save"
    p = scratch_page(system=RAWS, user=UP)
    st = p.trees["system"]
    sp = var(st, "Path")
    select(st, sp.child(0))
    press(st, Qt.Key_Delete)
    assert p.pending()
    press(st, Qt.Key_Z, CTRL)
    assert not p.pending() and "No unsaved changes" in p.status.text(), "undo to the start left changes"
    assert p.current().system["path"].value == r"C:\a;C:\b;"
    print("raw values ok")

    # ---- empty-area menu: Paste only with a variable row current ----
    p = scratch_page(user={**UP, "DIRS": (r"C:\a;C:\b", SZ)})
    ut = p.trees["user"]
    dirs = var(ut, "DIRS")
    select(ut, dirs.child(0))
    assert menu_texts(p.build_menu(ut, None)) == ["Add variable"]
    select(ut, dirs)
    assert menu_texts(p.build_menu(ut, None)) == ["Add variable", "Paste"]
    print("empty menu ok")

    # ---- Remove missing / duplicates only touch the selection's variables ----
    p = scratch_page(user={"Path": (r"C:\u;c:\U", EXPAND), "DIRS": (r"C:\a;C:\a;C:\b", SZ),
                           "MORE": (r"C:\m;C:\m", SZ), "PLAIN": ("plain", SZ)})
    ut = p.trees["user"]
    dirs, more = var(ut, "DIRS"), var(ut, "MORE")
    select(ut, dirs.child(0), dirs.child(1))
    assert p.remove_duplicates(ut) == 1 and texts(dirs) == [r"C:\a", r"C:\b"]
    assert texts(top(ut, "Path")) == [r"C:\u", r"c:\U"] and texts(more) == [r"C:\m", r"C:\m"], "other lists touched"
    select(ut, top(ut, "PLAIN"))
    assert p.remove_duplicates(ut) == 0 and texts(more) == [r"C:\m", r"C:\m"]
    select(ut, top(ut, "Path"), more.child(0))
    assert p.remove_duplicates(ut) == 2 and texts(more) == [r"C:\m"] and texts(top(ut, "Path")) == [r"C:\u"]
    p = scratch_page(user={"Path": (r"C:\n1;C:\n2", EXPAND), "DIRS": (r"C:\a;C:\b", SZ)})
    ut = p.trees["user"]
    dirs = var(ut, "DIRS")
    select(ut, dirs.child(0), dirs.child(1))
    assert p.remove_missing(ut) == 2 and texts(var(ut, "Path")) == [r"C:\n1", r"C:\n2"], "missing hit another list"
    ut.clearSelection()
    assert p.remove_missing(ut) == 2 and texts(var(ut, "Path")) == [], "nothing selected means every list"
    print("targets ok")

    # ---- a rename onto a deleted name keeps the row's own kind through undo and redo ----
    p = scratch_page(user={**UP, "XX": ("x1", SZ), "YY": ("y1", EXPAND)})
    ut = p.trees["user"]
    select(ut, top(ut, "XX"))
    p.delete_selected(ut)
    top(ut, "YY").setText(0, "XX")
    assert p.current().user["xx"].kind == EXPAND
    p.undo()
    p.undo()
    p.redo()
    p.redo()
    assert p.current().user["xx"].kind == EXPAND and p.current().user["xx"].value == "y1"
    assert p.current().as_json() == p._hist[p._hpos].as_json()
    assert p.save(confirm=False) == "" and values(USR)["XX"] == ("y1", EXPAND), values(USR)["XX"]
    print("kind flip ok")

    # ---- entry rows never open an editor in the Variable column ----
    p = scratch_page(user={**UP, "DIRS": (r"C:\a;C:\b", SZ)})
    ut = p.trees["user"]
    dirs = var(ut, "DIRS")
    app.processEvents()
    ut.editItem(dirs.child(0), 0)
    assert not editing(ut), "editItem opened the Variable cell of an entry"
    QTest.mouseDClick(ut.viewport(), Qt.LeftButton, NONE, at(ut, dirs.child(0), 0.5))
    assert not editing(ut), "a double-click opened the Variable cell of an entry"
    select(ut, dirs.child(0))
    press(ut, Qt.Key_Insert)
    QTest.keyClicks(editor(ut), r"C:\tab")
    QTest.keyClick(editor(ut), Qt.Key_Tab)
    app.processEvents()
    assert not editing(ut), "Tab moved the editor on"
    assert texts(dirs) == [r"C:\a", r"C:\tab", r"C:\b"] and all(dirs.child(i).text(0) == "" for i in range(3))
    print("entry cells ok")
finally:
    QFileDialog.getExistingDirectory = real_dialog
    os.startfile = real_startfile
    teardown()
    shutil.rmtree(SNAPS, ignore_errors=True)
    os.environ.clear()
    os.environ.update(saved_environ)

assert envedit.load().as_json() == before_real, "the real Environment keys changed!"
print("real Environment untouched")
print("STATUS: SUCCESS")
