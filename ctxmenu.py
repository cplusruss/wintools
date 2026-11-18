#!/usr/bin/env python3
"""ctxmenu.py - the right-click menu Explorer builds, item by item, with a
reversible per-item removal (LegacyDisable, disabled ContextMenuHandlers
registrations, Shell Extensions\\Blocked)."""

import base64
import contextlib
import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
import winreg
from dataclasses import asdict, dataclass, field, fields, replace

import pythoncom
import win32com.client
import win32con
import win32gui
import win32gui_struct
from PyQt5 import sip
from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QSize, Qt
from PyQt5.QtGui import QBrush, QColor, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QPushButton, QSplitter, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from PyQt5.QtWinExtras import QtWin
from win32com.shell import shell, shellcon

from keydiag import style_grid

KINDS = (("Folder", "folder"), ("File", "file"),
         ("Folder background", "background"), ("Drive", "drive"),
         ("New", "new"))

FIRST, LAST = 1, 0x7FFF
HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
HIVES = {"HKCU": HKCU, "HKLM": HKLM}
# (hive name, hive, ClassIndex key, package repository key)
PACKAGED = ("HKCR", winreg.HKEY_CLASSES_ROOT, r"PackagedCom\ClassIndex",
            r"Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel"
            r"\Repository\Packages")
CLASSES = "Software\\Classes\\"
BLOCKED_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Shell Extensions\Blocked"
RECORD_KEY = r"Software\wintools\ContextMenu\Removed"
SHELLNEW_CACHE = (r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                  r"\Discardable\PostSetup\ShellNew")
USERCHOICE = (r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"
              "\\{}\\UserChoice")

PROTECTED = frozenset((
    "open", "explore", "opennewwindow", "opennewprocess", "opennewtab", "find",
    "cut", "copy", "paste", "pastelink", "delete", "rename", "link",
    "properties", "runas"))
BUILTIN_TEXT = frozenset((
    "cut", "copy", "delete", "rename", "create shortcut", "properties"))
GUID = re.compile(r"^\{[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}\}$")
# HBMMENU_* sentinels are 1..11; HBMMENU_CALLBACK is -1
SENTINEL_MAX = 11
NEG_MIN = 0xFFFFFFFFFFFFFFF0
# what Explorer passes, so a handler builds the menu Explorer shows
FLAGS = shellcon.CMF_EXPLORE | shellcon.CMF_CANRENAME
# _probe result for a handler that is created but fails Initialize / QueryContextMenu
REFUSED = object()
HELPER_TIMEOUT = 20
SHELLWINDOWS = "{9BA05972-F6A8-11CF-A442-00A0C90A8F39}"


@dataclass
class Source:
    kind: str
    label: str
    key: str
    clsid: str
    dll: str
    scope: str


@dataclass
class MenuItem:
    text: str
    raw: str = ""
    verb: str = ""
    separator: bool = False
    children: list = field(default_factory=list)
    icon: QPixmap = None
    source: Source = None

    @property
    def removable(self):
        return self.source is not None and self.source.kind != "builtin"


@dataclass
class Removed:
    name: str
    text: str
    menu: str
    source: Source
    regs: tuple = ()


@dataclass
class Roots:
    blocked: tuple
    record: tuple
    classes: tuple  # (hive name, hive, key) of each Software\Classes root
    packaged: tuple = PACKAGED
    shellnew_cache: tuple = (HKCU, SHELLNEW_CACHE)


ROOTS = Roots(blocked=(HKLM, BLOCKED_KEY), record=(HKCU, RECORD_KEY),
              classes=tuple((n, h, CLASSES[:-1]) for n, h in HIVES.items()))


# ====================================================================
#  REGISTRY LOOKUPS
# ====================================================================

def _text(hive, sub, name=""):
    try:
        with winreg.OpenKey(hive, sub) as k:
            value = winreg.QueryValueEx(k, name)[0]
    except FileNotFoundError:
        return ""
    return os.path.expandvars(value) if isinstance(value, str) else ""


def _subkeys(hive, sub):
    try:
        with winreg.OpenKey(hive, sub) as k:
            return [winreg.EnumKey(k, i)
                    for i in range(winreg.QueryInfoKey(k)[0])]
    except FileNotFoundError:
        return []


def _class_key(cls, rel=""):
    """'HKCU\\...' or 'HKLM\\...' of the first hive that defines the key."""
    sub = CLASSES + cls + ("\\" + rel if rel else "")
    for hname, hive in HIVES.items():
        try:
            winreg.CloseKey(winreg.OpenKey(hive, sub))
        except FileNotFoundError:
            continue
        return f"{hname}\\{sub}"
    return None


def _class_text(cls, name=""):
    for hive in HIVES.values():
        value = _text(hive, CLASSES + cls, name)
        if value:
            return value
    return ""


def _split_key(full):
    hname, sub = full.split("\\", 1)
    return HIVES[hname], sub


def _command_source(full):
    rest = full.split("\\", 1)[1].removeprefix(CLASSES)
    scope, sep, verb = rest.rpartition("\\shell\\")
    if not sep:
        scope, verb = "", rest.rpartition("\\")[2]
    return Source("command", verb, full, "", "", scope)


def _packaged_source(clsid, roots):
    hname, hive, index, repo = roots.packaged
    key = index + "\\" + clsid
    fulls = _subkeys(hive, key)
    if not fulls:
        return None
    folder = _text(hive, repo + "\\" + fulls[0], "PackageRootFolder")
    return Source("extension", fulls[0].partition("_")[0], hname + "\\" + key,
                  clsid, folder, "all menus")


