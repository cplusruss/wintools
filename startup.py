"""startup.py - the Startup tab: what runs when Windows starts or you sign in.

A smaller Autoruns: Run keys, Startup folders, scheduled tasks with a boot or
logon trigger, and auto-start services. Unchecking an entry disables it the way
Task Manager does (StartupApproved for Run keys and Startup folders), so
re-checking brings it back unchanged; tasks and services are disabled through
Task Scheduler and the service manager.
"""

import ctypes
import os
import re
import shutil
import time
import winreg
from dataclasses import dataclass, field

import pythoncom
import pywintypes
import win32api
import win32service
import win32com.client
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QBrush, QColor, QIcon
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

import clean

HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
HIVE_NAMES = {HKCU: "HKCU", HKLM: "HKLM"}
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
SERVICES_RECORD = r"Software\wintools\Startup\Services"


@dataclass(frozen=True)
class Roots:
    """Where entries are read from; the tests point these at a scratch key."""
    # (hive, Run key, StartupApproved subkey, label)
    run: tuple = (
        (HKCU, RUN, "Run", "Run (user)"),
        (HKLM, RUN, "Run", "Run (machine)"),
        (HKLM, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "Run32",
         "Run (machine, 32-bit)"),
    )
    # (hive, folder, label); the folder's StartupApproved key is in the same hive
    folders: tuple = field(default_factory=lambda: (
        (HKCU, os.path.join(os.environ["APPDATA"],
                            r"Microsoft\Windows\Start Menu\Programs\Startup"),
         "Startup folder (user)"),
        (HKLM, os.path.join(os.environ["ProgramData"],
                            r"Microsoft\Windows\Start Menu\Programs\StartUp"),
         "Startup folder (all users)"),
    ))
    approved: str = APPROVED
    services_record: str = SERVICES_RECORD
    tasks: bool = True
    services: bool = True


ROOTS = Roots()


@dataclass
class Entry:
    kind: str           # run | folder | task | service
    name: str
    command: str
    location: str
    enabled: bool
    target: str = ""    # the program that actually runs
    publisher: str = ""
    hive: int = 0       # run, folder: hive of the StartupApproved key
    key: str = ""       # run: the Run key; folder: the folder; task: its path
    approved: str = ""  # run, folder: StartupApproved\<approved>

    @property
    def missing(self):
        return bool(self.target) and not os.path.exists(self.target)

    @property
    def microsoft(self):
        return (self.publisher.startswith("Microsoft")
                or (self.kind == "task" and self.key.lower().startswith("\\microsoft\\")))


# ====================================================================
#  helpers
# ====================================================================

_publishers = {}


def publisher(path):
    if not path or not os.path.isfile(path):
        return ""
    key = os.path.normcase(path)
    if key not in _publishers:
        name = ""
        try:
            langs = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation")
            for lang, cp in langs or ():
                name = win32api.GetFileVersionInfo(
                    path, f"\\StringFileInfo\\{lang:04x}{cp:04x}\\CompanyName") or ""
                if name:
                    break
        except pywintypes.error:
            pass
        _publishers[key] = name.strip()
    return _publishers[key]


def target_of(command):
    """The file a command line runs: the DLL for rundll32, else the program,
    found on PATH when it is not absolute."""
    exe = os.path.expandvars(clean._extract_exe_from_command(command))
    if os.path.basename(exe).lower() in ("rundll32.exe", "rundll32"):
        rest = command[command.lower().find("rundll32") + len("rundll32"):]
        rest = re.sub(r"^(\.exe)?\"?\s*", "", rest, flags=re.I)
        dll = rest.split(",", 1)[0].strip().strip('"')
        if dll:
            exe = os.path.expandvars(dll)
    if exe and not os.path.isabs(exe):
        exe = shutil.which(exe) or exe
    return exe


