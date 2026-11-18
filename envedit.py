"""envedit.py - the Environment tab: system and user variables, PATH-style
lists split one entry per row, missing folders flagged, like Rapid
Environment Editor.

Saving writes only the values that changed and never deletes either
Environment key. Both keys are snapshotted to JSON before every save and
whenever the tab sees them change, so any later loss can be undone from
Snapshots. After a save the change is broadcast (WM_SETTINGCHANGE
"Environment") so newly started programs see it, and wintools's own
environment is reloaded.
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import threading
import time
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QDragLeaveEvent, QPainter, QPen
from PyQt5.QtWidgets import (
    QAbstractItemDelegate, QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMenu, QMessageBox, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

import clean

HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
SYSTEM_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
USER_KEY = "Environment"
SNAPSHOT_DIR = clean.CONFIG_DIR / "env-snapshots"
# removing one of these needs an explicit yes; an empty Path is refused outright
CRITICAL = {"path", "comspec", "pathext", "windir", "os", "temp", "tmp", "psmodulepath",
            "number_of_processors", "processor_architecture", "driverdata"}
# variables whose value is a ;-separated list even with a single entry
LIST_NAMES = {"path", "pathext", "psmodulepath"}


@dataclass(frozen=True)
class Roots:
    """The two keys; the tests point them at scratch keys under HKCU."""
    system: tuple = (HKLM, SYSTEM_KEY)
    user: tuple = (HKCU, USER_KEY)
    snapshots: Path = SNAPSHOT_DIR


ROOTS = Roots()
SCOPES = ("system", "user")


@dataclass
class Var:
    name: str
    value: str
    kind: int = winreg.REG_EXPAND_SZ

    @property
    def is_list(self):
        return self.name.lower() in LIST_NAMES or ";" in self.value

    @property
    def entries(self):
        return split_list(self.value)


@dataclass
class Change:
    scope: str
    name: str
    old: Var | None
    new: Var | None

    @property
    def label(self):
        if self.old is None:
            return f"add {self.scope} {self.name}"
        if self.new is None:
            return f"remove {self.scope} {self.name}"
        return f"change {self.scope} {self.name}"


@dataclass
class Env:
    system: dict = field(default_factory=dict)   # lower name -> Var
    user: dict = field(default_factory=dict)

    def scope(self, name):
        return getattr(self, name)

    def as_json(self):
        return {s: {v.name: [v.kind, v.value] for v in self.scope(s).values()} for s in SCOPES}

    @classmethod
    def from_json(cls, data):
        env = cls()
        for s in SCOPES:
            for name, (kind, value) in data.get(s, {}).items():
                env.scope(s)[name.lower()] = Var(name, value, kind)
        return env


def split_list(value):
    return [p for p in value.split(";") if p.strip()]


def join_list(entries):
    return ";".join(e.strip() for e in entries if e.strip())


# ====================================================================
#  registry
# ====================================================================

def _read_key(hive, key):
    out = {}
    try:
        with winreg.OpenKey(hive, key) as k:
            i = 0
            while True:
                try:
                    name, value, kind = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and name:
                    out[name.lower()] = Var(name, value, kind)
    except FileNotFoundError:
        pass
    return out


def load(roots=ROOTS):
    return Env(_read_key(*roots.system), _read_key(*roots.user))


def diff(old, new):
    changes = []
    for s in SCOPES:
        a, b = old.scope(s), new.scope(s)
        for key in sorted(set(a) | set(b)):
            va, vb = a.get(key), b.get(key)
            if va is None or vb is None or (va.name, va.value, va.kind) != (vb.name, vb.value, vb.kind):
                changes.append(Change(s, (vb or va).name, va, vb))
    return changes


def check(changes):
    """Problems that stop a save (empty Path), and the critical removals that
    need a yes first."""
    errors, critical = [], []
    for c in changes:
        low = c.name.lower()
        if c.new is not None and low == "path" and c.scope == "system" and not c.new.value.strip():
            errors.append("the system Path would be empty")
        if c.new is None and low in CRITICAL and c.scope == "system":
            critical.append(c.name)
    return errors, critical


def write(changes, roots=ROOTS):
    """Applies changes value by value; the keys themselves are only ever
    opened (created when missing), never deleted."""
    for c in changes:
        hive, key = getattr(roots, c.scope)
        with winreg.CreateKeyEx(hive, key, 0, winreg.KEY_SET_VALUE) as k:
            if c.new is None:
                try:
                    winreg.DeleteValue(k, c.old.name)
                except FileNotFoundError:
                    pass
            else:
                if c.old is not None and c.old.name != c.new.name:
                    try:
                        winreg.DeleteValue(k, c.old.name)
                    except FileNotFoundError:
                        pass
                winreg.SetValueEx(k, c.new.name, 0, c.new.kind, c.new.value)


# ====================================================================
#  snapshots
# ====================================================================

def snapshots(roots=ROOTS):
    try:
        return sorted(roots.snapshots.glob("env_*.json"), reverse=True)
    except OSError:
        return []


def snapshot(env, reason, roots=ROOTS):
    """Saves env unless it equals the newest snapshot; returns the file or None."""
    data = env.as_json()
    latest = snapshots(roots)
    if latest:
        try:
            if json.loads(latest[0].read_text(encoding="utf-8"))["env"] == data:
                return None
        except (OSError, ValueError, KeyError):
            pass
    roots.snapshots.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = roots.snapshots / f"env_{stamp}_{reason}.json"
    n = 1
    while path.exists():
        n += 1
        path = roots.snapshots / f"env_{stamp}_{reason}_{n}.json"
    path.write_text(json.dumps({"taken": stamp, "reason": reason, "env": data}, indent=1),
                    encoding="utf-8")
    return path


def read_snapshot(path):
    return Env.from_json(json.loads(Path(path).read_text(encoding="utf-8"))["env"])


# ====================================================================
#  refresh
# ====================================================================

WM_SETTINGCHANGE, HWND_BROADCAST, SMTO_ABORTIFHUNG = 0x001A, 0xFFFF, 0x0002
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPCWSTR, wt.UINT,
                                        wt.UINT, ctypes.POINTER(ctypes.c_size_t)]
_user32.SendMessageTimeoutW.restype = ctypes.c_size_t


def broadcast():
    """Tells Explorer and every top-level window the environment changed, so
    programs started from now on get the new values."""
    result = ctypes.c_size_t()
    return bool(_user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
                                            SMTO_ABORTIFHUNG, 5000, ctypes.byref(result)))


def _expand(value, env):
    out = value
    for _ in range(3):   # nested %VAR% references
        nxt = os.path.expandvars(out) if env is None else _expand_with(out, env)
        if nxt == out:
            break
        out = nxt
    return out


def _expand_with(value, env):
    return re.sub(r"%([^%;]+)%", lambda m: env.get(m.group(1).upper(), m.group(0)), value)


def merged(env):
    """The environment a newly started program gets: process-built values,
    then system variables, then user variables, the two Paths joined."""
    base = {k.upper(): v for k, v in os.environ.items()
            if k.upper() in ("SYSTEMROOT", "SYSTEMDRIVE", "USERPROFILE", "USERNAME", "APPDATA",
                             "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
                             "COMPUTERNAME", "HOMEDRIVE", "HOMEPATH", "PUBLIC", "ALLUSERSPROFILE",
                             "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "PROGRAMW6432",
                             "COMMONPROGRAMW6432", "USERDOMAIN")}
    out = dict(base)
    for scope in SCOPES:
        for v in env.scope(scope).values():
            value = _expand(v.value, out) if v.kind == winreg.REG_EXPAND_SZ else v.value
            if v.name.upper() == "PATH" and scope == "user" and out.get("PATH"):
                value = out["PATH"].rstrip(";") + ";" + value
            out[v.name.upper()] = value
    return out


def refresh_process(env):
    """Reloads wintools's own environment, so programs it starts see the change."""
    new = merged(env)
    keep = set(new)
    for name in list(os.environ):
        up = name.upper()
        if up not in keep and up in {v.name.upper() for s in SCOPES for v in env.scope(s).values()}:
            del os.environ[name]
    os.environ.update(new)