def _extension_source(clsid, key="", roots=ROOTS):
    # a CLSID with no classic registration may be a packaged (MSIX) one
    if _class_key("CLSID\\" + clsid) is None:
        packaged = _packaged_source(clsid, roots)
        if packaged is not None:
            return packaged
    name = _class_text("CLSID\\" + clsid)
    dll = _class_text(f"CLSID\\{clsid}\\InprocServer32")
    return Source("extension", name or clsid, key, clsid, dll, "all menus")


BUILTIN = Source("builtin", "built-in", "", "", "", "")
UNKNOWN = Source("builtin", "unknown", "", "", "", "")


def _menu_classes(kind, path):
    if kind == "folder":
        return ["Directory", "Folder", "AllFilesystemObjects"]
    if kind == "background":
        return ["Directory\\Background"]
    if kind == "drive":
        return ["Drive", "Folder"]
    ext = os.path.splitext(path)[1].lower()
    out = ["*"]
    if ext:
        progids = [_class_text(ext)]
        progids.append(_text(HKCU, USERCHOICE.format(ext), "ProgId"))
        perceived = _class_text(ext, "PerceivedType")
        out += [ext, *progids, f"SystemFileAssociations\\{ext}"]
        if perceived:
            out.append(f"SystemFileAssociations\\{perceived}")
    out.append("AllFilesystemObjects")
    return list(dict.fromkeys(c for c in out if c))


def _default(hive, sub):
    try:
        with winreg.OpenKey(hive, sub) as k:
            return winreg.QueryValueEx(k, "")[0]
    except FileNotFoundError:
        return None


def _entries(hive, base):
    # form A: the default is the CLSID; form B: the subkey is named for it and
    # the default is empty or absent. A "-{CLSID}" default is a disabled entry.
    out = []
    for name in _subkeys(hive, base):
        default = _default(hive, f"{base}\\{name}")
        if default is not None and not isinstance(default, str):
            continue
        clsid = default or name
        if GUID.match(clsid):
            out.append((name, clsid, default))
    return out


def _handlers(classes):
    """[(clsid, key)] of every enabled ContextMenuHandlers entry."""
    out, seen = [], set()
    for cls in classes:
        for hname, hive in HIVES.items():
            base = f"{CLASSES}{cls}\\shellex\\ContextMenuHandlers"
            for name, clsid, _default_value in _entries(hive, base):
                if clsid.upper() not in seen:
                    seen.add(clsid.upper())
                    out.append((clsid, f"{hname}\\{base}\\{name}"))
    return out


def _registrations(roots):
    # {CLSID upper: [(full key, default or None)]}. Registrations sit one or
    # two levels below Classes: Folder\shellex, Directory\Background\shellex,
    # SystemFileAssociations\.png\shellex
    out = {}
    for hname, hive, root in roots.classes:
        for cls in _subkeys(hive, root):
            children = (f"{cls}\\{c}" for c in _subkeys(hive, f"{root}\\{cls}"))
            for rel in (cls, *children):
                base = f"{root}\\{rel}\\shellex\\ContextMenuHandlers"
                for name, clsid, default in _entries(hive, base):
                    out.setdefault(clsid.upper(), []).append(
                        (f"{hname}\\{base}\\{name}", default))
    return out


# ====================================================================
#  BUILDING THE MENU
# ====================================================================

def _display(raw):
    return re.sub(r"&(.)", r"\1", raw).replace("\t", "  ")


def _pixmap(h):
    if not h or h <= SENTINEL_MAX or h >= NEG_MIN or h == 0xFFFFFFFF:
        return None
    pm = QtWin.fromHBITMAP(sip.voidptr(h), QtWin.HBitmapAlpha)
    if pm.isNull():
        return None
    return _small(pm)


def _read_menu(menu, cm, icons=True):
    items = []
    for i in range(win32gui.GetMenuItemCount(menu)):
        buf, _extras = win32gui_struct.EmptyMENUITEMINFO()
        win32gui.GetMenuItemInfo(menu, i, True, buf)
        info = win32gui_struct.UnpackMENUITEMINFO(buf)
        if info.fType & win32con.MFT_SEPARATOR:
            items.append(MenuItem("", separator=True))
            continue
        verb = ""
        if cm is not None and info.wID and FIRST <= info.wID < LAST:
            try:
                verb = cm.GetCommandString(info.wID - FIRST, shellcon.GCS_VERBW)
            except pythoncom.com_error:
                verb = "?"
        raw = info.text or ""
        item = MenuItem(_display(raw), raw, verb)
        if icons:
            item.icon = _pixmap(info.hbmpItem)
        if info.hSubMenu:
            item.children = _read_menu(info.hSubMenu, cm, icons)
        items.append(item)
    return items


def _shell_objects(kind, path):
    """-> (IContextMenu, parent pidl, data object or None)"""
    hwnd = win32gui.GetDesktopWindow()
    desktop = shell.SHGetDesktopFolder()
    if kind == "background":
        pidl = shell.SHParseDisplayName(path, 0)[0]
        folder = desktop.BindToObject(pidl, None, shell.IID_IShellFolder)
        return folder.CreateViewObject(hwnd, shell.IID_IContextMenu), pidl, None
    if kind == "drive":
        pidl = shell.SHGetSpecialFolderLocation(0, shellcon.CSIDL_DRIVES)
        name = path
    else:
        parent, name = os.path.split(path.rstrip("\\"))
        pidl = shell.SHParseDisplayName(parent, 0)[0]
    folder = desktop.BindToObject(pidl, None, shell.IID_IShellFolder)
    child = folder.ParseDisplayName(0, None, name)[1]
    cm = folder.GetUIObjectOf(hwnd, [child], shell.IID_IContextMenu, 0)[1]
    data = folder.GetUIObjectOf(hwnd, [child], pythoncom.IID_IDataObject, 0)[1]
    return cm, pidl, data