def _values(hive, key):
    try:
        with winreg.OpenKey(hive, key) as k:
            out, i = [], 0
            while True:
                try:
                    out.append(winreg.EnumValue(k, i))
                except OSError:
                    return out
                i += 1
    except OSError:
        return []


def _approved_on(hive, sub, name, roots):
    # Task Manager writes 02 (on) or 03 (off) in the first byte, 06/07 on some builds
    try:
        with winreg.OpenKey(hive, f"{roots.approved}\\{sub}") as k:
            data, _typ = winreg.QueryValueEx(k, name)
    except OSError:
        return True
    return not (data and data[0] & 1)


def _set_approved(hive, sub, name, on, roots):
    stamp = b"\0" * 8 if on else int((time.time() + 11644473600) * 10**7).to_bytes(8, "little")
    data = bytes((2 if on else 3, 0, 0, 0)) + stamp
    with winreg.CreateKeyEx(hive, f"{roots.approved}\\{sub}", 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, data)


def _delete_approved(hive, sub, name, roots):
    try:
        with winreg.OpenKey(hive, f"{roots.approved}\\{sub}", 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except FileNotFoundError:
        pass


def _shortcut(path):
    if not path.lower().endswith(".lnk"):
        return path, path
    try:
        link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(path)
    except pywintypes.com_error:
        return path, path
    command = f'"{link.TargetPath}" {link.Arguments}'.strip() if link.TargetPath else path
    return command, link.TargetPath or path


# ====================================================================
#  scan
# ====================================================================

def scan_run(roots=ROOTS):
    out = []
    for hive, key, sub, label in roots.run:
        for name, data, _typ in _values(hive, key):
            if not name or not isinstance(data, str):
                continue
            target = target_of(data)
            out.append(Entry("run", name, data, label, _approved_on(hive, sub, name, roots),
                             target, publisher(target), hive, key, sub))
    return out


def scan_folders(roots=ROOTS):
    out = []
    for hive, folder, label in roots.folders:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            path = os.path.join(folder, name)
            if name.lower() == "desktop.ini" or not os.path.isfile(path):
                continue
            command, target = _shortcut(path)
            out.append(Entry("folder", os.path.splitext(name)[0], command, label,
                             _approved_on(hive, "StartupFolder", name, roots),
                             target, publisher(target), hive, folder, "StartupFolder"))
    return out


TASK_TRIGGER_BOOT, TASK_TRIGGER_LOGON, TASK_ACTION_EXEC, TASK_ENUM_HIDDEN = 8, 9, 0, 1


def _task_service():
    pythoncom.CoInitialize()
    svc = win32com.client.Dispatch("Schedule.Service")
    svc.Connect()
    return svc


def scan_tasks():
    out = []
    try:
        svc = _task_service()
    except pywintypes.com_error:
        return out
    stack = [svc.GetFolder("\\")]
    while stack:
        folder = stack.pop()
        try:
            stack.extend(folder.GetFolders(0))
            tasks = list(folder.GetTasks(TASK_ENUM_HIDDEN))
        except pywintypes.com_error:
            continue
        for task in tasks:
            try:
                d = task.Definition
                if not any(t.Type in (TASK_TRIGGER_BOOT, TASK_TRIGGER_LOGON)
                           for t in d.Triggers):
                    continue
                cmds = [(a.Path, a.Arguments) for a in d.Actions if a.Type == TASK_ACTION_EXEC]
            except pywintypes.com_error:
                continue
            if not cmds:
                continue
            path, args = cmds[0]
            path = (path or "").strip().strip('"')   # some tasks store the path quoted
            command = f'"{path}" {args or ""}'.strip() if path else ""
            target = target_of(command)
            out.append(Entry("task", task.Name, command, "Scheduled task", bool(task.Enabled),
                             target, publisher(target), key=task.Path))
    return out


def _recorded_services(roots):
    return {name.lower() for name, _d, _t in _values(HKCU, roots.services_record)}


def scan_services(roots=ROOTS):
    out = []
    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
    except pywintypes.error:
        return out
    recorded = _recorded_services(roots)
    try:
        for name, display, _status in win32service.EnumServicesStatus(
                scm, win32service.SERVICE_WIN32, win32service.SERVICE_STATE_ALL):
            try:
                h = win32service.OpenService(scm, name, win32service.SERVICE_QUERY_CONFIG)
                try:
                    cfg = win32service.QueryServiceConfig(h)
                finally:
                    win32service.CloseServiceHandle(h)
            except pywintypes.error:
                continue
            start, command = cfg[1], cfg[3] or ""
            auto = start == win32service.SERVICE_AUTO_START
            if not auto and name.lower() not in recorded:
                continue
            target = target_of(command)
            out.append(Entry("service", display or name, command, "Service", auto,
                             target, publisher(target), key=name))
    finally:
        win32service.CloseServiceHandle(scm)
    return out


def scan(roots=ROOTS):
    entries = scan_run(roots) + scan_folders(roots)
    if roots.tasks:
        entries += scan_tasks()
    if roots.services:
        entries += scan_services(roots)
    return entries


# ====================================================================
#  actions
# ====================================================================

def set_enabled(e, on, roots=ROOTS):
    if e.kind in ("run", "folder"):
        name = e.name if e.kind == "run" else os.path.basename(_folder_file(e))
        _set_approved(e.hive, e.approved, name, on, roots)
    elif e.kind == "task":
        _task_service().GetFolder("\\").GetTask(e.key).Enabled = on
    else:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            h = win32service.OpenService(scm, e.key, win32service.SERVICE_CHANGE_CONFIG)
            try:
                win32service.ChangeServiceConfig(
                    h, win32service.SERVICE_NO_CHANGE,
                    win32service.SERVICE_AUTO_START if on else win32service.SERVICE_DEMAND_START,
                    win32service.SERVICE_NO_CHANGE, None, None, 0, None, None, None, None)
            finally:
                win32service.CloseServiceHandle(h)
        finally:
            win32service.CloseServiceHandle(scm)
        # a demand-start service is no longer auto-start; remember it so it stays listed
        with winreg.CreateKeyEx(HKCU, roots.services_record, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                try:
                    winreg.DeleteValue(k, e.key)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(k, e.key, 0, winreg.REG_SZ, e.name)
    e.enabled = on


def _folder_file(e):
    # the shortcut (or file) in the Startup folder, by its listed name
    for name in os.listdir(e.key):
        if os.path.splitext(name)[0] == e.name:
            return os.path.join(e.key, name)
    raise FileNotFoundError(f"{e.name} is no longer in {e.key}")


def deletable(e):
    return e.kind != "service"


def delete(e, backup_dir, roots=ROOTS):
    """Removes a Run value, recycles a Startup-folder file or deletes a task,
    after saving it to backup_dir."""
    os.makedirs(backup_dir, exist_ok=True)
    base = clean._safe_filename(f"{e.kind}_{e.name}")
    if e.kind == "run":
        ok, msg = clean.reg_export(HIVE_NAMES[e.hive], e.key, os.path.join(backup_dir, base + ".reg"))
        if not ok:
            raise OSError(f"backup failed: {msg}")
        with winreg.OpenKey(e.hive, e.key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, e.name)
        _delete_approved(e.hive, e.approved, e.name, roots)
    elif e.kind == "folder":
        path = _folder_file(e)
        shutil.copy2(path, os.path.join(backup_dir, os.path.basename(path)))
        _recycled, failed = clean.recycle([path])
        if failed:
            raise OSError(failed[0][1])
        _delete_approved(e.hive, e.approved, os.path.basename(path), roots)
    elif e.kind == "task":
        root = _task_service().GetFolder("\\")
        task = root.GetTask(e.key)
        with open(os.path.join(backup_dir, base + ".xml"), "w", encoding="utf-16") as f:
            f.write(task.Xml)
        folder, _sep, name = e.key.rpartition("\\")
        root.GetFolder(folder or "\\").DeleteTask(name, 0)
    else:
        raise OSError("services can be disabled, not deleted")


def error_text(ex):
    if isinstance(ex, pywintypes.com_error):
        return ex.excepinfo[2] if ex.excepinfo and ex.excepinfo[2] else ex.strerror
    if isinstance(ex, pywintypes.error):
        return ex.strerror
    return getattr(ex, "strerror", None) or str(ex)


# ====================================================================
#  PAGE
# ====================================================================

COLS = ("Name", "Publisher", "Location", "Command")
COL_NAME, COL_PUB, COL_LOC, COL_CMD = range(len(COLS))
ROLE = Qt.UserRole
KIND_ORDER = {"run": 0, "folder": 1, "task": 2, "service": 3}


class StartupPage(QWidget):
    def __init__(self, parent=None, roots=ROOTS):
        super().__init__(parent)
        self.roots = roots
        self.entries = []
        self._built = False
        self._icons = {}

        self.edt_filter = QLineEdit()
        self.edt_filter.setPlaceholderText("Filter")
        self.cb_hide_ms = QCheckBox("Hide Microsoft")
        self.cb_hide_ms.setChecked(True)
        self.cb_services = QCheckBox("Services")
        self.btn_refresh = QPushButton("Refresh")
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.edt_filter, 1)
        top.addWidget(self.cb_hide_ms)
        top.addWidget(self.cb_services)
        top.addWidget(self.btn_refresh)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(COLS)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setIconSize(QSize(16, 16))
        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_CMD, QHeaderView.Stretch)
        for col, width in ((COL_NAME, 240), (COL_PUB, 170), (COL_LOC, 170)):
            self.tree.setColumnWidth(col, width)

        self.btn_open = QPushButton("Open file location")
        self.btn_delete = QPushButton("Delete")
        self.status = QLabel()
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        bottom.addWidget(self.btn_open)
        bottom.addWidget(self.btn_delete)
        bottom.addWidget(self.status, 1)

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        v.addLayout(top)
        v.addWidget(self.tree, 1)
        v.addLayout(bottom)

        self.edt_filter.textChanged.connect(self._fill)
        self.cb_hide_ms.toggled.connect(self._fill)
        self.cb_services.toggled.connect(lambda: self.reload())
        self.btn_refresh.clicked.connect(lambda: self.reload())
        self.btn_open.clicked.connect(self.open_location)
        self.btn_delete.clicked.connect(lambda: self.delete_selected())
        self.tree.itemChanged.connect(self._toggled)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.open_location())
        self._selection_changed()

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._built:
            self._built = True
            self.reload()

    def reload(self):
        roots = Roots(self.roots.run, self.roots.folders, self.roots.approved,
                      self.roots.services_record, self.roots.tasks,
                      self.roots.services and self.cb_services.isChecked())
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.entries = scan(roots)
        finally:
            QApplication.restoreOverrideCursor()
        self._fill()

    def _shown(self, e):
        if self.cb_hide_ms.isChecked() and e.microsoft:
            return False
        needle = self.edt_filter.text().strip().lower()
        return not needle or needle in f"{e.name} {e.publisher} {e.command}".lower()

    def _icon(self, e):
        key = os.path.normcase(e.target)
        if key not in self._icons:
            pix = clean._shgetfileinfo_icon(e.target) if e.target else None
            self._icons[key] = QIcon(pix) if pix is not None else QIcon()
        return self._icons[key]

    def _fill(self, *_):
        self.tree.blockSignals(True)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        shown = sorted((e for e in self.entries if self._shown(e)),
                       key=lambda e: (KIND_ORDER[e.kind], e.location, e.name.lower()))
        for e in shown:
            it = QTreeWidgetItem([e.name, e.publisher, e.location, e.command])
            it.setData(COL_NAME, ROLE, e)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(COL_NAME, Qt.Checked if e.enabled else Qt.Unchecked)
            it.setIcon(COL_NAME, self._icon(e))
            it.setToolTip(COL_CMD, e.command)
            self._paint(it, e)
            self.tree.addTopLevelItem(it)
        self.tree.blockSignals(False)
        self._show_counts()

    @staticmethod
    def _paint(it, e):
        if e.missing:
            brush = QBrush(QColor("#b00000"))
            it.setToolTip(COL_NAME, f"File not found: {e.target}")
        elif not e.enabled:
            brush = QBrush(QColor("gray"))
            it.setToolTip(COL_NAME, "Disabled")
        else:
            brush = QBrush()
            it.setToolTip(COL_NAME, "")
        for c in range(len(COLS)):
            it.setForeground(c, brush)

    def _show_counts(self, note=""):
        n = self.tree.topLevelItemCount()
        off = sum(1 for i in range(n)
                  if self.tree.topLevelItem(i).checkState(COL_NAME) == Qt.Unchecked)
        hidden = len(self.entries) - n
        text = f"{n} shown   {off} disabled" + (f"   {hidden} hidden" if hidden else "")
        self.status.setText(f"{note}   {text}" if note else text)

    def _toggled(self, item, column):
        if column != COL_NAME:
            return
        e = item.data(COL_NAME, ROLE)
        on = item.checkState(COL_NAME) == Qt.Checked
        if e is None or on == e.enabled:
            return
        try:
            set_enabled(e, on, self.roots)
            note = f"{'Enabled' if on else 'Disabled'} {e.name}"
        except (OSError, pywintypes.error, pywintypes.com_error) as ex:
            note = f"{e.name}: {error_text(ex)}"
            if not ctypes.windll.shell32.IsUserAnAdmin():
                note += " (machine-wide entries need wintools run as administrator)"
            self.tree.blockSignals(True)
            item.setCheckState(COL_NAME, Qt.Checked if e.enabled else Qt.Unchecked)
            self.tree.blockSignals(False)
        self._paint(item, e)
        self._show_counts(note)

    def selected(self):
        return [it.data(COL_NAME, ROLE) for it in self.tree.selectedItems()]

    def _selection_changed(self):
        sel = self.selected()
        self.btn_open.setEnabled(len(sel) == 1 and bool(sel[0].target))
        self.btn_delete.setEnabled(any(deletable(e) for e in sel))

    def open_location(self):
        sel = self.selected()
        if len(sel) == 1 and sel[0].target and os.path.exists(sel[0].target):
            clean._reveal_in_file_manager(sel[0].target)

    def delete_selected(self, confirm=True):
        entries = [e for e in self.selected() if deletable(e)]
        if not entries:
            return ""
        backup_dir = str(clean.REG_BACKUP_DIR / f"startup_{time.strftime('%Y%m%d_%H%M%S')}")
        if confirm:
            names = "\n  ".join(e.name for e in entries[:12])
            more = f"\n  ... and {len(entries) - 12} more" if len(entries) > 12 else ""
            if QMessageBox.question(
                    self, "Delete startup entries",
                    f"Delete {len(entries)} startup entr{'y' if len(entries) == 1 else 'ies'}?"
                    f"\n\n  {names}{more}\n\n"
                    f"Each is saved to {backup_dir} first. Unchecking an entry only "
                    "disables it.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return ""
        failed = []
        for e in entries:
            try:
                delete(e, backup_dir, self.roots)
            except (OSError, pywintypes.error, pywintypes.com_error) as ex:
                failed.append(f"{e.name}: {error_text(ex)}")
        self.reload()
        note = f"Deleted {len(entries) - len(failed)}" + (f", {len(failed)} failed" if failed else "")
        self._show_counts(note)
        if failed and confirm:
            QMessageBox.warning(self, "Some entries were not deleted", "\n".join(failed[:15]))
        return "\n".join(failed)