def entry_state(entry, env_vars):
    """"missing" for a path that does not exist, "" otherwise (non-paths too)."""
    text = entry.strip().strip('"')
    if not text or not (":" in text[:3] or text.startswith(("%", "\\\\"))):
        return ""
    expanded = _expand(text, env_vars)
    if "%" in expanded:
        return "unresolved"
    return "" if os.path.exists(expanded) else "missing"


# ====================================================================
#  PAGE
# ====================================================================

# data on a variable row: the last accepted name (COL_NAME), and on COL_VALUE the registry
# type, the raw value the row was built from, and whether it is a list row
NAME, KIND, ORIG, LIST = Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3
COL_NAME, COL_VALUE = 0, 1
RED, ORANGE, GRAY = QColor("#b00000"), QColor("#b06000"), QColor("gray")


class EnvTree(QTreeWidget):
    def __init__(self, scope, page):
        super().__init__()
        self.scope = scope
        self.page = page
        self._drag_items = []     # set only while this tree is the source of a running drag
        self._drop_y = None
        self.setHeaderLabels(["Variable", "Value"])
        self.setColumnWidth(COL_NAME, 170)
        self.header().setSectionResizeMode(COL_VALUE, QHeaderView.Stretch)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.setTextElideMode(Qt.ElideMiddle)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDropIndicatorShown(False)   # drawn in paintEvent, only where a drop is accepted
        p = page
        self._read_keys = {(Qt.Key_C, True, False): lambda: p.copy_selection(self)}
        self._edit_keys = {
            **self._read_keys,
            (Qt.Key_X, True, False): lambda: p.cut_selection(self),
            (Qt.Key_V, True, False): lambda: p.paste(self),
            (Qt.Key_Delete, False, False): lambda: p.delete_selected(self),
            (Qt.Key_Insert, False, False): lambda: p.add_entry(tree=self),
            (Qt.Key_F2, False, False): lambda: p.edit_current(self),
            (Qt.Key_Return, False, False): lambda: p.edit_current(self),
            (Qt.Key_Enter, False, False): lambda: p.edit_current(self),
            (Qt.Key_Up, True, False): lambda: p.move_entry(-1, self),
            (Qt.Key_Down, True, False): lambda: p.move_entry(1, self),
            (Qt.Key_Home, True, False): lambda: p.move_to_edge(True, self),
            (Qt.Key_End, True, False): lambda: p.move_to_edge(False, self),
            (Qt.Key_Z, True, False): p.undo,
            (Qt.Key_Y, True, False): p.redo,
            (Qt.Key_Z, True, True): p.redo,
        }

    # an open line editor keeps every key, Ctrl+Z included
    def keyPressEvent(self, ev):
        mod = ev.modifiers()
        combo = (ev.key(), bool(mod & Qt.ControlModifier), bool(mod & Qt.ShiftModifier))
        keys = self._edit_keys if self.page.writable(self) else self._read_keys
        action = None if mod & Qt.AltModifier or self.state() == QAbstractItemView.EditingState \
            else keys.get(combo)
        if action is None:
            super().keyPressEvent(ev)
            return
        ev.accept()
        action()

    def closeEditor(self, editor, hint):
        # Tab commits and stops; moving on would open editors in cells that take no input
        if hint in (QAbstractItemDelegate.EditNextItem, QAbstractItemDelegate.EditPreviousItem):
            hint = QAbstractItemDelegate.NoHint
        super().closeEditor(editor, hint)
        self.page.editor_closed()

    def edit(self, index, trigger=None, event=None):
        item = self.itemFromIndex(index)
        if item is not None and not self.page.cell_editable(item, index.column()):
            return False
        if trigger is None:
            return super().edit(index)
        return super().edit(index, trigger, event)

    def mousePressEvent(self, ev):
        self.page.activate(self)
        super().mousePressEvent(ev)

    def focusInEvent(self, ev):
        self.page.activate(self)
        super().focusInEvent(ev)

    def contextMenuEvent(self, ev):
        item = self.itemAt(ev.pos())
        if item is not None and not item.isSelected():
            self.setCurrentItem(item)
        menu = self.page.build_menu(self, item)
        if menu.actions():
            menu.exec_(ev.globalPos())
        menu.deleteLater()

    # ---- drag and drop: entries of one variable, reordered within it ----
    def drop_target(self, items, pos):
        """(variable, index) where dropping items at viewport pos lands, None when refused."""
        if not items or not self.page.writable(self):
            return None
        var = items[0].parent()
        if var is None or any(it.parent() is not var for it in items):
            return None
        target = self.itemAt(pos)
        if target is var:
            return var, var.childCount()
        if target is None or target.parent() is not var:
            return None
        i = var.indexOfChild(target)
        return var, i if pos.y() < self.visualItemRect(target).center().y() else i + 1

    def startDrag(self, actions):
        self._drag_items = self.selectedItems()
        try:
            super().startDrag(actions)
        finally:
            self._drag_items = []

    def dragEnterEvent(self, ev):
        super().dragEnterEvent(ev)
        if not self._drag_items:
            ev.ignore()

    def dragMoveEvent(self, ev):
        super().dragMoveEvent(ev)   # auto-scroll
        target = self.drop_target(self._drag_items, ev.pos())
        self._set_drop_line(target)
        ev.ignore() if target is None else ev.accept()

    def dragLeaveEvent(self, ev):
        super().dragLeaveEvent(ev)
        self._set_drop_line(None)

    def dropEvent(self, ev):
        target = self.drop_target(self._drag_items, ev.pos())
        items = self._drag_items
        self.dragLeaveEvent(QDragLeaveEvent())   # stops the auto-scroll, ends the drag state, clears the line
        if target is None:
            ev.ignore()
            return
        self.page.move_entries(items, target[1])
        ev.setDropAction(Qt.CopyAction)   # the move is done; a Move result makes the view delete the source rows
        ev.accept()

    def _set_drop_line(self, target):
        if target is None:
            self._drop_y = None
        else:
            var, index = target
            if index < var.childCount():
                self._drop_y = self.visualItemRect(var.child(index)).top()
            else:
                self._drop_y = self.visualItemRect(var.child(var.childCount() - 1)).bottom() + 1
        self.viewport().update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self._drop_y is not None:
            painter = QPainter(self.viewport())
            painter.setPen(QPen(self.palette().highlight().color(), 2))
            painter.drawLine(0, self._drop_y, self.viewport().width(), self._drop_y)