def _probe(clsid, pidl, data):
    """Top-level items one handler adds to a scratch menu; None when it cannot
    be created, REFUSED when it is created but will not initialize or build
    its menu."""
    try:
        init = pythoncom.CoCreateInstance(
            clsid, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellExtInit)
    except pythoncom.com_error:
        return None
    try:
        init.Initialize(pidl, data, 0)
        cm = init.QueryInterface(shell.IID_IContextMenu)
        menu = win32gui.CreatePopupMenu()
        try:
            cm.QueryContextMenu(menu, 0, FIRST, LAST, FLAGS)
            top = _read_menu(menu, cm, icons=False)
            return [i for i in top if not i.separator]
        finally:
            win32gui.DestroyMenu(menu)
    except pythoncom.com_error:
        return REFUSED


def _static(verb):
    # File Converter issues a fresh GUID verb for every instance
    return verb not in ("", "?") and not GUID.match("{" + verb.strip("{}") + "}")


def _same_item(item, probed):
    if not item.text or item.text != probed.text:
        return False
    if _static(item.verb) and _static(probed.verb):
        return item.verb.lower() == probed.verb.lower()
    return True


def _by_verb(item, classes):
    verb = item.verb.lower()
    if verb in PROTECTED or (
            verb in ("", "?") and item.text.lower() in BUILTIN_TEXT):
        return BUILTIN
    if GUID.match(item.verb):
        return _extension_source(item.verb)
    if verb in ("", "?"):
        return None
    for cls in classes:
        key = _class_key(cls, "shell\\" + item.verb)
        if key is None:
            continue
        hive, sub = _split_key(key)
        handler = _text(hive, sub, "ExplorerCommandHandler")
        if handler:
            return _extension_source(handler, key)
        return _command_source(key)
    return None


def _walk(items):
    for it in items:
        if not it.separator:
            yield it
            yield from _walk(it.children)


def _inherit(items, parent):
    for it in items:
        if it.separator:
            continue
        if it.source is None:
            it.source = parent or UNKNOWN
        _inherit(it.children, it.source)


def _in_system(dll):
    return dll.lower().startswith(os.environ["SystemRoot"].lower() + "\\")


def _demote_internals(items, roots=ROOTS):
    # an Explorer-internal server: under %SystemRoot%, no menu registration
    regs = None
    for it in _walk(items):
        s = it.source
        if s is not None and s.kind == "extension" and _in_system(s.dll):
            if regs is None:
                regs = _registrations(roots)
            if s.clsid.upper() not in regs:
                it.source = replace(s, kind="builtin")


def build_menu(kind, path):
    cm, pidl, data = _shell_objects(kind, path)
    menu = win32gui.CreatePopupMenu()
    try:
        cm.QueryContextMenu(menu, 0, FIRST, LAST, FLAGS)
        items = _read_menu(menu, cm)
    finally:
        win32gui.DestroyMenu(menu)

    classes = _menu_classes(kind, path)
    for it in _walk(items):
        it.source = _by_verb(it, classes)
    _demote_internals(items)
    pending = [it for it in items if not it.separator and it.source is None]
    refused = []
    for clsid, key in _handlers(classes):
        top = _probe(clsid, pidl, data)
        if top is REFUSED:
            source = _extension_source(clsid, key)
            # a %SystemRoot% handler (Work Folders) refuses inside Explorer too
            if not _in_system(source.dll):
                refused.append(source)
        elif top is not None:
            for it in [p for p in pending if any(_same_item(p, t) for t in top)]:
                it.source = _extension_source(clsid, key)
                pending.remove(it)
    _inherit(items, None)
    if refused:
        # Explorer loads these; outside it they add nothing to the live menu
        items.append(MenuItem("", separator=True))
        items += [MenuItem(s.label, s.label, source=s) for s in refused]
    return items


# ====================================================================
#  UNTRUSTED INPUT
#  Any process of this user can write the helper outfile and the HKCU removal
#  record, and remove() / restore() write the registry from what they read, so
#  both are checked on the way in.
# ====================================================================

SOURCE_KINDS = ("command", "extension", "builtin")
HANDLER_REG = "\\shellex\\contextmenuhandlers\\"


def _bad(where, name, value):
    return ValueError(f"{where}: unexpected {name} {value!r}")


def _under_classes(full, roots):
    low = full.lower()
    return any(low.startswith(f"{hname}\\{key}\\".lower())
               for hname, _hive, key in roots.classes)


def _validate_source(kind, key, clsid, roots, where):
    if kind not in SOURCE_KINDS:
        raise _bad(where, "kind", kind)
    if kind == "command":
        if not (_under_classes(key, roots) and "\\shell\\" in key.lower()):
            raise _bad(where, "key", key)
    elif kind == "extension":
        if not GUID.fullmatch(clsid):
            raise _bad(where, "clsid", clsid)
        hname, _hive, index, _repo = roots.packaged
        low = key.lower()
        # a handler registration, the verb key of an ExplorerCommandHandler
        # (_by_verb), the package index entry, or none
        if key and low != f"{hname}\\{index}\\{clsid}".lower() and not (
                _under_classes(key, roots) and (HANDLER_REG in low or "\\shell\\" in low)):
            raise _bad(where, "key", key)


def _validate_regs(regs, roots, where):
    for full, previous in regs:
        if not (_under_classes(full, roots) and HANDLER_REG in full.lower()):
            raise _bad(where, "registration", full)
        if previous and not GUID.fullmatch(previous):
            raise _bad(where, "previous", previous)


# ====================================================================
#  UNELEVATED HELPER
#  Windows loads no packaged shell extension into an elevated process, so an
#  elevated app has an unelevated copy of itself build the menu and hand it
#  back as JSON.
# ====================================================================

def _png(pm):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    if not pm.save(buf, "PNG"):
        raise ValueError("menu icon cannot be encoded")
    return base64.b64encode(bytes(ba)).decode("ascii")


def _to_json(item):
    return {"text": item.text, "raw": item.raw, "verb": item.verb,
            "separator": item.separator,
            "icon": None if item.icon is None else _png(item.icon),
            "source": None if item.source is None else asdict(item.source),
            "children": [_to_json(c) for c in item.children]}


ITEM_TYPES = {"text": str, "raw": str, "verb": str, "separator": bool,
              "icon": (str, type(None)), "source": (dict, type(None)),
              "children": list}
SOURCE_TYPES = dict.fromkeys((f.name for f in fields(Source)), str)


def _shaped(d, types, where):
    if not isinstance(d, dict) or d.keys() != types.keys():
        raise ValueError(f"{where}: unexpected fields "
                         f"{sorted(d) if isinstance(d, dict) else type(d).__name__}")
    for name, kinds in types.items():
        if not isinstance(d[name], kinds):
            raise _bad(where, name, d[name])


def _from_json(d, roots=ROOTS):
    where = "menu helper output"
    _shaped(d, ITEM_TYPES, where)
    icon = None
    if d["icon"] is not None:
        icon = QPixmap()
        if not icon.loadFromData(base64.b64decode(d["icon"]), "PNG"):
            raise ValueError(f"{where}: unreadable icon")
    source = None
    if d["source"] is not None:
        _shaped(d["source"], SOURCE_TYPES, where + " source")
        source = Source(**d["source"])
        _validate_source(source.kind, source.key, source.clsid, roots, where)
    return MenuItem(d["text"], d["raw"], d["verb"], d["separator"],
                    [_from_json(c, roots) for c in d["children"]], icon, source)


def _items_from(data):
    if isinstance(data, dict) and data.keys() == {"error"}:
        if not isinstance(data["error"], str):
            raise _bad("menu helper output", "error", data["error"])
        raise OSError(data["error"])
    _shaped(data, {"items": list}, "menu helper output")
    return [_from_json(d) for d in data["items"]]


def dump_menu(kind, path, outfile):
    try:
        data = {"items": [_to_json(i) for i in build_menu(kind, path)]}
    except Exception as e:  # the parent is waiting on the file: it gets the reason
        data = {"error": _error(e) or repr(e)}
    tmp = outfile + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, outfile)  # the reader never sees a partial file


def dump_main(argv):
    """--ctxmenu-dump <kind> <path> <outfile>"""
    kind, path, outfile = argv
    _app = QApplication([])  # QPixmap needs a live application object
    dump_menu(kind, path, outfile)


def _helper_command(args):
    # same split as wintools._relaunch_args, which imports this module
    if getattr(sys, "frozen", False):
        return (sys.executable, subprocess.list2cmdline(args),
                os.path.dirname(os.path.abspath(sys.executable)))
    here = os.path.dirname(os.path.abspath(__file__))
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(exe):
        exe = sys.executable
    return exe, subprocess.list2cmdline([os.path.join(here, "wintools.py"), *args]), here


def _explorer_launch(exe, params, cwd):
    """Start exe through Explorer's own shell: it runs with Explorer's token."""
    windows = win32com.client.Dispatch(pythoncom.CoCreateInstance(
        SHELLWINDOWS, None, pythoncom.CLSCTX_LOCAL_SERVER, pythoncom.IID_IDispatch))
    desktop = windows.FindWindowSW(shellcon.CSIDL_DESKTOP, "", shellcon.SWC_DESKTOP,
                                   0, shellcon.SWFO_NEEDDISPATCH)
    browser = desktop._oleobj_.QueryInterface(
        pythoncom.IID_IServiceProvider).QueryService(
            shell.SID_STopLevelBrowser, shell.IID_IShellBrowser)
    background = browser.QueryActiveShellView().GetItemObject(
        shellcon.SVGIO_BACKGROUND, pythoncom.IID_IDispatch)
    win32com.client.Dispatch(background).Application.ShellExecute(
        exe, params, cwd, "open", 0)


def _outfile():
    return os.path.join(tempfile.gettempdir(), f"wintools-ctxmenu-{uuid.uuid4().hex}.json")


def _wait_for(path, timeout):
    deadline = time.monotonic() + timeout
    while not os.path.exists(path):
        if time.monotonic() > deadline:
            raise TimeoutError("menu helper timed out")
        time.sleep(0.05)


def load_menu(kind, path, *, elevated=None, launch=None, timeout=HELPER_TIMEOUT):
    if elevated is None:
        elevated = shell.IsUserAnAdmin()
    if not elevated:
        return build_menu(kind, path)
    outfile = _outfile()
    exe, params, cwd = _helper_command(["--ctxmenu-dump", kind, path, outfile])
    try:
        (launch or _explorer_launch)(exe, params, cwd)
        _wait_for(outfile, timeout)
        with open(outfile, encoding="utf-8") as f:
            return _items_from(json.load(f))
    except RecursionError as e:
        raise ValueError("menu helper output: nested too deep") from e
    finally:
        # best-effort: a helper that timed out may still hold its file, and
        # that must not replace the timeout
        for leftover in (outfile, outfile + ".tmp"):
            with contextlib.suppress(OSError):
                os.remove(leftover)


# ====================================================================
#  REMOVAL STORE
# ====================================================================