class EnvPage(QWidget):
    refreshed = pyqtSignal(str, bool)

    def __init__(self, parent=None, roots=ROOTS):
        super().__init__(parent)
        self.roots = roots
        self.refreshed.connect(self._refreshed)
        self.saved = Env()           # what the registry held at the last load/save
        self._built = False
        self._filling = False
        self._hist = [self.saved]    # Env states, the saved one first
        self._hpos = 0
        self._fresh = None           # row just inserted, still waiting for its first text
        self._next_edit = None       # (item, column) to open once the current editor has closed

        self.btn_reload = QPushButton("Reload")
        self.btn_broadcast = QPushButton("Refresh environment")
        self.cmb_snap = QComboBox()
        self.cmb_snap.setMinimumWidth(260)
        self.btn_restore = QPushButton("Restore snapshot")
        self.lbl_admin = QLabel()
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.btn_reload)
        top.addWidget(self.btn_broadcast)
        top.addSpacing(12)
        top.addWidget(QLabel("Snapshots:"))
        top.addWidget(self.cmb_snap)
        top.addWidget(self.btn_restore)
        top.addStretch(1)
        top.addWidget(self.lbl_admin)

        self.trees = {s: EnvTree(s, self) for s in SCOPES}
        split = QSplitter(Qt.Horizontal)
        for scope, title in (("system", "System variables"), ("user", "User variables")):
            box = QWidget()
            bv = QVBoxLayout(box)
            bv.setContentsMargins(0, 0, 0, 0)
            bv.setSpacing(2)
            lbl = QLabel(title)
            f = lbl.font()
            f.setBold(True)
            lbl.setFont(f)
            bv.addWidget(lbl)
            bv.addWidget(self.trees[scope], 1)
            split.addWidget(box)
            split.setStretchFactor(split.count() - 1, 1)

        self.btn_add_var = QPushButton("Add variable")
        self.btn_add_entry = QPushButton("Add entry")
        self.btn_folder = QPushButton("Add folder...")
        self.btn_delete = QPushButton("Delete")
        self.btn_up = QPushButton("Up")
        self.btn_down = QPushButton("Down")
        self.btn_clean = QPushButton("Remove missing")
        self.btn_dups = QPushButton("Remove duplicates")
        self.btn_save = QPushButton("Save")
        self.btn_revert = QPushButton("Revert")
        self.status = QLabel()
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        for b in (self.btn_add_var, self.btn_add_entry, self.btn_folder, self.btn_delete, self.btn_up,
                  self.btn_down, self.btn_clean, self.btn_dups):
            bottom.addWidget(b)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.btn_revert)
        bottom.addWidget(self.btn_save)

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        v.addLayout(top)
        v.addWidget(split, 1)
        v.addLayout(bottom)

        self.btn_reload.clicked.connect(lambda: self.reload())
        self.btn_broadcast.clicked.connect(lambda: self.refresh_environment())
        self.btn_restore.clicked.connect(lambda: self.restore_snapshot())
        self.btn_add_var.clicked.connect(lambda: self.add_variable())
        self.btn_add_entry.clicked.connect(lambda: self.add_entry())
        self.btn_folder.clicked.connect(lambda: self.add_folder())
        self.btn_delete.clicked.connect(lambda: self.delete_selected())
        self.btn_up.clicked.connect(lambda: self.move_entry(-1))
        self.btn_down.clicked.connect(lambda: self.move_entry(1))
        self.btn_clean.clicked.connect(lambda: self.remove_missing())
        self.btn_dups.clicked.connect(lambda: self.remove_duplicates())
        self.btn_save.clicked.connect(lambda: self.save())
        self.btn_revert.clicked.connect(lambda: self.reload())
        self._active = self.trees["user"]   # the tree the bottom row acts on
        for tree in self.trees.values():
            tree.itemChanged.connect(self._edited)
            tree.itemSelectionChanged.connect(lambda t=tree: self._tree_selected(t))
        self._selection_changed()

    # ---- load / fill ----
    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._built:
            self._built = True
            self.reload()

    def can_write_system(self):
        return bool(ctypes.windll.shell32.IsUserAnAdmin()) or self.roots.system[0] != HKLM

    def writable(self, tree):
        return tree.scope == "user" or self.can_write_system()

    def reload(self):
        self.saved = load(self.roots)
        snapshot(self.saved, "seen", self.roots)   # a no-op unless something changed it
        self._fill(self.saved)
        self._hist, self._hpos = [self.saved], 0
        self._fill_snapshots()
        self.lbl_admin.setText("" if self.can_write_system() else "system read-only")
        self._show_pending()

    def _fill(self, env):
        self._filling = True
        self._fresh = self._next_edit = None
        names = merged(env)
        for scope, tree in self.trees.items():
            expanded = {it.data(COL_NAME, NAME).lower() for it in self._top(tree)
                        if it.isExpanded()}
            tree.clear()
            writable = self.writable(tree)
            for var in sorted(env.scope(scope).values(), key=lambda v: v.name.lower()):
                self._add_var_item(tree, var, writable, names)
            for it in self._top(tree):
                if it.data(COL_NAME, NAME).lower() in expanded or (
                        it.data(COL_NAME, NAME).lower() == "path"):
                    it.setExpanded(True)
        self._filling = False
        self._selection_changed()   # the refill cleared the selection without a signal

    def _flags(self, writable):
        f = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        return f | Qt.ItemIsEditable if writable else f

    def _add_var_item(self, tree, var, writable, names):
        it = QTreeWidgetItem([var.name, "" if var.is_list else var.value])
        it.setData(COL_NAME, NAME, var.name)
        it.setData(COL_NAME, LIST, var.is_list)
        it.setData(COL_VALUE, KIND, var.kind)
        it.setData(COL_VALUE, ORIG, var.value)
        it.setFlags(self._flags(writable))
        f = it.font(COL_NAME)
        f.setBold(True)
        it.setFont(COL_NAME, f)
        tree.addTopLevelItem(it)
        if var.is_list:
            for entry in var.entries:
                self._add_entry_item(it, entry, writable)
            self._mark(it, names)
        else:
            self._mark_single(it, names)
        return it

    def _add_entry_item(self, parent, text, writable, index=None):
        child = QTreeWidgetItem(["", text])
        child.setFlags(self._flags(writable) | (Qt.ItemIsDragEnabled if writable else Qt.NoItemFlags))
        if index is None:
            parent.addChild(child)
        else:
            parent.insertChild(index, child)
        return child

    @staticmethod
    def _top(tree):
        return [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]

    def _mark(self, var_item, names):
        seen = set()
        missing = 0
        for i in range(var_item.childCount()):
            c = var_item.child(i)
            text = c.text(COL_VALUE)
            state = entry_state(text, names)
            key = text.strip().rstrip("\\").lower()
            if state == "missing":
                missing += 1
                c.setForeground(COL_VALUE, QBrush(RED))
            elif key in seen:
                c.setForeground(COL_VALUE, QBrush(ORANGE))
            elif state == "unresolved":
                c.setForeground(COL_VALUE, QBrush(GRAY))
            else:
                c.setForeground(COL_VALUE, QBrush())
            c.setToolTip(COL_VALUE, _expand(text, names) if "%" in text else "")
            seen.add(key)
        n = var_item.childCount()
        var_item.setText(COL_VALUE, f"{n} entr{'y' if n == 1 else 'ies'}" if n else "")
        if missing:
            var_item.setText(COL_VALUE, var_item.text(COL_VALUE) + f", {missing} missing")
        var_item.setForeground(COL_VALUE, QBrush(RED if missing else GRAY))

    def _mark_single(self, it, names):
        state = entry_state(it.text(COL_VALUE), names)
        it.setForeground(COL_VALUE, QBrush(RED if state == "missing" else QColor()))
        it.setToolTip(COL_VALUE, _expand(it.text(COL_VALUE), names) if "%" in it.text(COL_VALUE) else "")

    # ---- the tree as an Env ----
    def current(self):
        env = Env()
        for scope, tree in self.trees.items():
            for it in self._top(tree):
                name = it.text(COL_NAME).strip()
                if not name:
                    continue
                value = self._var_value(it)
                kind = it.data(COL_VALUE, KIND)
                if "%" in value and value != it.data(COL_VALUE, ORIG):
                    kind = winreg.REG_EXPAND_SZ
                env.scope(scope)[name.lower()] = Var(name, value, kind)
        return env

    @staticmethod
    def _is_list(it):
        return bool(it.data(COL_NAME, LIST))

    def _var_value(self, it):
        """The variable's value; a list row is read from its entries, never from its readout.
        Entries equal to the loaded ones give the loaded raw value back untouched."""
        if not self._is_list(it):
            return it.text(COL_VALUE)
        entries = [e for e in (it.child(i).text(COL_VALUE) for i in range(it.childCount()))
                   if e.strip()]
        orig = it.data(COL_VALUE, ORIG)
        return orig if entries == split_list(orig) else join_list(entries)

    def pending(self):
        return diff(self.saved, self.current())

    def _show_pending(self, note=""):
        n = len(self.pending())
        text = f"{n} unsaved change{'' if n == 1 else 's'}" if n else "No unsaved changes"
        self.status.setText(f"{note}   {text}" if note else text)
        self.btn_save.setEnabled(bool(n))
        self.btn_revert.setEnabled(bool(n))

    # ---- history ----
    def _record(self):
        """Pushes the tree's state after a completed mutation, unless nothing changed."""
        cur = self.current()
        if cur.as_json() != self._hist[self._hpos].as_json():
            del self._hist[self._hpos + 1:]
            self._hist.append(cur)
            self._hpos += 1

    def _done(self, note=""):
        self._record()
        self._show_pending(note)

    def undo(self):
        self._step(-1)

    def redo(self):
        self._step(1)

    def _step(self, d):
        pos = self._hpos + d
        if 0 <= pos < len(self._hist):
            self._hpos = pos
            self._fill(self._hist[pos])
            self._show_pending()

    # ---- inline editing ----
    def editor_closed(self):
        """Called by the trees after any line editor closed: chains the value editor after a new
        variable's name, and drops a freshly inserted row that was left blank."""
        nxt, self._next_edit = self._next_edit, None
        if nxt is not None:
            nxt[0].treeWidget().editItem(*nxt)
            return
        fresh, self._fresh = self._fresh, None
        if fresh is None or fresh.treeWidget() is None:
            return
        tree, parent = fresh.treeWidget(), fresh.parent()
        self._filling = True
        if parent is not None and not fresh.text(COL_VALUE).strip():
            parent.removeChild(fresh)
            self._mark(parent, merged(self.current()))
        elif parent is None and not fresh.text(COL_NAME).strip():
            tree.takeTopLevelItem(tree.indexOfTopLevelItem(fresh))
        self._filling = False
        self._done()

    def _commit_name(self, item):
        """Validates a committed variable name; a refused one is reverted (a new row is removed).
        Returns the status note."""
        tree = item.treeWidget()
        name = item.text(COL_NAME).strip()
        fresh = item is self._fresh
        clash = self._name_taken(tree, name, item)
        if name and not clash:
            item.setText(COL_NAME, name)
            item.setData(COL_NAME, NAME, name)
            self._sync_list(item)
            if fresh:
                self._next_edit = (item, COL_VALUE)
            return ""
        item.setText(COL_NAME, item.data(COL_NAME, NAME))
        if fresh:
            tree.takeTopLevelItem(tree.indexOfTopLevelItem(item))
            self._fresh = None
        return f"{name} already exists" if clash else ""

    def _sync_list(self, item):
        """A list name makes the row a list; the plain value it held becomes its entries."""
        if self._is_list(item) or item.text(COL_NAME).strip().lower() not in LIST_NAMES:
            return
        item.setData(COL_NAME, LIST, True)
        self._add_entries(item, item.text(COL_VALUE))

    def _add_entries(self, item, text):
        for e in split_list(text):
            self._add_entry_item(item, e, True)
        item.setExpanded(True)
        self._mark(item, merged(self.current()))

    def _edited(self, item, column):
        if self._filling:
            return
        self._filling = True
        note = ""
        names = merged(self.current())
        parent = item.parent()
        if parent is not None:
            if not item.text(COL_VALUE).strip():
                parent.removeChild(item)
            self._mark(parent, names)
        elif column == COL_NAME:
            note = self._commit_name(item)
        else:
            text = item.text(COL_VALUE)
            if ";" in text:
                item.setData(COL_NAME, LIST, True)   # a ;-list typed into a plain variable
            if not self._is_list(item):
                self._mark_single(item, names)
            elif item.childCount():
                self._mark(item, names)
            else:
                self._add_entries(item, text)   # a value typed into a list without entries
        self._filling = False
        if self._next_edit is None:   # a new variable is recorded once its value is settled
            self._record()
        self._show_pending(note)

    # ---- selection-driven actions ----
    def _focus_tree(self):
        return self._active

    def activate(self, tree):
        """Makes tree the one the bottom row acts on (a click, focus or a selection change)."""
        if tree is not self._active:
            self._active = tree
            self._selection_changed()

    def _tree_selected(self, tree):
        if not self._filling:
            self._active = tree
        self._selection_changed()

    def cell_editable(self, item, column):
        """Entries take input in the value cell only; a list with entries is edited through them."""
        if item.parent() is not None:
            return column == COL_VALUE
        return column == COL_NAME or not (self._is_list(item) and item.childCount())

    def _selection_changed(self):
        tree = self._focus_tree()
        writable = self.writable(tree)
        anchored = writable and self._anchor(tree) is not None
        block = writable and self._selected_block(tree) is not None
        self.btn_add_var.setEnabled(writable)
        self.btn_add_entry.setEnabled(anchored)
        self.btn_folder.setEnabled(anchored)
        self.btn_delete.setEnabled(writable and bool(tree.selectedItems()))
        self.btn_up.setEnabled(block)
        self.btn_down.setEnabled(block)
        self.btn_clean.setEnabled(writable)
        self.btn_dups.setEnabled(writable)

    def _tree(self, tree):
        return tree if tree is not None else self._focus_tree()

    @staticmethod
    def _go(tree, item):
        """Makes item the only selected and current row."""
        tree.clearSelection()
        tree.setCurrentItem(item)

    @staticmethod
    def _ordered(items):
        def pos(it):
            p = it.parent()
            t = p or it
            return t.treeWidget().indexOfTopLevelItem(t), -1 if p is None else p.indexOfChild(it)
        return sorted(items, key=pos)

    def _anchor(self, tree):
        """The current item, or the last selected one when the current item is not selected."""
        cur, sel = tree.currentItem(), self._ordered(tree.selectedItems())
        return sel[-1] if sel and not any(cur is s for s in sel) else cur

    def _selected_block(self, tree):
        """(variable, entries) when the selection is entries of one variable, else None."""
        items = self._ordered(tree.selectedItems())
        if not items or items[0].parent() is None or any(
                it.parent() is not items[0].parent() for it in items):
            return None
        return items[0].parent(), items

    def _name_taken(self, tree, name, skip=None):
        return any(o is not skip and o.text(COL_NAME).strip().lower() == name.lower()
                   for o in self._top(tree))

    def add_variable(self, scope=None, name=None, value=None):
        """Without a name: a blank row whose name editor opens, then its value editor."""
        tree = self.trees[scope] if scope else self._focus_tree()
        if not self.writable(tree):
            return None
        if name is None:
            return self._new_variable(tree)
        name = name.strip()
        if self._name_taken(tree, name):
            self._show_pending(f"{name} already exists")
            return None
        self._filling = True
        var = Var(name, value or "", winreg.REG_EXPAND_SZ if "%" in (value or "") else winreg.REG_SZ)
        it = self._add_var_item(tree, var, True, merged(self.current()))
        it.setExpanded(True)
        self._filling = False
        self._go(tree, it)
        self._done()
        return it

    def _new_variable(self, tree):
        self._filling = True
        it = self._add_var_item(tree, Var("", "", winreg.REG_SZ), True, merged(self.current()))
        self._filling = False
        self._fresh = it
        self._go(tree, it)
        tree.scrollToItem(it)
        tree.editItem(it, COL_NAME)
        return it

    def _insert(self, anchor, texts, above=False):
        """Adds entries after (or above) the anchor entry, or at the end of the anchor variable."""
        var = anchor.parent() or anchor
        self._filling = True
        if not self._is_list(var):
            # a plain value becomes the first entry of a list
            var.setData(COL_NAME, LIST, True)
            if var.text(COL_VALUE).strip():
                self._add_entry_item(var, var.text(COL_VALUE), True)
        index = None if anchor.parent() is None else var.indexOfChild(anchor) + (0 if above else 1)
        items = [self._add_entry_item(var, t, True, None if index is None else index + k)
                 for k, t in enumerate(texts)]
        var.setExpanded(True)
        self._mark(var, merged(self.current()))
        self._filling = False
        return items

    def add_entry(self, text=None, tree=None, above=False):
        """Without text: a blank row whose editor opens."""
        tree = self._tree(tree)
        anchor = self._anchor(tree)
        if anchor is None or not self.writable(tree):
            return None
        (item,) = self._insert(anchor, ["" if text is None else text.strip()], above)
        self._go(tree, item)
        if text is None:
            self._fresh = item
            tree.scrollToItem(item)
            tree.editItem(item, COL_VALUE)
        else:
            self._done()
        return item

    def edit_current(self, tree=None):
        tree = self._tree(tree)
        item = self._anchor(tree)
        if item is None or not self.writable(tree):
            return
        tree.editItem(item, COL_NAME if item.parent() is None and item.childCount() else COL_VALUE)

    def _expanded_text(self, entry):
        return _expand(entry.text(COL_VALUE).strip().strip('"'), merged(self.current()))

    def _pick_folder(self, entry=None):
        start = self._expanded_text(entry) if entry is not None else ""
        folder = QFileDialog.getExistingDirectory(self, "Browse for folder",
                                                  start if os.path.isdir(start) else "")
        return folder.replace("/", "\\")

    def browse_entry(self, tree=None):
        tree = self._tree(tree)
        item = self._anchor(tree)
        if item is None or item.parent() is None or not self.writable(tree):
            return None
        path = self._pick_folder(item)
        if not path:
            return None
        self._filling = True
        item.setText(COL_VALUE, path)
        self._mark(item.parent(), merged(self.current()))
        self._filling = False
        self._done()
        return path

    def add_folder(self, tree=None):
        tree = self._tree(tree)
        anchor = self._anchor(tree)
        if anchor is None or not self.writable(tree):
            return None
        path = self._pick_folder(anchor if anchor.parent() is not None else None)
        if not path:
            return None
        (item,) = self._insert(anchor, [path])
        self._go(tree, item)
        self._done()
        return item

    def open_in_explorer(self, tree=None):
        item = self._anchor(self._tree(tree))
        if item is None or item.parent() is None:
            return None
        path = self._expanded_text(item)
        if not os.path.exists(path):
            self._show_pending(f"not found: {path}")
            return None
        # a file entry opens its folder; startfile on the file itself would run it
        os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
        return path

    def delete_selected(self, tree=None):
        tree = self._tree(tree)
        sel = self._ordered(tree.selectedItems())
        if not sel or not self.writable(tree):
            return
        gone = {id(it) for it in sel}
        gone |= {id(it.child(i)) for it in sel if it.parent() is None for i in range(it.childCount())}
        # the row after the last deleted one (else the one before the first) becomes current
        nxt = tree.itemBelow(sel[-1])
        while nxt is not None and id(nxt) in gone:
            nxt = tree.itemBelow(nxt)
        if nxt is None:
            nxt = tree.itemAbove(sel[0])
            while nxt is not None and id(nxt) in gone:
                nxt = tree.itemAbove(nxt)
        self._filling = True
        parents = set()
        for it in sel:
            if it.parent() is not None:
                parents.add(id(it.parent()))
                it.parent().removeChild(it)
            else:
                tree.takeTopLevelItem(tree.indexOfTopLevelItem(it))
        names = merged(self.current())
        for it in self._top(tree):
            if id(it) in parents:
                self._mark(it, names)
        self._filling = False
        if nxt is not None:
            self._go(tree, nxt)
        self._done()

    def move_entry(self, step, tree=None):
        """Moves the selected entries of one variable by one row each; blocked at the ends."""
        tree = self._tree(tree)
        block = self._selected_block(tree)
        if block is None or not self.writable(tree):
            return False
        parent, items = block
        kids = [parent.child(i) for i in range(parent.childCount())]
        ids = {id(it) for it in items}
        hit = [id(k) in ids for k in kids]
        if step < 0:
            if hit[0]:
                return False
            for i in range(1, len(kids)):
                if hit[i]:
                    kids[i - 1], kids[i] = kids[i], kids[i - 1]
        else:
            if hit[-1]:
                return False
            for i in range(len(kids) - 2, -1, -1):
                if hit[i]:
                    kids[i], kids[i + 1] = kids[i + 1], kids[i]
        return self._reorder(tree, parent, kids, items)

    def move_to_edge(self, top, tree=None):
        tree = self._tree(tree)
        block = self._selected_block(tree)
        if block is None:
            return False
        return self.move_entries(block[1], 0 if top else block[0].childCount())

    def move_entries(self, items, index):
        """Moves entries of one variable, in tree order, in front of the child now at index."""
        parent = items[0].parent() if items else None
        if parent is None or any(it.parent() is not parent for it in items) or not (
                0 <= index <= parent.childCount()):
            raise ValueError("move_entries needs entries of one variable and an index inside it")
        tree = parent.treeWidget()
        if not self.writable(tree):
            return False
        ids = {id(it) for it in items}
        kids = [parent.child(i) for i in range(parent.childCount())]
        moved = [k for k in kids if id(k) in ids]
        order = ([k for k in kids[:index] if id(k) not in ids] + moved
                 + [k for k in kids[index:] if id(k) not in ids])
        return self._reorder(tree, parent, order, moved)

    def _reorder(self, tree, parent, order, keep):
        """Rebuilds the children in the given order, keeping the moved ones selected."""
        if all(k is parent.child(i) for i, k in enumerate(order)):
            return False
        cur = tree.currentItem()
        cur = cur if any(cur is k for k in keep) else keep[0]
        self._filling = True
        parent.takeChildren()
        parent.addChildren(order)
        self._mark(parent, merged(self.current()))
        self._filling = False
        self._go(tree, cur)
        for it in keep:
            it.setSelected(True)
        self._done()
        return True

    # ---- clipboard ----
    def copy_selection(self, tree=None):
        sel = self._ordered(self._tree(tree).selectedItems())
        entries = [it for it in sel if it.parent() is not None]
        text = "\n".join(it.text(COL_VALUE) for it in entries) if entries else \
            "\n".join(self._var_value(it) for it in sel)
        if sel:
            QApplication.clipboard().setText(text)
        return text

    def cut_selection(self, tree=None):
        tree = self._tree(tree)
        if not self.writable(tree):
            return ""
        text = self.copy_selection(tree)
        self.delete_selected(tree)
        return text

    def paste(self, tree=None):
        tree = self._tree(tree)
        anchor = self._anchor(tree)
        if anchor is None or not self.writable(tree):
            return []
        texts = [t.strip() for t in re.split(r"[;\r\n]+", QApplication.clipboard().text()) if t.strip()]
        if not texts:
            return []
        items = self._insert(anchor, texts)
        self._go(tree, items[-1])
        for it in items:
            it.setSelected(True)
        self._done()
        return items

    # ---- list cleanup ----
    def _list_targets(self, tree):
        """The list variables the selection belongs to; every list when nothing is selected."""
        sel = tree.selectedItems()
        if not sel:
            return [it for it in self._top(tree) if self._is_list(it)]
        owners = {id(it.parent() or it): it.parent() or it for it in sel}
        return [v for v in self._top(tree) if id(v) in owners and self._is_list(v)]

    def remove_missing(self, tree=None):
        tree = self._tree(tree)
        if not self.writable(tree):
            return 0
        names = merged(self.current())
        gone = 0
        self._filling = True
        for var in self._list_targets(tree):
            before = var.childCount()
            for i in reversed(range(before)):
                if entry_state(var.child(i).text(COL_VALUE), names) == "missing":
                    var.removeChild(var.child(i))
            if var.childCount() != before:
                gone += before - var.childCount()
                self._mark(var, names)
        self._filling = False
        self._done(f"Removed {gone} missing entr{'y' if gone == 1 else 'ies'}")
        return gone

    def remove_duplicates(self, tree=None):
        tree = self._tree(tree)
        if not self.writable(tree):
            return 0
        names = merged(self.current())
        gone = 0
        self._filling = True
        for var in self._list_targets(tree):
            before, seen = var.childCount(), set()
            for child in [var.child(i) for i in range(before)]:
                key = child.text(COL_VALUE).strip().rstrip("\\").lower()
                if key in seen:
                    var.removeChild(child)
                seen.add(key)
            if var.childCount() != before:
                gone += before - var.childCount()
                self._mark(var, names)
        self._filling = False
        self._done(f"Removed {gone} duplicate entr{'y' if gone == 1 else 'ies'}")
        return gone

    # ---- context menu ----
    def build_menu(self, tree, item):
        menu = QMenu(tree)

        def add(label, fn, keys=""):
            menu.addAction(f"{label}\t{keys}" if keys else label).triggered.connect(
                lambda _checked=False: fn())

        copy = ("Copy", lambda: self.copy_selection(tree), "Ctrl+C")
        paste = ("Paste", lambda: self.paste(tree), "Ctrl+V")
        delete = ("Delete", lambda: self.delete_selected(tree), "Del")
        edit = ("Edit", lambda: self.edit_current(tree), "F2")
        explorer = ("Open in Explorer", lambda: self.open_in_explorer(tree))
        new_var = ("Add variable", lambda: self.add_variable(tree.scope))
        is_entry = item is not None and item.parent() is not None
        if not self.writable(tree):
            if item is not None:
                add(*copy)
            if is_entry:
                add(*explorer)
        elif is_entry:
            add("Insert above", lambda: self.add_entry(tree=tree, above=True))
            add("Insert below", lambda: self.add_entry(tree=tree), "Ins")
            add(*edit)
            add("Browse...", lambda: self.browse_entry(tree))
            add(*explorer)
            add(*copy)
            add("Cut", lambda: self.cut_selection(tree), "Ctrl+X")
            add(*paste)
            add(*delete)
            add("Move to top", lambda: self.move_to_edge(True, tree), "Ctrl+Home")
            add("Move to bottom", lambda: self.move_to_edge(False, tree), "Ctrl+End")
        elif item is not None:
            add("Add entry", lambda: self.add_entry(tree=tree), "Ins")
            add("Add folder...", lambda: self.add_folder(tree))
            add(*edit)
            add(*copy)
            add(*paste)
            add(*delete)
            add(*new_var)
        else:
            add(*new_var)
            cur = tree.currentItem()
            if cur is not None and cur.parent() is None:
                add(*paste)
        return menu

    # ---- save / refresh / snapshots ----
    def save(self, confirm=True):
        changes = self.pending()
        if not changes:
            return ""
        if not self.can_write_system() and any(c.scope == "system" for c in changes):
            msg = "Not saved: system variables are read-only"
            self._show_pending(msg)
            return msg
        errors, critical = check(changes)
        if errors:
            msg = "Not saved: " + "; ".join(errors)
            if confirm:
                QMessageBox.warning(self, "Environment", msg)
            self._show_pending(msg)
            return msg
        if critical and confirm and QMessageBox.warning(
                self, "Remove critical variables",
                "Windows needs these system variables:\n\n  " + "\n  ".join(critical)
                + "\n\nRemove them anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return "cancelled"
        if critical and not confirm:
            return "critical: " + ", ".join(critical)
        snapshot(load(self.roots), "before-save", self.roots)
        try:
            write(changes, self.roots)
        except OSError as e:
            msg = f"Save failed: {getattr(e, 'strerror', None) or e}"
            self._show_pending(msg)
            self.reload()
            return msg
        self.reload()
        self.refresh_environment(note=f"Saved {len(changes)} change{'' if len(changes) == 1 else 's'}")
        return ""

    def refresh_environment(self, note=""):
        refresh_process(load(self.roots))
        self._show_pending((note + ". " if note else "") + "Refreshing environment")
        # the broadcast waits on every top-level window, up to 5 s each
        self._refresh_thread = threading.Thread(
            target=lambda: self.refreshed.emit(note, broadcast()), daemon=True)
        self._refresh_thread.start()

    def _refreshed(self, note, ok):
        msg = (note + ". " if note else "") + (
            "Environment refreshed for new programs" if ok else "Broadcast timed out")
        self._show_pending(msg)

    def _fill_snapshots(self):
        self.cmb_snap.clear()
        for p in snapshots(self.roots)[:50]:
            parts = p.stem.split("_")
            when = f"{parts[1][:4]}-{parts[1][4:6]}-{parts[1][6:]} {parts[2][:2]}:{parts[2][2:4]}:{parts[2][4:]}"
            self.cmb_snap.addItem(f"{when}  ({'_'.join(parts[3:])})", str(p))
        self.btn_restore.setEnabled(self.cmb_snap.count() > 0)

    def restore_snapshot(self, path=None, confirm=True):
        path = path or self.cmb_snap.currentData()
        if not path:
            return ""
        target = read_snapshot(path)
        if not self.can_write_system():
            target.system = dict(self.saved.system)   # only the user half can be written
        changes = diff(self.saved, target)
        if not changes:
            self._show_pending("Snapshot matches the current environment")
            return ""
        if confirm and QMessageBox.question(
                self, "Restore snapshot",
                f"Restore {Path(path).name}?\n\n" + "\n".join(c.label for c in changes[:20])
                + (f"\n... and {len(changes) - 20} more" if len(changes) > 20 else ""),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return "cancelled"
        snapshot(load(self.roots), "before-restore", self.roots)
        write(changes, self.roots)
        self.reload()
        self.refresh_environment(note=f"Restored {len(changes)} change{'' if len(changes) == 1 else 's'}")
        return ""