def _record_name(source):
    if source.kind == "shellnew":
        return f"shellnew|{source.label}"
    if source.kind == "command":
        return f"command|{source.key}"
    return f"extension|{source.clsid}"


def _set_block(source, roots, on):
    if source.kind == "command":
        hive, sub = _split_key(source.key)
        with winreg.OpenKey(hive, sub, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, "LegacyDisable", 0, winreg.REG_SZ, "")
            else:
                winreg.DeleteValue(k, "LegacyDisable")
        return
    hive, sub = roots.blocked
    if on:
        with winreg.CreateKeyEx(hive, sub, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, source.clsid, 0, winreg.REG_SZ, "")
    else:
        with winreg.OpenKey(hive, sub, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, source.clsid)


def _set_default(full, value):
    hive, sub = _split_key(full)
    with winreg.OpenKey(hive, sub, 0, winreg.KEY_SET_VALUE) as k:
        if value is None:
            winreg.DeleteValue(k, "")
        else:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, value)


def _enable(regs):
    for full, previous in regs:
        try:
            _set_default(full, previous)
        except FileNotFoundError:
            pass  # key or value is gone: nothing left to put back


def _disable(clsid, regs):
    done = []
    try:
        for full, previous in regs:
            _set_default(full, "-" + clsid)
            done.append((full, previous))
    except OSError:
        _enable(done)
        raise


def _read_record(roots, name):
    hive, sub = roots.record
    try:
        with winreg.OpenKey(hive, sub) as k:
            return winreg.QueryValueEx(k, name)
    except FileNotFoundError:
        return None


def _write_record(roots, name, data, kind):
    hive, sub = roots.record
    with winreg.CreateKey(hive, sub) as k:
        winreg.SetValueEx(k, name, 0, kind, data)


def _delete_record(roots, name):
    hive, sub = roots.record
    with winreg.OpenKey(hive, sub, 0, winreg.KEY_SET_VALUE) as k:
        winreg.DeleteValue(k, name)


def remove(source, text, menu, roots=ROOTS):
    # a classic extension is disabled per ContextMenuHandlers registration so
    # its other roles (property sheet, drag-drop) keep working; one with no
    # registration is blocked by CLSID
    if source.kind == "builtin":
        raise ValueError(f"{text}: built-in items cannot be removed")
    if source.kind == "shellnew":
        _rename_shellnew(source.label, "ShellNew", "_ShellNew", roots)
        return
    regs = []
    if source.kind == "extension":
        regs = _registrations(roots).get(source.clsid.upper(), [])
        if not regs and _in_system(source.dll):
            raise ValueError(f"{text}: built-in items cannot be removed")
    name = _record_name(source)
    old = _read_record(roots, name)
    head = f"{menu}|{text}"
    if regs:
        lines = [f"{'N' if prev is None else 'S' + prev}|{full}"
                 for full, prev in regs]
        _write_record(roots, name, [head, *lines], winreg.REG_MULTI_SZ)
    else:
        _write_record(roots, name, head, winreg.REG_SZ)
    try:
        if regs:
            _disable(source.clsid, regs)
        else:
            _set_block(source, roots, True)
    except OSError:
        if old is None:
            _delete_record(roots, name)
        else:
            _write_record(roots, name, *old)
        raise


def restore(entry, roots=ROOTS):
    if entry.source.kind == "shellnew":
        _rename_shellnew(entry.source.label, "_ShellNew", "ShellNew", roots)
        return
    if entry.regs:
        _enable(entry.regs)
    else:
        try:
            _set_block(entry.source, roots, False)
        except FileNotFoundError:
            pass  # Windows no longer holds the block: the record is all that is left
    _delete_record(roots, entry.name)


# ====================================================================
#  NEW SUBMENU (ShellNew)
#  Explorer's rule, checked against its own cache of the shown extensions:
#  .ext\<progid>\ShellNew wins over .ext\ShellNew whenever that key exists, valid
#  or not, and is shown when it holds NullFile, FileName, Data or Command.
#  Hiding renames ShellNew to _ShellNew (the ShellMenuNew convention); the
#  renamed key is the record.
# ====================================================================

SHELLNEW_VALUES = frozenset(("nullfile", "filename", "data", "command"))
_advapi32 = ctypes.WinDLL("advapi32")
_advapi32.RegRenameKey.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
_advapi32.RegRenameKey.restype = ctypes.c_long
_shlwapi = ctypes.WinDLL("shlwapi")


def _has(hive, sub):
    try:
        winreg.CloseKey(winreg.OpenKey(hive, sub))
    except FileNotFoundError:
        return False
    return True


def _values(hive, sub):
    """{lower-case name: data} of a key, None when the key is missing."""
    try:
        with winreg.OpenKey(hive, sub) as k:
            return {n.lower(): d for n, d, _t in (
                winreg.EnumValue(k, i) for i in range(winreg.QueryInfoKey(k)[1]))}
    except FileNotFoundError:
        return None


def _found(roots, rel):
    """[(hive name, hive, key, values)] of each Classes root that has the key."""
    out = []
    for hname, hive, root in roots.classes:
        sub = f"{root}\\{rel}"
        vals = _values(hive, sub)
        if vals is not None:
            out.append((hname, hive, sub, vals))
    return out


def _first(found, name):
    for *_, vals in found:
        value = vals.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _indirect(text):
    if not text.startswith("@"):
        return text
    buf = ctypes.create_unicode_buffer(512)
    hr = _shlwapi.SHLoadIndirectString(text, buf, len(buf), None)
    return None if hr else buf.value


def _extensions(roots):
    names = {}
    for _hname, hive, root in roots.classes:
        for name in _subkeys(hive, root):
            if name.startswith("."):
                names.setdefault(name.lower(), name)
    return [names[k] for k in sorted(names)]


def _shellnew_parents(roots, ext):
    subs = {}
    for _hname, hive, root in roots.classes:
        for sub in _subkeys(hive, f"{root}\\{ext}"):
            if sub.lower() not in ("shellnew", "_shellnew"):
                subs.setdefault(sub.lower(), sub)
    return [ext, *(f"{ext}\\{s}" for s in subs.values())]


def _carries(found):
    return any(SHELLNEW_VALUES & vals.keys() for *_, vals in found)


def _shown_location(roots, ext):
    progid = _first(_found(roots, ext), "")
    if progid:
        found = _found(roots, f"{ext}\\{progid}\\ShellNew")
        if found:
            return found
    return _found(roots, f"{ext}\\ShellNew")


def _hidden_location(roots, ext):
    return [f for rel in _shellnew_parents(roots, ext)
            for f in _found(roots, rel + "\\_ShellNew") if _carries([f])]


def _shellnew_text(roots, ext, found):
    progid = _first(_found(roots, ext), "")
    progid_found = _found(roots, progid) if progid else []
    # an uninstalled app can leave a @dll,-id whose DLL is gone; the next source names it
    for text in (_first(found, "menutext"), _first(progid_found, "friendlytypename"),
                 _first(progid_found, "")):
        if text and (text := _indirect(text)):
            return text
    return ext


def _shellnew_source(ext, found):
    return Source("shellnew", ext, "; ".join(f"{h}\\{sub}" for h, _hive, sub, _v in found),
                  "", "", "+".join(h for h, *_ in found))


def _small(pm):
    return pm if pm.width() == 16 else pm.scaled(
        16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _type_icon(name, attrs):
    flags = shellcon.SHGFI_ICON | shellcon.SHGFI_SMALLICON | shellcon.SHGFI_USEFILEATTRIBUTES
    hicon = shell.SHGetFileInfo(name, attrs, flags)[1][0]
    if not hicon:
        return None
    try:
        pm = QtWin.fromHICON(hicon)
    finally:
        win32gui.DestroyIcon(hicon)
    return None if pm.isNull() else _small(pm)


def _shown_exts(roots):
    out = {}
    for ext in _extensions(roots):
        found = _shown_location(roots, ext)
        if ext.lower() != ".lnk" and _carries(found):
            out[ext] = found
    return out


def shellnew_menu(roots=ROOTS):
    items = [
        MenuItem("Folder", source=BUILTIN,
                 icon=_type_icon("folder", win32con.FILE_ATTRIBUTE_DIRECTORY)),
        MenuItem("Shortcut", source=BUILTIN,
                 icon=_type_icon(".lnk", win32con.FILE_ATTRIBUTE_NORMAL)),
        MenuItem("", separator=True)]
    for ext, found in _shown_exts(roots).items():
        items.append(MenuItem(_shellnew_text(roots, ext, found),
                              source=_shellnew_source(ext, found),
                              icon=_type_icon(ext, win32con.FILE_ATTRIBUTE_NORMAL)))
    return items


def shellnew_removed(roots=ROOTS):
    shown = _shown_exts(roots)
    out = []
    for ext in _extensions(roots):
        if ext.lower() == ".lnk" or ext in shown:
            continue
        found = _hidden_location(roots, ext)
        if found:
            out.append(Removed(f"shellnew|{ext}", _shellnew_text(roots, ext, found),
                               "new", _shellnew_source(ext, found)))
    return out


def _delete_tree(hive, sub):
    for child in _subkeys(hive, sub):
        _delete_tree(hive, f"{sub}\\{child}")
    winreg.DeleteKey(hive, sub)


def _rename_key(hive, parent, old, new):
    with winreg.OpenKey(hive, parent, 0, winreg.KEY_WRITE) as k:
        rc = _advapi32.RegRenameKey(k.handle, old, new)
    if rc:
        raise ctypes.WinError(rc)


def _rename_shellnew(ext, old, new, roots):
    jobs = [(hive, f"{root}\\{rel}")
            for rel in _shellnew_parents(roots, ext)
            for _hname, hive, root in roots.classes
            if _has(hive, f"{root}\\{rel}\\{old}")]
    for hive, parent in jobs:
        if old == "_ShellNew" and _has(hive, f"{parent}\\{new}"):
            raise FileExistsError(f"{parent}\\{new} exists beside {parent}\\{old}")
    done = []
    try:
        for hive, parent in jobs:
            # a stale copy from an earlier hide would make the rename fail
            if old == "ShellNew" and _has(hive, f"{parent}\\{new}"):
                _delete_tree(hive, f"{parent}\\{new}")
            _rename_key(hive, parent, old, new)
            done.append((hive, parent))
    except OSError:
        # half-hidden (HKCU renamed, HKLM refused) stays shown with no row to undo it
        for hive, parent in reversed(done):
            _rename_key(hive, parent, new, old)
        raise
    finally:
        # Explorer rebuilds the New submenu from this cache; a missing key is fine
        with contextlib.suppress(FileNotFoundError):
            _delete_tree(*roots.shellnew_cache)


def _parse_regs(sub, name, lines):
    out = []
    for line in lines:
        head, sep, full = line.partition("|")
        if not sep or head[:1] not in ("N", "S"):
            raise ValueError(f"{sub}: unreadable record {name!r}")
        out.append((full, None if head == "N" else head[1:]))
    return tuple(out)


def removed(roots=ROOTS):
    hive, sub = roots.record
    try:
        k = winreg.OpenKey(hive, sub)
    except FileNotFoundError:
        return []
    out = []
    with k:
        for i in range(winreg.QueryInfoKey(k)[1]):
            name, data, _type = winreg.EnumValue(k, i)
            kind, sep, ident = name.partition("|")
            head, *lines = data if isinstance(data, list) else [data]
            if not all(isinstance(x, str) for x in (head, *lines)):
                raise ValueError(f"{sub}: unreadable record {name!r}")
            menu, sep2, text = head.partition("|")
            if not sep or not sep2 or kind not in ("command", "extension"):
                raise ValueError(f"{sub}: unreadable record {name!r}")
            where = f"{sub}: record {name!r}"
            key, clsid = (ident, "") if kind == "command" else ("", ident)
            _validate_source(kind, key, clsid, roots, where)
            regs = _parse_regs(sub, name, lines)
            _validate_regs(regs, roots, where)
            source = (_command_source(ident) if kind == "command"
                      else _extension_source(ident, roots=roots))
            out.append(Removed(name, text, menu, source, regs))
    return out


# ====================================================================
#  PAGE
# ====================================================================

ROLE = Qt.UserRole
DEFAULT_PATH = {
    "folder": lambda: os.environ["USERPROFILE"],
    "file": lambda: os.path.join(os.environ["SystemRoot"], "win.ini"),
    "background": lambda: os.environ["USERPROFILE"],
    "drive": lambda: "C:\\",
    "new": lambda: "",
}
GRID_ROWS = ("Source", "Key", "CLSID", "DLL", "Scope")
ROW_H, SEP_H = 22, 7
PLAIN = Qt.ItemIsSelectable | Qt.ItemIsEnabled
CHECKABLE = PLAIN | Qt.ItemIsUserCheckable


class _MenuDelegate(QStyledItemDelegate):
    """Separators drawn as a line; rows without a checkbox are indented by the
    checkbox width so every icon and label lines up."""

    def paint(self, painter, option, index):
        data = index.data(ROLE)
        style = option.widget.style() if option.widget else QApplication.style()
        pad = style.pixelMetric(QStyle.PM_IndicatorWidth) + 6
        if isinstance(data, MenuItem) and data.separator:
            y = option.rect.center().y()
            painter.setPen(QColor("#c5c5c5"))
            painter.drawLine(option.rect.left() + pad, y, option.rect.right() - 2, y)
            return
        if index.data(Qt.CheckStateRole) is None:
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect.left(), option.rect.top(), pad,
                                 option.rect.height(), option.palette.highlight())
            option = QStyleOptionViewItem(option)
            option.rect = option.rect.adjusted(pad, 0, 0, 0)
        super().paint(painter, option, index)


def _error(e):
    return getattr(e, "strerror", None) or str(e)


class ContextMenuPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._built = False

        self.cmb_menu = QComboBox()
        for label, kind in KINDS:
            self.cmb_menu.addItem(label, kind)
        self.edt_path = QLineEdit(DEFAULT_PATH["folder"]())
        self.btn_browse = QPushButton("Browse")
        self.btn_reload = QPushButton("Reload")
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.cmb_menu)
        top.addWidget(self.edt_path, 1)
        top.addWidget(self.btn_browse)
        top.addWidget(self.btn_reload)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(16)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setItemDelegate(_MenuDelegate(self.tree))
        self.tree.setStyleSheet(
            "QTreeWidget { background: white; border: 1px solid #646464; }"
            "QTreeWidget::branch { image: none; border-image: none; }")

        self.grid = style_grid(QTableWidget(len(GRID_ROWS), 2))
        self.grid.horizontalHeader().setVisible(False)
        self.grid.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.grid.setTextElideMode(Qt.ElideMiddle)
        self.grid.setSelectionMode(QTableWidget.NoSelection)
        for r, name in enumerate(GRID_ROWS):
            self.grid.setItem(r, 0, QTableWidgetItem(name))
            self.grid.setItem(r, 1, QTableWidgetItem(""))
        self.grid.setFixedHeight(
            len(GRID_ROWS) * self.grid.verticalHeader().defaultSectionSize() + 4)
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.addWidget(self.grid)
        sv.addStretch(1)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.tree)
        split.addWidget(side)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)

        self.btn_preview = QPushButton("Preview")
        self.btn_apply = QPushButton("Apply")
        self.status = QLabel()
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        bottom.addWidget(self.btn_preview)
        bottom.addWidget(self.btn_apply)
        bottom.addWidget(self.status, 1)

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        v.addLayout(top)
        v.addWidget(split, 1)
        v.addLayout(bottom)

        self.cmb_menu.currentIndexChanged.connect(self._kind_changed)
        self.btn_browse.clicked.connect(self._browse)
        self.btn_reload.clicked.connect(lambda: self.reload())
        self.btn_preview.clicked.connect(lambda: self._popup_preview())
        self.btn_apply.clicked.connect(lambda: self.apply())
        self.tree.itemChanged.connect(self._toggled)
        self.tree.currentItemChanged.connect(self._show_source)

    def kind(self):
        return self.cmb_menu.currentData()

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._built:
            self._built = True
            self.reload()

    def _kind_changed(self):
        self.edt_path.setText(DEFAULT_PATH[self.kind()]())
        for w in (self.edt_path, self.btn_browse):
            w.setEnabled(self.kind() != "new")
        if self._built:
            self.reload()

    def _browse(self):
        if self.kind() == "file":
            path, _ = QFileDialog.getOpenFileName(self, "File", self.edt_path.text())
        else:
            path = QFileDialog.getExistingDirectory(self, "Folder", self.edt_path.text())
        if path:
            self.edt_path.setText(os.path.normpath(path))
            self.reload()

    # ---- tree ----
    def reload(self):
        kind = self.kind()
        self.tree.clear()
        self._show_source(None)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if kind == "new":
                items, gone = shellnew_menu(), shellnew_removed()
            else:
                items = load_menu(kind, self.edt_path.text())
                gone = [e for e in removed() if e.menu == kind]
        except (OSError, ValueError, pythoncom.com_error) as e:
            msg = _error(e)
            self.status.setText(msg)
            return msg
        finally:
            QApplication.restoreOverrideCursor()
        self.tree.blockSignals(True)
        root = self.tree.invisibleRootItem()
        self._add_rows(root, items)
        if gone:
            self._add_row(root, MenuItem("", separator=True))
            for e in gone:
                self._add_row(root, e)
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self._show_pending()
        return ""

    def _add_rows(self, parent, items, depth=0):
        for mi in items:
            it = self._add_row(parent, mi, depth)
            if mi.children:
                self._add_rows(it, mi.children, depth + 1)

    def _add_row(self, parent, data, depth=0):
        it = QTreeWidgetItem(parent)
        it.setData(0, ROLE, data)
        if isinstance(data, Removed):
            it.setText(0, data.text)
            font = it.font(0)
            font.setStrikeOut(True)
            it.setFont(0, font)
            it.setFlags(CHECKABLE)
            it.setCheckState(0, Qt.Unchecked)
            it.setSizeHint(0, QSize(0, ROW_H))
            return it
        if data.separator:
            it.setFlags(Qt.NoItemFlags)
            it.setSizeHint(0, QSize(0, SEP_H))
            return it
        it.setText(0, data.text)
        it.setFlags(PLAIN)
        it.setSizeHint(0, QSize(0, ROW_H))
        # a transparent icon keeps the label column aligned on icon-less rows
        it.setIcon(0, QIcon(data.icon or self._blank()))
        if data.source.kind == "builtin":
            it.setForeground(0, QBrush(QColor("gray")))
        elif depth == 0:
            it.setFlags(CHECKABLE)
            it.setCheckState(0, Qt.Checked)
        return it

    @staticmethod
    def _blank():
        pm = QPixmap(16, 16)
        pm.fill(Qt.transparent)
        return pm

    def _top_rows(self):
        return [self.tree.topLevelItem(i)
                for i in range(self.tree.topLevelItemCount())]

    def _pending(self):
        drop, back = {}, {}
        for it in self._top_rows():
            if not it.flags() & Qt.ItemIsUserCheckable:
                continue
            data = it.data(0, ROLE)
            if isinstance(data, Removed):
                if it.checkState(0) == Qt.Checked:
                    back[data.name] = data
            elif it.checkState(0) == Qt.Unchecked:
                src, texts = drop.setdefault(_record_name(data.source),
                                             (data.source, []))
                texts.append(data.text)
        return ([(src, ", ".join(dict.fromkeys(texts))) for src, texts in drop.values()],
                list(back.values()))

    def _toggled(self, item, _column=0):
        data = item.data(0, ROLE)
        if isinstance(data, MenuItem) and item.flags() & Qt.ItemIsUserCheckable:
            self.tree.blockSignals(True)
            for other in self._top_rows():
                twin = other.data(0, ROLE)
                if (isinstance(twin, MenuItem) and other is not item
                        and other.flags() & Qt.ItemIsUserCheckable
                        and _record_name(twin.source) == _record_name(data.source)):
                    other.setCheckState(0, item.checkState(0))
            self.tree.blockSignals(False)
        self._show_pending()

    def _show_pending(self):
        drop, back = self._pending()
        self.status.setText(f"{len(drop)} removed   {len(back)} restored")

    def _show_source(self, current, _previous=None):
        data = current.data(0, ROLE) if current is not None else None
        src = data.source if data is not None else None
        if src is None:
            values = ("",) * len(GRID_ROWS)
        else:
            label = src.label if src.kind == "builtin" else f"{src.kind}: {src.label}"
            values = (label, src.key, src.clsid, src.dll, src.scope)
        for r, text in enumerate(values):
            self.grid.item(r, 1).setText(text)

    # ---- actions ----
    def apply(self):
        drop, back = self._pending()
        kind = self.kind()
        error = ""
        what = ""
        try:
            for source, text in drop:
                what = text
                remove(source, text, kind)
            for entry in back:
                what = entry.text
                restore(entry)
        except OSError as e:
            error = f"{what}: {_error(e)}"
        rebuild = self.reload()
        done = error or f"{len(drop)} removed   {len(back)} restored"
        self.status.setText(f"{done}   {rebuild}" if rebuild else done)

    def preview_menu(self):
        menu = QMenu(self)
        dropped = {_record_name(src) for src, _text in self._pending()[0]}
        self._fill_menu(menu, self.tree.invisibleRootItem(), dropped)
        return menu

    def _fill_menu(self, menu, parent, dropped):
        gap = False
        for i in range(parent.childCount()):
            it = parent.child(i)
            data = it.data(0, ROLE)
            if isinstance(data, Removed):
                continue
            if data.separator:
                gap = True
                continue
            if data.source.kind != "builtin" and _record_name(data.source) in dropped:
                continue
            if gap and menu.actions():
                menu.addSeparator()
            gap = False
            icon = QIcon(data.icon) if data.icon else QIcon()
            text = data.text.replace("&", "&&")
            if it.childCount():
                self._fill_menu(menu.addMenu(icon, text), it, dropped)
            else:
                menu.addAction(icon, text)

    def _popup_preview(self):
        menu = self.preview_menu()
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.popup(self.btn_preview.mapToGlobal(
            QPoint(0, -menu.sizeHint().height())))
