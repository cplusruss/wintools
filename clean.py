#!/usr/bin/env python3
"""clean.py - disk, registry, uninstall and debloat pages for wintools."""

import ctypes
import ctypes.wintypes as wt
import heapq
import json
import os
import re
import subprocess
import threading
import time
import winreg
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

import pywintypes
import win32api
import win32con
import win32job
from PyQt5.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QIcon
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "clean"
CONFIG_PATH = CONFIG_DIR / "config.json"
REG_BACKUP_DIR = CONFIG_DIR / "reg-backups"
BATCH = 2000
MAX_CHILDREN_SHOWN = 5000
ROW_HEIGHT_PX = 16
CHECKED_ROW_BG = "#fff8b0"   # light yellow, same hue as the elevation banner


# =======================================================================
# Shared helpers
# =======================================================================

def human_size(n: int) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{int(n)} B" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} PB"


def _iter_files(root) -> Iterator[Tuple[str, int, int]]:
    root = os.fspath(root)
    if not os.path.isdir(root):
        return
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            scan = os.scandir(d)
        except OSError:
            continue
        with scan:
            for e in scan:
                try:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        try:
                            st = e.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        yield (e.path, int(st.st_size), int(st.st_mtime))
                except OSError:
                    continue


# =======================================================================
# Recycle Bin via Shell
# =======================================================================

SHERB_NOCONFIRMATION = 0x00000001
SHERB_NOPROGRESSUI = 0x00000002
SHERB_NOSOUND = 0x00000004


class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("i64Size", ctypes.c_longlong),
        ("i64NumItems", ctypes.c_longlong),
    ]


def query_recycle_bin() -> Tuple[int, int]:
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    res = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if res != 0:
        return 0, 0
    return int(info.i64Size), int(info.i64NumItems)


def empty_recycle_bin() -> int:
    flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    return ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)


FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
# Without this, "Yes to all" also answers the shell's own question for an item
# too big for the bin (or on a volume without one) and it is destroyed.
FOF_WANTNUKEWARNING = 0x4000


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("wFunc", wt.UINT), ("pFrom", wt.LPCWSTR),
                ("pTo", wt.LPCWSTR), ("fFlags", wt.WORD),
                ("fAnyOperationsAborted", wt.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wt.LPCWSTR)]


ctypes.windll.shell32.SHFileOperationW.restype = ctypes.c_int
ctypes.windll.shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]


def _file_op(op):
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))


MAX_PATH = 260


def recycle(paths):
    recycled, failed = [], []
    for path in paths:
        # With long paths enabled, SHFileOperationW can destroy a MAX_PATH+
        # item instead of recycling it, and \\?\ paths fail outright.
        if len(path) >= MAX_PATH:
            failed.append((path, "path too long"))
            continue
        # Qt's folder dialog returns forward slashes; normalise for the shell.
        op = SHFILEOPSTRUCTW(
            wFunc=FO_DELETE, pFrom=path.replace("/", "\\") + "\0",
            fFlags=(FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_WANTNUKEWARNING
                    | FOF_SILENT | FOF_NOERRORUI))
        rc = _file_op(op)
        if rc:
            failed.append((path, f"error 0x{rc:X}"))
        elif op.fAnyOperationsAborted:
            failed.append((path, "aborted"))
        else:
            recycled.append(path)
    return recycled, failed


# =======================================================================
# Elevation / UAC
# =======================================================================

# =======================================================================
# File scanners
# =======================================================================

def scan_windows_temp() -> Iterator[Tuple[str, int, int]]:
    seen = set()
    roots: List[str] = []
    for env in ("TEMP", "TMP"):
        v = os.environ.get(env)
        if v:
            roots.append(v)
    roots.append(r"C:\Windows\Temp")
    for r in roots:
        try:
            key = os.path.normcase(os.path.abspath(r))
        except OSError:
            key = r
        if key in seen:
            continue
        seen.add(key)
        yield from _iter_files(r)


def scan_browser_caches() -> Iterator[Tuple[str, int, int]]:
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    candidates = [
        os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cache"),
        os.path.join(local, "Google", "Chrome", "User Data", "Default", "Code Cache"),
        os.path.join(local, "Google", "Chrome", "User Data", "Default", "GPUCache"),
        os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Cache"),
        os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Code Cache"),
        os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "GPUCache"),
    ]
    for c in candidates:
        yield from _iter_files(c)
    ff = os.path.join(appdata, "Mozilla", "Firefox", "Profiles")
    if os.path.isdir(ff):
        try:
            for prof in os.scandir(ff):
                if prof.is_dir(follow_symlinks=False):
                    yield from _iter_files(os.path.join(prof.path, "cache2"))
        except OSError:
            pass


def scan_recent_thumbnails() -> Iterator[Tuple[str, int, int]]:
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    yield from _iter_files(os.path.join(appdata, "Microsoft", "Windows", "Recent"))
    explorer = os.path.join(local, "Microsoft", "Windows", "Explorer")
    if os.path.isdir(explorer):
        try:
            for e in os.scandir(explorer):
                if e.is_file(follow_symlinks=False) and (
                    e.name.startswith("thumbcache_") or e.name.startswith("iconcache_")
                ):
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    yield (e.path, int(st.st_size), int(st.st_mtime))
        except OSError:
            pass


@dataclass
class Category:
    key: str
    name: str
    description: str
    scanner: Optional[Callable[[], Iterator[Tuple[str, int, int]]]] = None
    special: Optional[str] = None


CATEGORIES = [
    Category("temp", "Windows Temp", "%TEMP% and C:\\Windows\\Temp", scan_windows_temp),
    Category("recycle", "Recycle Bin", "All drives", special="recycle_bin"),
    Category("browser", "Browser caches", "Chrome, Edge, Firefox", scan_browser_caches),
    Category("recent", "Recent & thumbnails", "Recent files, jump lists, thumbnail cache", scan_recent_thumbnails),
    Category("custom", "Custom paths", "", special="custom"),
]


# =======================================================================
# File scan / clean threads
# =======================================================================

class ScanController(QObject):
    # Byte counts go as object: a pyqtSignal int is 32-bit and wraps past 2 GB.
    files_batch = pyqtSignal(str, int, object)
    recycle_info = pyqtSignal(str, object, int)
    category_started = pyqtSignal(str)
    category_done = pyqtSignal(str)
    finished_all = pyqtSignal()

    def __init__(self, categories, custom_paths, parent=None):
        super().__init__(parent)
        self._cats = categories
        self._custom = list(custom_paths)
        self._stop = threading.Event()
        self.files_by_cat: dict = {c.key: [] for c in categories}
        self._executor: Optional[ThreadPoolExecutor] = None
        self._waiter: Optional[threading.Thread] = None

    def start(self):
        n = max(2, min(8, len(self._cats)))
        self._executor = ThreadPoolExecutor(max_workers=n, thread_name_prefix="clean-scan")
        futs = {}
        for cat in self._cats:
            futs[cat.key] = self._executor.submit(self._run_category, cat)
        self._waiter = threading.Thread(target=self._await_all, args=(futs,), daemon=True)
        self._waiter.start()

    def stop(self):
        self._stop.set()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _await_all(self, futs):
        for key, fut in futs.items():
            try:
                fut.result()
            except Exception:
                pass
            self.category_done.emit(key)
        if self._executor is not None:
            self._executor.shutdown(wait=False)
        self.finished_all.emit()

    def _iter_custom(self) -> Iterator[Tuple[str, int, int]]:
        for entry in self._custom:
            if self._stop.is_set():
                return
            if os.path.isfile(entry):
                try:
                    st = os.stat(entry)
                except OSError:
                    continue
                yield (entry, int(st.st_size), int(st.st_mtime))
            elif os.path.isdir(entry):
                yield from _iter_files(entry)

    def _run_category(self, cat: Category):
        self.category_started.emit(cat.key)
        if cat.special == "recycle_bin":
            size, n = query_recycle_bin()
            self.recycle_info.emit(cat.key, size, n)
            return
        if cat.special == "custom":
            it = self._iter_custom()
        elif cat.scanner is not None:
            it = cat.scanner()
        else:
            return
        bucket = self.files_by_cat[cat.key]
        batch_count = 0
        batch_bytes = 0
        for tup in it:
            if self._stop.is_set():
                break
            bucket.append(tup)
            batch_count += 1
            batch_bytes += tup[1]
            if batch_count >= BATCH:
                self.files_batch.emit(cat.key, batch_count, batch_bytes)
                batch_count = 0
                batch_bytes = 0
        if batch_count:
            self.files_batch.emit(cat.key, batch_count, batch_bytes)


class CleanWorker(QThread):
    progress = pyqtSignal(int, int)
    item_error = pyqtSignal(str, str)
    finished_all = pyqtSignal(int, int, object)

    def __init__(self, paths_to_recycle, empty_recycle, recycle_bytes_estimate, parent=None):
        super().__init__(parent)
        self._paths = list(paths_to_recycle)
        self._empty = empty_recycle
        self._recycle_bytes = recycle_bytes_estimate
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        total = len(self._paths) + (1 if self._empty else 0)
        ok = 0
        fail = 0
        freed = 0
        for i, (path, size) in enumerate(self._paths):
            if self._stop:
                break
            _done, failed = recycle([os.fspath(path)])
            if failed:
                fail += 1
                self.item_error.emit(path, failed[0][1])
            else:
                ok += 1
                freed += size
            if (i + 1) % 50 == 0 or i + 1 == len(self._paths):
                self.progress.emit(i + 1, total)
        if self._empty and not self._stop:
            try:
                empty_recycle_bin()
                ok += 1
                freed += self._recycle_bytes
            except Exception as e:
                fail += 1
                self.item_error.emit("<Recycle Bin>", str(e))
            self.progress.emit(total, total)
        self.finished_all.emit(ok, fail, freed)


# =======================================================================
# Registry: helpers, walker, deleter
# =======================================================================

HIVES = [
    ("HKCU", winreg.HKEY_CURRENT_USER),
    ("HKLM", winreg.HKEY_LOCAL_MACHINE),
    ("HKCR", winreg.HKEY_CLASSES_ROOT),
    ("HKU",  winreg.HKEY_USERS),
    ("HKCC", winreg.HKEY_CURRENT_CONFIG),
]
HIVES_BY_NAME = {n: h for n, h in HIVES}
HIVE_FULL_NAMES = {
    "HKCU": "HKEY_CURRENT_USER",
    "HKLM": "HKEY_LOCAL_MACHINE",
    "HKCR": "HKEY_CLASSES_ROOT",
    "HKU":  "HKEY_USERS",
    "HKCC": "HKEY_CURRENT_CONFIG",
}


def open_in_regedit(hive_name: str, key_path: str) -> Tuple[bool, str]:
    """Launch regedit.exe pre-positioned at hive_name\\key_path. Regedit reads
    HKCU\\...\\Applets\\Regedit\\LastKey only at startup; if an instance is
    already running, plain re-launch just foregrounds the existing window at
    its current location. So: kill any running regedit, write LastKey, then
    launch a fresh instance."""
    full_hive = HIVE_FULL_NAMES.get(hive_name)
    if not full_hive:
        return False, f"unknown hive: {hive_name}"
    full = f"Computer\\{full_hive}\\{key_path}" if key_path else f"Computer\\{full_hive}"

    killed = False
    try:
        cp = subprocess.run(
            ["taskkill", "/IM", "regedit.exe", "/F"],
            capture_output=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        killed = (cp.returncode == 0)
    except Exception:
        pass
    if killed:
        # Brief pause so Windows finishes tearing the old process down before
        # the new one starts reading LastKey.
        time.sleep(0.15)

    try:
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit",
        ) as k:
            winreg.SetValueEx(k, "LastKey", 0, winreg.REG_SZ, full)
    except OSError as e:
        return False, f"could not set LastKey: {e}"

    try:
        subprocess.Popen(
            ["regedit.exe"], shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        return False, f"could not launch regedit.exe: {e}"
    return True, full


def reg_key_info(hive_handle, sub_path: str) -> Optional[Tuple[int, int]]:
    """Return (n_subkeys, n_values) or None if the key is unreadable."""
    try:
        with winreg.OpenKey(hive_handle, sub_path, 0, winreg.KEY_READ) as k:
            n_sub, n_val, _ = winreg.QueryInfoKey(k)
            return int(n_sub), int(n_val)
    except OSError:
        return None


def predict_empty_parents(hive_handle, matched_paths: List[str]) -> set:
    """Given the set of paths that *will* be deleted under one hive, return
    the set of additional parent paths that would also become empty (no values,
    no surviving subkeys) once the matched paths are gone. Walks deepest-first
    so cascading grandparents are caught.
    """
    will_delete = set(matched_paths)
    candidates = set()
    for m in matched_paths:
        parts = m.split("\\")
        for d in range(len(parts) - 1, 0, -1):
            candidates.add("\\".join(parts[:d]))
    extras = set()
    for cp in sorted(candidates, key=lambda p: -p.count("\\")):
        try:
            with winreg.OpenKey(hive_handle, cp, 0, winreg.KEY_READ) as k:
                n_sub, n_val, _ = winreg.QueryInfoKey(k)
                if n_val > 0:
                    continue
                names = [winreg.EnumKey(k, i) for i in range(n_sub)]
        except OSError:
            continue
        if all((cp + "\\" + name) in will_delete for name in names):
            will_delete.add(cp)
            extras.add(cp)
    return extras


def attribute_cascade(matched_path: str, empty_parents: set) -> List[str]:
    """Per-row preview: walking up from matched_path, list the parents that
    are in empty_parents until we hit one that isn't."""
    parts = matched_path.split("\\")
    chain = []
    for d in range(len(parts) - 1, 0, -1):
        parent = "\\".join(parts[:d])
        if parent in empty_parents:
            chain.append(parent)
        else:
            break
    return chain


# Keys no cleanup may delete, nor any key above them (deleting a parent takes
# them along). Environment holds PATH: without it every newly started process,
# elevated ones included, gets an empty PATH. Paths are lowercase.
_SM = r"\control\session manager"
PROTECTED_KEYS = {
    "HKLM": (
        *(cs + _SM + r"\environment" for cs in
          (r"system\currentcontrolset", r"system\controlset001", r"system\controlset002")),
        r"software\microsoft\windows\currentversion\run",
        r"software\microsoft\windows\currentversion\runonce",
        r"software\wow6432node\microsoft\windows\currentversion\run",
        r"software\microsoft\windows\currentversion\uninstall",
        r"software\wow6432node\microsoft\windows\currentversion\uninstall",
        r"software\microsoft\windows\currentversion\app paths",
        r"software\microsoft\windows\currentversion\shareddlls",
        r"software\microsoft\windows nt\currentversion",
        r"software\classes\clsid",
        r"software\classes\typelib",
    ),
    "HKCU": (
        "environment",
        r"volatile environment",
        r"software\microsoft\windows\currentversion\run",
        r"software\microsoft\windows\currentversion\runonce",
        r"software\microsoft\windows\currentversion\uninstall",
        r"software\classes\clsid",
    ),
    "HKCR": ("clsid", "typelib", r"wow6432node\clsid", r"wow6432node\typelib"),
}
_HIVE_NAMES = {h: n for n, h in HIVES}


def is_protected_key(hive_name: str, path: str) -> bool:
    """True for a protected key, any key above one, and a hive root."""
    p = path.strip("\\").lower()
    if not p:
        return True
    return any(k == p or k.startswith(p + "\\") for k in PROTECTED_KEYS.get(hive_name, ()))


def reg_delete_recursive(hive_handle, path: str):
    """Delete a registry key and all its descendants. Raises OSError on failure,
    and PermissionError without touching anything for a protected key."""
    hive_name = _HIVE_NAMES.get(hive_handle, "")
    if is_protected_key(hive_name, path):
        raise PermissionError(f"refusing to delete protected key {hive_name}\\{path}")
    try:
        with winreg.OpenKey(hive_handle, path, 0, winreg.KEY_READ) as k:
            n_sub, _, _ = winreg.QueryInfoKey(k)
            sub_names = [winreg.EnumKey(k, i) for i in range(n_sub)]
    except OSError:
        sub_names = []
    for name in sub_names:
        try:
            reg_delete_recursive(hive_handle, path + "\\" + name)
        except OSError:
            pass
    winreg.DeleteKey(hive_handle, path)


def reg_export(hive_name: str, path: str, outfile: str) -> Tuple[bool, str]:
    """Shell out to reg.exe export. Returns (ok, msg)."""
    full = f"{hive_name}\\{path}"
    try:
        cp = subprocess.run(
            ["reg", "export", full, outfile, "/y"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if cp.returncode == 0:
            return True, ""
        return False, (cp.stderr or cp.stdout or f"reg export rc={cp.returncode}").strip()
    except Exception as e:
        return False, str(e)


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_filename(s: str) -> str:
    return _SAFE_NAME_RE.sub("_", s)[:120] or "key"


class RegistrySearchWorker(QThread):
    # value_matches is a list of (value_name, value_data, name_hit, data_hit) tuples
    match = pyqtSignal(str, str, int, int, bool, list)
    progress = pyqtSignal(str, int)
    finished_all = pyqtSignal(int)

    def __init__(self, needle: str, hives: List[str],
                 search_values: bool = True, parent=None,
                 needle2: str = "", mode: str = "AND NOT"):
        super().__init__(parent)
        self._needle = needle.lower()
        self._needle2 = (needle2 or "").lower()
        # mode is only meaningful when needle2 is non-empty.
        self._mode = mode if mode in ("AND NOT", "OR") else "AND NOT"
        self._hives = list(hives)
        self._search_values = bool(search_values)
        self._stop = False
        self._matches = 0
        self._last_progress = 0.0

    def request_stop(self):
        self._stop = True

    def run(self):
        for hive_name in self._hives:
            if self._stop:
                break
            hive_h = HIVES_BY_NAME.get(hive_name)
            if hive_h is None:
                continue
            self._walk(hive_h, hive_name, "")
        self.finished_all.emit(self._matches)

    def _emit_progress(self, hive_name: str, sub: str):
        now = time.monotonic()
        if now - self._last_progress < 0.1:
            return
        self._last_progress = now
        loc = f"{hive_name}\\{sub}" if sub else hive_name
        self.progress.emit(loc, self._matches)

    def _check_values(self, hive_handle, path: str):
        """Open the key, return (n_sub, n_val, records).

        records is a list of
            (name, data, p_name, p_data, s_name, s_data)
        tuples for every value whose name or data contains the primary
        OR secondary needle. The four bool flags distinguish which needle
        matched which field. On error, returns (None, None, []).
        """
        try:
            with winreg.OpenKey(hive_handle, path, 0, winreg.KEY_READ) as k:
                n_sub, n_val, _ = winreg.QueryInfoKey(k)
                records = []
                has2 = bool(self._needle2)
                for i in range(n_val):
                    if self._stop:
                        break
                    try:
                        nm, data, _typ = winreg.EnumValue(k, i)
                    except OSError:
                        continue
                    nm_lc = nm.lower() if isinstance(nm, str) else ""
                    data_lc = data.lower() if isinstance(data, str) else ""
                    p_name = bool(nm_lc) and self._needle in nm_lc
                    p_data = bool(data_lc) and self._needle in data_lc
                    s_name = has2 and bool(nm_lc) and self._needle2 in nm_lc
                    s_data = has2 and bool(data_lc) and self._needle2 in data_lc
                    if p_name or p_data or s_name or s_data:
                        records.append((
                            nm or "",
                            str(data) if isinstance(data, str) else "",
                            p_name, p_data, s_name, s_data,
                        ))
                return n_sub, n_val, records
        except OSError:
            return None, None, []

    def _walk(self, hive_handle, hive_name: str, sub: str):
        if self._stop:
            return
        try:
            k = winreg.OpenKey(hive_handle, sub, 0, winreg.KEY_READ)
        except OSError:
            return
        try:
            try:
                n_sub, _, _ = winreg.QueryInfoKey(k)
            except OSError:
                return
            self._emit_progress(hive_name, sub)
            has2 = bool(self._needle2)
            for i in range(n_sub):
                if self._stop:
                    return
                try:
                    name = winreg.EnumKey(k, i)
                except OSError:
                    break
                child = (sub + "\\" + name) if sub else name
                child_lc = child.lower()
                p_key = self._needle in child_lc
                s_key = has2 and self._needle2 in child_lc
                cs = cv = 0
                records: list = []
                if self._search_values:
                    cs_v, cv_v, records = self._check_values(hive_handle, child)
                    if cs_v is not None:
                        cs, cv = cs_v, cv_v
                p_vals = [r for r in records if r[2] or r[3]]
                s_vals = [r for r in records if r[4] or r[5]]
                if not has2:
                    hit = p_key or bool(p_vals)
                    key_match = p_key
                    value_matches = [(r[0], r[1], r[2], r[3]) for r in p_vals]
                elif self._mode == "AND NOT":
                    hit = (p_key or bool(p_vals)) and not (s_key or bool(s_vals))
                    key_match = p_key
                    value_matches = [(r[0], r[1], r[2], r[3]) for r in p_vals]
                else:  # OR
                    hit = p_key or s_key or bool(p_vals) or bool(s_vals)
                    key_match = p_key or s_key
                    # Merge: each record's name_hit / data_hit = OR over both needles.
                    value_matches = [
                        (r[0], r[1], r[2] or r[4], r[3] or r[5])
                        for r in records
                    ]
                if hit:
                    if cs == 0 and cv == 0:
                        info = reg_key_info(hive_handle, child)
                        if info:
                            cs, cv = info
                    self._matches += 1
                    self.match.emit(hive_name, child, cs, cv, key_match, value_matches)
                    # Recurse only if we didn't match by key path — descendants of
                    # a key-matched node are implicit. Value-only matches still
                    # need recursion so deeper subkeys aren't missed.
                    if not key_match:
                        self._walk(hive_handle, hive_name, child)
                else:
                    self._walk(hive_handle, hive_name, child)
        finally:
            try:
                k.Close()
            except Exception:
                pass


class RegistryDeleteWorker(QThread):
    progress = pyqtSignal(int, int, str)         # done, total, current_label
    item_error = pyqtSignal(str, str)
    backup_done = pyqtSignal(str, int, int)      # folder, ok, fail
    finished_all = pyqtSignal(int, int)          # ok, fail

    def __init__(self, targets: List[Tuple[str, str]], do_backup: bool, parent=None):
        """targets: list of (hive_name, key_path) to delete (cascade-included)."""
        super().__init__(parent)
        self._targets = list(targets)
        self._do_backup = do_backup
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        # Deepest first so children are gone before parents are attempted.
        ordered = sorted(self._targets, key=lambda t: -t[1].count("\\"))
        # Backup pass (only for original matches, not pure cascade parents — but the
        # caller passes whatever it considers important; we back up everything we'll touch).
        backup_dir = ""
        if self._do_backup:
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup_dir = str(REG_BACKUP_DIR / ts)
            os.makedirs(backup_dir, exist_ok=True)
            bok = bfail = 0
            for i, (hive_name, path) in enumerate(ordered):
                if self._stop:
                    break
                fname = _safe_filename(f"{hive_name}__{path.replace(chr(92), '__')}") + ".reg"
                out = os.path.join(backup_dir, fname)
                ok, msg = reg_export(hive_name, path, out)
                if ok:
                    bok += 1
                else:
                    bfail += 1
                    self.item_error.emit(f"backup {hive_name}\\{path}", msg)
                self.progress.emit(i + 1, len(ordered), f"Backing up: {hive_name}\\{path}")
            self.backup_done.emit(backup_dir, bok, bfail)

        ok = fail = 0
        total = len(ordered)
        for i, (hive_name, path) in enumerate(ordered):
            if self._stop:
                break
            hive_h = HIVES_BY_NAME.get(hive_name)
            if hive_h is None:
                fail += 1
                self.item_error.emit(f"{hive_name}\\{path}", "unknown hive")
                continue
            try:
                reg_delete_recursive(hive_h, path)
                ok += 1
            except OSError as e:
                fail += 1
                self.item_error.emit(f"{hive_name}\\{path}", str(e))
            except Exception as e:
                fail += 1
                self.item_error.emit(f"{hive_name}\\{path}", str(e))
            self.progress.emit(i + 1, total, f"Deleting: {hive_name}\\{path}")
        self.finished_all.emit(ok, fail)


# ";" ends a candidate (PATH-style lists are many paths, not one long one), and
# the extension must end the path, so a folder like "ImageMagick-7.1.1-Q16" is
# not read as the file "ImageMagick-7.1"
_PATH_CANDIDATE_RE = re.compile(
    r"(?:"
    r"[A-Za-z]:\\[^\"<>|?*;\r\n]+?\.[A-Za-z0-9]{1,8}"
    r"|%[A-Za-z_][A-Za-z0-9_]*%\\[^\"<>|?*;\r\n]+?\.[A-Za-z0-9]{1,8}"
    r"|\\\\[^\"<>|?*;\r\n]+?\.[A-Za-z0-9]{1,8}"
    r")(?=$|[\s\"',;])",
    re.IGNORECASE,
)


def extract_path_candidate(value) -> str:
    """If a registry value contains a recognizable filesystem path-with-
    extension (drive letter, UNC, or %ENV%-prefixed), return the path
    (env-expanded). Empty string otherwise.

    Handles quoted command lines: '"C:\\App\\app.exe" --flag' -> 'C:\\App\\app.exe'
    Handles buried paths: 'regsvr32 /s "C:\\foo.dll"' -> 'C:\\foo.dll'
    """
    if not isinstance(value, str):
        return ""
    s = value.strip()
    if not s:
        return ""
    if s.startswith('"'):
        end = s.find('"', 1)
        if end > 0:
            m = _PATH_CANDIDATE_RE.search(s[1:end])
            if m:
                return os.path.expandvars(m.group(0))
    m = _PATH_CANDIDATE_RE.search(s)
    if m:
        return os.path.expandvars(m.group(0))
    return ""


def _path_exists(p: str) -> bool:
    try:
        return os.path.exists(p)
    except OSError:
        return False


@dataclass
class OrphanMatch:
    hive_name: str
    key_path: str
    value_name: str       # "" for the default value
    value_data: str
    missing_path: str
    n_sub: int = 0
    n_val: int = 0


# Hot-spots: (hive_name, sub_path, check_value_names). check_value_names=True
# is for SharedDlls, where the *value name* itself is the file path.
ORPHAN_HOTSPOTS = [
    ("HKCR", r"TypeLib", False),
    ("HKCR", r"CLSID", False),
    ("HKCR", r"WOW6432Node\TypeLib", False),
    ("HKCR", r"WOW6432Node\CLSID", False),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths", False),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths", False),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\SharedDlls", True),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", False),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", False),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", False),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\RunOnce", False),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", False),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", False),
]


class OrphanScanWorker(QThread):
    match = pyqtSignal(object)                 # OrphanMatch
    progress = pyqtSignal(str, int)            # location, total_found_so_far
    finished_all = pyqtSignal(int)             # total

    def __init__(self, hives: List[str], deep: bool, parent=None):
        super().__init__(parent)
        self._hives = list(hives)
        self._deep = deep
        self._stop = False
        self._count = 0
        self._last_progress = 0.0

    def request_stop(self):
        self._stop = True

    def _scan_subtree(self, hive_h, hive_name: str, base_path: str,
                      check_value_names: bool):
        queue = [base_path]
        while queue:
            if self._stop:
                return
            sub = queue.pop()
            try:
                k = winreg.OpenKey(hive_h, sub, 0, winreg.KEY_READ)
            except OSError:
                continue
            try:
                try:
                    n_sub, n_val, _ = winreg.QueryInfoKey(k)
                except OSError:
                    continue
                for i in range(n_val):
                    if self._stop:
                        return
                    try:
                        name, data, _typ = winreg.EnumValue(k, i)
                    except OSError:
                        continue
                    cand = ""
                    if isinstance(data, str):
                        cand = extract_path_candidate(data)
                    if not cand and check_value_names and isinstance(name, str):
                        cand = extract_path_candidate(name)
                    if cand and not _path_exists(cand):
                        self._count += 1
                        self.match.emit(OrphanMatch(
                            hive_name=hive_name, key_path=sub,
                            value_name=name or "",
                            value_data=data if isinstance(data, str) else "",
                            missing_path=cand,
                            n_sub=n_sub, n_val=n_val,
                        ))
                for i in range(n_sub):
                    if self._stop:
                        return
                    try:
                        sn = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    queue.append((sub + "\\" + sn) if sub else sn)
            finally:
                try:
                    k.Close()
                except Exception:
                    pass
            now = time.monotonic()
            if now - self._last_progress > 0.1:
                self._last_progress = now
                loc = f"{hive_name}\\{sub}" if sub else hive_name
                self.progress.emit(loc, self._count)

    def run(self):
        if self._deep:
            for hive_name in self._hives:
                if self._stop:
                    break
                hive_h = HIVES_BY_NAME.get(hive_name)
                if hive_h is None:
                    continue
                self._scan_subtree(hive_h, hive_name, "", False)
        else:
            for hive_name, sub_path, check_names in ORPHAN_HOTSPOTS:
                if self._stop:
                    break
                if hive_name not in self._hives:
                    continue
                hive_h = HIVES_BY_NAME.get(hive_name)
                if hive_h is None:
                    continue
                self._scan_subtree(hive_h, hive_name, sub_path, check_names)
        self.finished_all.emit(self._count)


class RegistryBackupWorker(QThread):
    """Standalone backup pass: exports each target key to its own .reg file
    under %APPDATA%\\clean\\reg-backups\\manual_<timestamp>\\."""
    progress = pyqtSignal(int, int, str)
    item_error = pyqtSignal(str, str)
    finished_all = pyqtSignal(str, int, int)   # folder, ok, fail

    def __init__(self, targets: List[Tuple[str, str]], parent=None):
        super().__init__(parent)
        self._targets = list(targets)
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        ts = time.strftime("%Y%m%d_%H%M%S")
        folder = str(REG_BACKUP_DIR / f"manual_{ts}")
        os.makedirs(folder, exist_ok=True)
        ok = fail = 0
        total = len(self._targets)
        for i, (hive_name, path) in enumerate(self._targets):
            if self._stop:
                break
            fname = _safe_filename(f"{hive_name}__{path.replace(chr(92), '__')}") + ".reg"
            out = os.path.join(folder, fname)
            success, msg = reg_export(hive_name, path, out)
            if success:
                ok += 1
            else:
                fail += 1
                self.item_error.emit(f"{hive_name}\\{path}", msg)
            self.progress.emit(i + 1, total, f"Backing up: {hive_name}\\{path}")
        self.finished_all.emit(folder, ok, fail)


# =======================================================================
# Small-icon extraction from .exe / .dll resources
# =======================================================================

_shell32 = ctypes.windll.shell32
_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32

_shell32.ExtractIconExW.argtypes = [
    wt.LPCWSTR, ctypes.c_int,
    ctypes.POINTER(wt.HICON), ctypes.POINTER(wt.HICON), wt.UINT,
]
_shell32.ExtractIconExW.restype = wt.UINT

_user32.DestroyIcon.argtypes = [wt.HICON]
_user32.DestroyIcon.restype = wt.BOOL
_user32.GetDC.argtypes = [wt.HWND]
_user32.GetDC.restype = wt.HDC
_user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
_user32.ReleaseDC.restype = ctypes.c_int
_user32.DrawIconEx.argtypes = [
    wt.HDC, ctypes.c_int, ctypes.c_int, wt.HICON,
    ctypes.c_int, ctypes.c_int, wt.UINT, ctypes.c_void_p, wt.UINT,
]
_user32.DrawIconEx.restype = wt.BOOL

_gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
_gdi32.CreateCompatibleDC.restype = wt.HDC
_gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
_gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
_gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
_gdi32.SelectObject.restype = wt.HGDIOBJ
_gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
_gdi32.DeleteObject.restype = wt.BOOL
_gdi32.DeleteDC.argtypes = [wt.HDC]
_gdi32.DeleteDC.restype = wt.BOOL
_gdi32.GetDIBits.argtypes = [
    wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT,
    ctypes.c_void_p, ctypes.c_void_p, wt.UINT,
]
_gdi32.GetDIBits.restype = ctypes.c_int


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


_DI_NORMAL = 0x0003


def _hicon_to_qpixmap(hicon, size=16):
    """Render a Win32 HICON onto a 32bpp bitmap and wrap as a QPixmap.
    Returns None if hicon is null or conversion fails."""
    if not hicon:
        return None
    from PyQt5.QtGui import QImage, QPixmap
    hdc = _user32.GetDC(None)
    mem_dc = _gdi32.CreateCompatibleDC(hdc)
    bmp = _gdi32.CreateCompatibleBitmap(hdc, size, size)
    old = _gdi32.SelectObject(mem_dc, bmp)
    _user32.DrawIconEx(mem_dc, 0, 0, hicon, size, size, 0, None, _DI_NORMAL)
    bi = _BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = size
    bi.bmiHeader.biHeight = -size  # top-down
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0  # BI_RGB
    buf = (ctypes.c_ubyte * (size * size * 4))()
    _gdi32.GetDIBits(mem_dc, bmp, 0, size, buf, ctypes.byref(bi), 0)
    _gdi32.SelectObject(mem_dc, old)
    _gdi32.DeleteObject(bmp)
    _gdi32.DeleteDC(mem_dc)
    _user32.ReleaseDC(None, hdc)
    # On Windows, Format_ARGB32 in memory is BGRA — matches GetDIBits output.
    img = QImage(bytes(buf), size, size, QImage.Format_ARGB32)
    pix = QPixmap.fromImage(img.copy())
    if pix.isNull():
        return None
    return pix


def _parse_display_icon(s: str) -> Tuple[str, int]:
    """DisplayIcon registry values come in a handful of shapes:
        "C:\\path\\foo.exe,2"      -> ('C:\\path\\foo.exe', 2)
        C:\\path\\foo.exe,-100     -> ('C:\\path\\foo.exe', -100)  (negative = resource ID)
        C:\\path\\bar.ico          -> ('C:\\path\\bar.ico', 0)
    """
    if not s:
        return "", 0
    s = s.strip()
    if s.startswith('"'):
        end = s.find('"', 1)
        if end > 0:
            path = s[1:end]
            rest = s[end + 1:].strip()
            idx = 0
            if rest.startswith(","):
                try:
                    idx = int(rest[1:].strip())
                except ValueError:
                    idx = 0
            return path, idx
        return s.strip('"'), 0
    if "," in s:
        path, n = s.rsplit(",", 1)
        try:
            return path.strip(), int(n.strip())
        except ValueError:
            return s, 0
    return s, 0


def extract_small_icon(display_icon: str, fallback_exe: str = ""):
    """Return a 16x16 QPixmap extracted from a DisplayIcon spec, optionally
    falling back to fallback_exe. Returns None when nothing renders."""
    candidates = []
    if display_icon:
        candidates.append(_parse_display_icon(display_icon))
    if fallback_exe:
        candidates.append((fallback_exe, 0))
    for path, idx in candidates:
        if not path:
            continue
        expanded = os.path.expandvars(path)
        if not os.path.isfile(expanded):
            continue
        pix = _extract_icon_from_path(expanded, idx)
        if pix is not None:
            return pix
    return None


def _extract_icon_from_path(path: str, idx: int = 0, size: int = 16):
    """ExtractIconExW + GDI render to QPixmap. Returns None on failure."""
    large = wt.HICON()
    small = wt.HICON()
    try:
        rc = _shell32.ExtractIconExW(
            path, idx, ctypes.byref(large), ctypes.byref(small), 1)
    except Exception:
        return None
    if rc < 1:
        return None
    try:
        hicon = small.value or large.value
        if not hicon:
            return None
        pix = _hicon_to_qpixmap(hicon, size)
        if pix is not None and not pix.isNull():
            return pix
        return None
    finally:
        if small.value:
            _user32.DestroyIcon(small)
        if large.value:
            _user32.DestroyIcon(large)


# ----- SHGetFileInfo (system-associated file-type icon) -------------------

SHGFI_ICON = 0x00000100
SHGFI_SMALLICON = 0x00000001
SHGFI_USEFILEATTRIBUTES = 0x00000010
FILE_ATTRIBUTE_NORMAL = 0x00000080


class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wt.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wt.DWORD),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


_shell32.SHGetFileInfoW.argtypes = [
    wt.LPCWSTR, wt.DWORD, ctypes.POINTER(_SHFILEINFOW),
    wt.UINT, wt.UINT,
]
_shell32.SHGetFileInfoW.restype = ctypes.c_void_p


def _shgetfileinfo_icon(path: str, size: int = 16):
    """System-associated icon via SHGetFileInfoW. Used when ExtractIconExW
    returns nothing (e.g., a registry entry referencing a folder or a file
    type that has no embedded icon resources)."""
    if not path:
        return None
    info = _SHFILEINFOW()
    flags = SHGFI_ICON | SHGFI_SMALLICON
    if not os.path.exists(path):
        flags |= SHGFI_USEFILEATTRIBUTES
    try:
        rc = _shell32.SHGetFileInfoW(
            path, FILE_ATTRIBUTE_NORMAL,
            ctypes.byref(info), ctypes.sizeof(info), flags)
    except Exception:
        return None
    if not rc or not info.hIcon:
        return None
    try:
        pix = _hicon_to_qpixmap(info.hIcon, size)
        if pix is not None and not pix.isNull():
            return pix
        return None
    finally:
        _user32.DestroyIcon(info.hIcon)


# Generic fallback: 'application' icon from shell32.dll (cogwheel).
GENERIC_ICON_SOURCE = (
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                 "System32", "shell32.dll"),
    24,
)


def _icon_candidates_for(e) -> List[Tuple[str, int]]:
    """Ordered list of (path, icon_index) sources to try for one UninstallEntry."""
    cands: List[Tuple[str, int]] = []
    if e.display_icon:
        p, i = _parse_display_icon(e.display_icon)
        if p:
            cands.append((p, i))
    exe = _extract_exe_from_command(e.uninstall_string)
    if exe and os.path.basename(exe).lower() not in ("msiexec.exe", "msiexec"):
        cands.append((exe, 0))
    if e.quiet_uninstall_string:
        qexe = _extract_exe_from_command(e.quiet_uninstall_string)
        if qexe and os.path.basename(qexe).lower() not in ("msiexec.exe", "msiexec"):
            cands.append((qexe, 0))
    if e.install_location:
        loc = e.install_location.strip().strip('"')
        loc = os.path.expandvars(loc)
        if loc and os.path.isdir(loc):
            picked = False
            for name in ("unins000.exe", "uninstall.exe", "uninst.exe",
                         "setup.exe", "install.exe"):
                p = os.path.join(loc, name)
                if os.path.isfile(p):
                    cands.append((p, 0))
                    picked = True
                    break
            if not picked:
                try:
                    for f in os.listdir(loc):
                        if f.lower().endswith(".exe"):
                            cands.append((os.path.join(loc, f), 0))
                            break
                except OSError:
                    pass
    return cands


def extract_icon_for_entry(e, use_generic_fallback: bool = True):
    """Try every known icon source for an UninstallEntry.
    Order: DisplayIcon -> UninstallString exe -> QuietUninstallString exe ->
    InstallLocation exe -> SHGetFileInfo on each candidate -> generic shell32.
    """
    for path, idx in _icon_candidates_for(e):
        expanded = os.path.expandvars(path)
        if not os.path.isfile(expanded):
            continue
        pix = _extract_icon_from_path(expanded, idx)
        if pix is not None:
            return pix
    for path, _idx in _icon_candidates_for(e):
        expanded = os.path.expandvars(path)
        pix = _shgetfileinfo_icon(expanded)
        if pix is not None:
            return pix
    if use_generic_fallback:
        gp, gi = GENERIC_ICON_SOURCE
        return _extract_icon_from_path(gp, gi)
    return None


# =======================================================================
# Uninstall: enumerate Add/Remove Programs, run or remove entries
# =======================================================================

UNINSTALL_LOCATIONS = [
    ("HKLM", winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "64-bit"),
    ("HKLM", winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", "32-bit"),
    ("HKCU", winreg.HKEY_CURRENT_USER,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "user"),
]


@dataclass
class UninstallEntry:
    hive_name: str
    hive_handle: int
    arch_tag: str
    parent_path: str
    sub_name: str
    key_path: str
    display_name: str
    display_version: str
    publisher: str
    install_date: str
    install_location: str
    uninstall_string: str
    quiet_uninstall_string: str
    display_icon: str
    estimated_size_kb: int
    system_component: bool
    parent_key_name: str
    is_msi: bool
    is_valid: bool
    invalid_reason: str

    @property
    def display(self) -> str:
        return self.display_name or self.sub_name


def _extract_exe_from_command(cmd: str) -> str:
    s = (cmd or "").strip()
    if not s:
        return ""
    if s.startswith('"'):
        end = s.find('"', 1)
        if end > 0:
            return s[1:end]
        return s.strip('"')
    lower = s.lower()
    idx = lower.find(".exe")
    if idx > 0:
        return s[: idx + 4]
    return s.split()[0]


MSI_PRODUCT = re.compile(r"\{[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}\}")
INNO_UNINSTALLER = re.compile(r"^unins\d{3}\.exe$", re.I)
NSIS_UNINSTALLER = re.compile(r"^(un|uninst|uninstall|uninstaller)[\w .\-]*\.exe$", re.I)
_nsis_cache: dict = {}


def _is_nsis(exe: str) -> bool:
    # NSIS uninstallers are small and carry "Nullsoft" in their stub
    key = os.path.normcase(exe)
    if key not in _nsis_cache:
        try:
            with open(exe, "rb") as f:
                _nsis_cache[key] = b"Nullsoft" in f.read(512 * 1024)
        except OSError:
            _nsis_cache[key] = False
    return _nsis_cache[key]


def silent_command(e: "UninstallEntry") -> Tuple[str, str]:
    """The command that uninstalls without the program's own dialogs, and how
    ("quiet", "msi", "inno", "nsis"); the plain UninstallString and "" when
    no silent form is known."""
    if e.quiet_uninstall_string:
        return e.quiet_uninstall_string, "quiet"
    cmd = e.uninstall_string or ""
    exe = _extract_exe_from_command(cmd)
    base = os.path.basename(exe)
    if base.lower() in ("msiexec.exe", "msiexec") or (e.is_msi and not cmd):
        m = MSI_PRODUCT.search(cmd) or MSI_PRODUCT.search(e.sub_name)
        if m:
            return f"MsiExec.exe /X{m.group(0)} /passive /norestart", "msi"
    if INNO_UNINSTALLER.match(base):
        return f"{cmd} /VERYSILENT /SUPPRESSMSGBOXES /NORESTART", "inno"
    if NSIS_UNINSTALLER.match(base) and _is_nsis(os.path.expandvars(exe)):
        return f"{cmd} /S", "nsis"
    return cmd, ""


def _check_uninstaller_validity(entry: "UninstallEntry") -> Tuple[bool, str]:
    cmd = entry.uninstall_string or entry.quiet_uninstall_string
    if not cmd:
        if entry.is_msi:
            return True, ""
        return False, "no UninstallString"
    exe = _extract_exe_from_command(cmd)
    if not exe:
        return False, "unparseable command"
    base = os.path.basename(exe).lower()
    if base in ("msiexec.exe", "msiexec"):
        return True, ""
    expanded = os.path.expandvars(exe)
    if os.path.isabs(expanded):
        if os.path.isfile(expanded):
            return True, ""
        return False, f"missing: {expanded}"
    import shutil
    if shutil.which(expanded):
        return True, ""
    return False, f"not found: {expanded}"


def _read_uninstall_entry(hive_name, hive_h, arch_tag, parent_path, sub_name) -> Optional[UninstallEntry]:
    key_path = parent_path + "\\" + sub_name
    try:
        with winreg.OpenKey(hive_h, key_path, 0, winreg.KEY_READ) as sk:
            def gv(name, default=""):
                try:
                    v, _ = winreg.QueryValueEx(sk, name)
                    return v
                except OSError:
                    return default

            def gi(name, default=0):
                try:
                    v, _ = winreg.QueryValueEx(sk, name)
                    return int(v)
                except (OSError, ValueError, TypeError):
                    return default

            entry = UninstallEntry(
                hive_name=hive_name,
                hive_handle=hive_h,
                arch_tag=arch_tag,
                parent_path=parent_path,
                sub_name=sub_name,
                key_path=key_path,
                display_name=str(gv("DisplayName", "")),
                display_version=str(gv("DisplayVersion", "")),
                publisher=str(gv("Publisher", "")),
                install_date=str(gv("InstallDate", "")),
                install_location=str(gv("InstallLocation", "")),
                uninstall_string=str(gv("UninstallString", "")),
                quiet_uninstall_string=str(gv("QuietUninstallString", "")),
                display_icon=str(gv("DisplayIcon", "")),
                estimated_size_kb=gi("EstimatedSize", 0),
                system_component=bool(gi("SystemComponent", 0)),
                parent_key_name=str(gv("ParentKeyName", "")),
                is_msi=bool(gi("WindowsInstaller", 0)),
                is_valid=False,
                invalid_reason="",
            )
            valid, reason = _check_uninstaller_validity(entry)
            entry.is_valid = valid
            entry.invalid_reason = reason
            return entry
    except OSError:
        return None


def enumerate_uninstall_entries() -> List[UninstallEntry]:
    entries: List[UninstallEntry] = []
    for hive_name, hive_h, parent_path, arch_tag in UNINSTALL_LOCATIONS:
        try:
            with winreg.OpenKey(hive_h, parent_path, 0, winreg.KEY_READ) as k:
                n_sub, _, _ = winreg.QueryInfoKey(k)
                names = []
                for i in range(n_sub):
                    try:
                        names.append(winreg.EnumKey(k, i))
                    except OSError:
                        break
        except OSError:
            continue
        for name in names:
            e = _read_uninstall_entry(hive_name, hive_h, arch_tag, parent_path, name)
            if e is not None:
                entries.append(e)
    return entries


class UninstallEnumWorker(QThread):
    entry = pyqtSignal(object)
    finished_all = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        count = 0
        for hive_name, hive_h, parent_path, arch_tag in UNINSTALL_LOCATIONS:
            if self._stop:
                break
            try:
                with winreg.OpenKey(hive_h, parent_path, 0, winreg.KEY_READ) as k:
                    n_sub, _, _ = winreg.QueryInfoKey(k)
                    names = []
                    for i in range(n_sub):
                        try:
                            names.append(winreg.EnumKey(k, i))
                        except OSError:
                            break
            except OSError:
                continue
            for name in names:
                if self._stop:
                    break
                e = _read_uninstall_entry(hive_name, hive_h, arch_tag, parent_path, name)
                if e is not None:
                    self.entry.emit(e)
                    count += 1
        self.finished_all.emit(count)


class UninstallRunWorker(QThread):
    """Sequentially launch each uninstaller via shell and wait."""
    starting = pyqtSignal(object)
    finished_one = pyqtSignal(object, int)
    finished_all = pyqtSignal(int, int)

    def __init__(self, entries: List["UninstallEntry"], use_quiet: bool, parent=None):
        super().__init__(parent)
        self._entries = list(entries)
        self._use_quiet = use_quiet
        self._stop = False
        self._proc: Optional[subprocess.Popen] = None

    def request_stop(self):
        self._stop = True
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self):
        ok = fail = 0
        for e in self._entries:
            if self._stop:
                break
            cmd = (silent_command(e)[0] if self._use_quiet
                   else e.uninstall_string or e.quiet_uninstall_string)
            if not cmd:
                fail += 1
                continue
            self.starting.emit(e)
            try:
                self._proc = subprocess.Popen(
                    cmd, shell=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError:
                rc = -1
            else:
                rc = self._wait_tree(self._proc)
            self._proc = None
            self.finished_one.emit(e, rc)
            if rc == 0:
                ok += 1
            else:
                fail += 1
        self.finished_all.emit(ok, fail)

    def _wait_tree(self, proc: subprocess.Popen) -> int:
        # Inno and NSIS uninstallers relaunch a copy from %TEMP% and exit at
        # once; the job holds that copy, so waiting on it waits for the real
        # uninstall. cmd.exe takes far longer to spawn its child than the
        # assignment below takes, so the child lands in the job.
        job = win32job.CreateJobObject(None, "")
        h = win32api.OpenProcess(
            win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, proc.pid)
        try:
            win32job.AssignProcessToJobObject(job, h)
        except pywintypes.error:
            if proc.poll() is None:
                raise
            return proc.returncode
        finally:
            h.Close()
        rc = proc.wait()
        while not self._stop and win32job.QueryInformationJobObject(
                job, win32job.JobObjectBasicAccountingInformation)["ActiveProcesses"]:
            time.sleep(0.25)
        job.Close()
        return rc


class UninstallRemoveWorker(QThread):
    progress = pyqtSignal(int, int, str)
    item_error = pyqtSignal(str, str)
    backup_done = pyqtSignal(str, int, int)
    finished_all = pyqtSignal(int, int)

    def __init__(self, entries: List["UninstallEntry"], do_backup: bool, parent=None):
        super().__init__(parent)
        self._entries = list(entries)
        self._do_backup = do_backup
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        if self._do_backup:
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup_dir = str(REG_BACKUP_DIR / f"uninstall_{ts}")
            os.makedirs(backup_dir, exist_ok=True)
            bok = bfail = 0
            for i, e in enumerate(self._entries):
                if self._stop:
                    break
                fname = _safe_filename(f"{e.hive_name}__{e.arch_tag}__{e.sub_name}") + ".reg"
                out = os.path.join(backup_dir, fname)
                ok, msg = reg_export(e.hive_name, e.key_path, out)
                if ok:
                    bok += 1
                else:
                    bfail += 1
                    self.item_error.emit(f"backup {e.hive_name}\\{e.key_path}", msg)
                self.progress.emit(i + 1, len(self._entries), f"Backing up: {e.display}")
            self.backup_done.emit(backup_dir, bok, bfail)

        ok = fail = 0
        total = len(self._entries)
        for i, e in enumerate(self._entries):
            if self._stop:
                break
            try:
                reg_delete_recursive(e.hive_handle, e.key_path)
                ok += 1
            except OSError as ex:
                fail += 1
                self.item_error.emit(f"{e.hive_name}\\{e.key_path}", str(ex))
            except Exception as ex:
                fail += 1
                self.item_error.emit(f"{e.hive_name}\\{e.key_path}", str(ex))
            self.progress.emit(i + 1, total, f"Removing entry: {e.display}")
        self.finished_all.emit(ok, fail)


# =======================================================================
# UI
# =======================================================================

COL_NAME, COL_SIZE, COL_MOD, COL_PATH = 0, 1, 2, 3


class CheckRangeTreeWidget(QTreeWidget):
    """QTreeWidget that supports Shift+click to set a *range* of checkable
    items to the same state as the last clicked item (the 'anchor').

    Plain click on a checkable item updates the anchor; the click then runs
    through Qt's default handling (so clicking the checkbox still toggles).
    Shift+click extends from the anchor to the clicked row and applies the
    anchor's check state to every checkable item between them in tree-display
    order. setCheckState fires itemChanged for each — the page's existing
    summary/background handlers update normally.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._check_anchor = None
        self._check_column = 0

    def set_check_column(self, col: int):
        self._check_column = col

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            item = self.itemAt(ev.pos())
            if (item is not None and (ev.modifiers() & Qt.ShiftModifier)
                    and self._check_anchor is not None):
                anchor_state = self._check_anchor.checkState(self._check_column)
                if anchor_state == Qt.PartiallyChecked:
                    anchor_state = Qt.Checked
                for it in self._items_in_range(self._check_anchor, item):
                    if it.flags() & Qt.ItemIsUserCheckable:
                        if it.checkState(self._check_column) != anchor_state:
                            it.setCheckState(self._check_column, anchor_state)
                if item.flags() & Qt.ItemIsUserCheckable:
                    self._check_anchor = item
                ev.accept()
                return
            if item is not None and (item.flags() & Qt.ItemIsUserCheckable):
                self._check_anchor = item
        super().mousePressEvent(ev)

    def _items_in_range(self, a, b):
        order = []

        def walk(item):
            order.append(item)
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self.topLevelItemCount()):
            walk(self.topLevelItem(i))
        try:
            ai = order.index(a)
            bi = order.index(b)
        except ValueError:
            return []
        if ai > bi:
            ai, bi = bi, ai
        return order[ai:bi + 1]


def _apply_checked_bg(item, tree: QTreeWidget, checked: bool, check_col: int = 0):
    """Paint the row's background yellow when checked, clear otherwise."""
    if checked:
        brush = QBrush(QColor(CHECKED_ROW_BG))
        for c in range(tree.columnCount()):
            item.setBackground(c, brush)
    else:
        for c in range(tree.columnCount()):
            item.setData(c, Qt.BackgroundRole, None)


class FilesPage(QWidget):
    """Tab 1: file-based cleanup (Windows Temp / Recycle Bin / Browser / Recent / Custom)."""

    def __init__(self, config_ref: dict, save_config_cb: Callable[[], None], parent=None):
        super().__init__(parent)
        self._config = config_ref
        self._save_config = save_config_cb
        self._cat_items: dict = {}
        self._cat_totals: dict = {}
        self._cat_populated: dict = {}
        self._scan: Optional[ScanController] = None
        self._scan_t0 = 0.0
        self._clean_worker: Optional[CleanWorker] = None
        self._clean_errors: list = []
        self._recycle_bytes = 0
        self._recycle_count = 0
        saved = self._config.get("files_unchecked", {})
        self._unchecked_cats = set(saved.get("cats", []))
        self._unchecked_files = {k: set(v) for k, v in saved.get("files", {}).items()}
        # Checking a populated category fires itemChanged per child; coalesce the summary.
        self._summary_timer = QTimer(self, singleShot=True, interval=0,
                                     timeout=self._refresh_summary)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self._build_toolbar(lay)
        self._build_tree(lay)
        self._build_status(lay)
        self._reset_tree_to_categories(initial=True)

    # ---- config helpers ----
    def custom_paths(self) -> List[str]:
        return list(self._config.get("custom_paths", []))

    # ---- toolbar ----
    def _build_toolbar(self, parent_layout: QVBoxLayout):
        row = QHBoxLayout()
        self.btn_scan = QPushButton("Scan")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_clean = QPushButton("Clean checked")
        self.btn_clean.setEnabled(False)
        self.btn_check_all = QPushButton("Check all")
        self.btn_uncheck_all = QPushButton("Uncheck all")
        self.btn_add_custom = QPushButton("Add custom path...")
        self.btn_mgr_custom = QPushButton("Manage custom paths...")
        for w in (self.btn_scan, self.btn_stop, self.btn_clean):
            row.addWidget(w)
        row.addSpacing(8)
        for w in (self.btn_check_all, self.btn_uncheck_all):
            row.addWidget(w)
        row.addSpacing(8)
        for w in (self.btn_add_custom, self.btn_mgr_custom):
            row.addWidget(w)
        row.addStretch(1)
        parent_layout.addLayout(row)
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_stop.clicked.connect(self.stop_scan)
        self.btn_clean.clicked.connect(self.start_clean)
        self.btn_check_all.clicked.connect(lambda: self._bulk_check(Qt.Checked))
        self.btn_uncheck_all.clicked.connect(lambda: self._bulk_check(Qt.Unchecked))
        self.btn_add_custom.clicked.connect(self.add_custom_path)
        self.btn_mgr_custom.clicked.connect(self.manage_custom_paths)

    # ---- tree ----
    def _build_tree(self, parent_layout: QVBoxLayout):
        self.tree = CheckRangeTreeWidget()
        self.tree.set_check_column(COL_NAME)
        self.tree.setHeaderLabels(["Item", "Size", "Modified", "Path"])
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setSortingEnabled(False)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_SIZE, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_MOD, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_PATH, QHeaderView.Stretch)
        self.tree.setColumnWidth(COL_NAME, 320)
        self.tree.setColumnWidth(COL_SIZE, 160)
        self.tree.setColumnWidth(COL_MOD, 140)
        self.tree.setStyleSheet(f"QTreeWidget::item {{ height: {ROW_HEIGHT_PX}px; }}")
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        parent_layout.addWidget(self.tree, 1)

    # ---- status ----
    def _build_status(self, parent_layout: QVBoxLayout):
        row = QHBoxLayout()
        self.lbl_status = QLabel("Idle")
        self.lbl_summary = QLabel("")
        row.addWidget(self.lbl_status, 1)
        row.addWidget(self.lbl_summary)
        parent_layout.addLayout(row)

    def _reset_tree_to_categories(self, initial=False):
        self.tree.blockSignals(True)
        self.tree.clear()
        self._cat_items.clear()
        self._cat_totals.clear()
        self._cat_populated.clear()
        self._recycle_bytes = 0
        self._recycle_count = 0
        for cat in CATEGORIES:
            placeholder = "not scanned yet" if initial else "scanning..."
            item = QTreeWidgetItem([cat.name, placeholder, "", cat.description])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            if cat.key in self._unchecked_cats:
                state = Qt.Unchecked
            elif self._unchecked_files.get(cat.key):
                state = Qt.PartiallyChecked
            else:
                state = Qt.Checked
            item.setCheckState(COL_NAME, state)
            item.setData(COL_NAME, Qt.UserRole, ("cat", cat.key))
            item.setChildIndicatorPolicy(QTreeWidgetItem.DontShowIndicator)
            self.tree.addTopLevelItem(item)
            _apply_checked_bg(item, self.tree, state == Qt.Checked, COL_NAME)
            self._cat_items[cat.key] = item
            self._cat_totals[cat.key] = (0, 0)
            self._cat_populated[cat.key] = False
        self.tree.blockSignals(False)
        self._refresh_summary()

    # ---- scan ----
    def start_scan(self):
        if self._scan is not None:
            self._scan.stop()
            self._scan = None
        self._save_checks()
        self._reset_tree_to_categories(initial=False)
        self.btn_clean.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._scan_t0 = time.monotonic()
        self.lbl_status.setText("Scanning (parallel)...")
        self._scan = ScanController(CATEGORIES, self.custom_paths(), parent=self)
        self._scan.files_batch.connect(self._on_files_batch)
        self._scan.recycle_info.connect(self._on_recycle_info)
        self._scan.category_started.connect(self._on_cat_start)
        self._scan.category_done.connect(self._on_cat_done)
        self._scan.finished_all.connect(self._on_scan_finished)
        self._scan.start()

    def stop_scan(self):
        if self._scan is not None:
            self._scan.stop()
            self.lbl_status.setText("Stopping scan...")

    def _on_cat_start(self, key):
        parent = self._cat_items.get(key)
        if parent:
            parent.setText(COL_SIZE, "scanning...")

    def _on_files_batch(self, key, batch_count, batch_bytes):
        parent = self._cat_items.get(key)
        if parent is None:
            return
        c, b = self._cat_totals[key]
        c += batch_count
        b += batch_bytes
        self._cat_totals[key] = (c, b)
        parent.setText(COL_SIZE, f"{c:,} files - {human_size(b)}")
        parent.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        self._refresh_summary()

    def _on_recycle_info(self, key, size, num):
        parent = self._cat_items.get(key)
        if parent is None:
            return
        self._recycle_bytes = size
        self._recycle_count = num
        self.tree.blockSignals(True)
        parent.setText(COL_SIZE, f"{num:,} items - {human_size(size)}")
        parent.setData(COL_NAME, Qt.UserRole, ("recycle", size, num))
        if num == 0:
            parent.setCheckState(COL_NAME, Qt.Unchecked)
            parent.setDisabled(True)
            parent.setText(COL_PATH, "Recycle Bin is empty")
        self._cat_totals[key] = (num, size)
        self.tree.blockSignals(False)
        self._refresh_summary()

    def _on_cat_done(self, key):
        parent = self._cat_items.get(key)
        if parent is None:
            return
        # sender() guards against a stopped scan's late signals pruning the new scan.
        scan = self.sender()
        ex = self._unchecked_files.get(key)
        if ex and scan is self._scan and not scan._stop.is_set():
            ex &= {p for p, _, _ in scan.files_by_cat[key]}
            if not ex and parent.checkState(COL_NAME) == Qt.PartiallyChecked:
                parent.setCheckState(COL_NAME, Qt.Checked)
        c, b = self._cat_totals.get(key, (0, 0))
        if c == 0 and not parent.isDisabled():
            self.tree.blockSignals(True)
            parent.setText(COL_SIZE, "0 B")
            parent.setText(COL_PATH, "nothing found")
            parent.setCheckState(COL_NAME, Qt.Unchecked)
            parent.setDisabled(True)
            self.tree.blockSignals(False)

    def _on_scan_finished(self):
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_clean.setEnabled(True)
        dt = time.monotonic() - self._scan_t0
        total = sum(c for c, _ in self._cat_totals.values())
        bytes_ = sum(b for _, b in self._cat_totals.values())
        self.lbl_status.setText(
            f"Scan complete in {dt:0.1f}s - {total:,} items, {human_size(bytes_)}. Expand a row to see files."
        )
        self._refresh_summary()

    # ---- lazy expand ----
    def _on_item_expanded(self, item):
        if item.parent() is not None:
            return
        data = item.data(COL_NAME, Qt.UserRole)
        if not data or data[0] != "cat":
            return
        key = data[1]
        if self._cat_populated.get(key):
            return
        if self._scan is None:
            return
        files = self._scan.files_by_cat.get(key, [])
        if not files:
            return
        self._populate_children(item, key, files)
        self._cat_populated[key] = True

    def _populate_children(self, parent_item, key, files):
        parent_checked = parent_item.checkState(COL_NAME) != Qt.Unchecked
        ex = self._unchecked_files.get(key, set())
        cap = MAX_CHILDREN_SHOWN
        self.tree.setUpdatesEnabled(False)
        self.tree.blockSignals(True)
        try:
            children = []
            for idx, (path, size, mtime) in enumerate(files[:cap]):
                name = os.path.basename(path) or path
                mod = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)) if mtime else ""
                ch = QTreeWidgetItem([name, human_size(size), mod, path])
                ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
                checked = parent_checked and path not in ex
                ch.setCheckState(COL_NAME, Qt.Checked if checked else Qt.Unchecked)
                ch.setData(COL_NAME, Qt.UserRole, ("file", key, idx))
                children.append(ch)
            parent_item.addChildren(children)
            for ch in children:
                if ch.checkState(COL_NAME) == Qt.Checked:
                    _apply_checked_bg(ch, self.tree, True, COL_NAME)
            _apply_checked_bg(parent_item, self.tree,
                              parent_item.checkState(COL_NAME) == Qt.Checked, COL_NAME)
            if len(files) > cap:
                rest = len(files) - cap
                rest_bytes = sum(s for _, s, _ in files[cap:])
                stub = QTreeWidgetItem([
                    f"... and {rest:,} more (included if category is checked)",
                    human_size(rest_bytes), "", ""
                ])
                stub.setFlags(Qt.ItemIsEnabled)
                parent_item.addChild(stub)
        finally:
            self.tree.blockSignals(False)
            self.tree.setUpdatesEnabled(True)

    # ---- selection ----
    def _on_item_changed(self, item, col):
        if col != COL_NAME:
            return
        state = item.checkState(COL_NAME)
        _apply_checked_bg(item, self.tree, state == Qt.Checked, COL_NAME)
        if item.parent() is None:
            self._remember_cat(next(k for k, it in self._cat_items.items() if it is item), state)
        else:
            data = item.data(COL_NAME, Qt.UserRole)
            if data and data[0] == "file":
                _, key, idx = data
                path = self._scan.files_by_cat[key][idx][0]
                if state == Qt.Checked:
                    self._unchecked_files.get(key, set()).discard(path)
                else:
                    self._unchecked_files.setdefault(key, set()).add(path)
        if item.parent() is None and state != Qt.PartiallyChecked:
            self.tree.blockSignals(True)
            for i in range(item.childCount()):
                ch = item.child(i)
                if ch.flags() & Qt.ItemIsUserCheckable:
                    ch.setCheckState(COL_NAME, state)
                    _apply_checked_bg(ch, self.tree, state == Qt.Checked, COL_NAME)
            self.tree.blockSignals(False)
        self._summary_timer.start()

    def _remember_cat(self, key, state):
        if state == Qt.Unchecked:
            self._unchecked_cats.add(key)
            return
        self._unchecked_cats.discard(key)
        if state == Qt.Checked:
            self._unchecked_files.pop(key, None)

    def _save_checks(self):
        self._config["files_unchecked"] = {
            "cats": sorted(self._unchecked_cats),
            "files": {k: sorted(v) for k, v in self._unchecked_files.items() if v},
        }
        self._save_config()

    def _bulk_check(self, state):
        self.tree.blockSignals(True)
        is_checked = state == Qt.Checked
        for key, parent in self._cat_items.items():
            if parent.isDisabled():
                continue
            self._remember_cat(key, state)
            parent.setCheckState(COL_NAME, state)
            _apply_checked_bg(parent, self.tree, is_checked, COL_NAME)
            for i in range(parent.childCount()):
                ch = parent.child(i)
                if ch.flags() & Qt.ItemIsUserCheckable:
                    ch.setCheckState(COL_NAME, state)
                    _apply_checked_bg(ch, self.tree, is_checked, COL_NAME)
        self.tree.blockSignals(False)
        self._refresh_summary()

    def _refresh_summary(self):
        checked_files = 0
        checked_bytes = 0
        empty_recycle = False
        for key, parent in self._cat_items.items():
            if parent.isDisabled():
                continue
            if key == "recycle":
                if parent.checkState(COL_NAME) == Qt.Checked:
                    empty_recycle = True
                    checked_files += self._recycle_count
                    checked_bytes += self._recycle_bytes
                continue
            state = parent.checkState(COL_NAME)
            if state == Qt.Unchecked:
                continue
            c_total, b_total = self._cat_totals.get(key, (0, 0))
            ex = self._unchecked_files.get(key)
            if ex and self._scan:
                ex_sizes = [s for p, s, _ in self._scan.files_by_cat[key] if p in ex]
                c_total -= len(ex_sizes)
                b_total -= sum(ex_sizes)
            checked_files += c_total
            checked_bytes += b_total
        suffix = "  -  will empty Recycle Bin" if empty_recycle else ""
        self.lbl_summary.setText(
            f"Checked: {checked_files:,} items, {human_size(checked_bytes)}{suffix}"
        )

    # ---- clean ----
    def _collect_clean_targets(self):
        paths = []
        empty_recycle = False
        for key, parent in self._cat_items.items():
            if parent.isDisabled():
                continue
            if key == "recycle":
                if parent.checkState(COL_NAME) == Qt.Checked:
                    empty_recycle = True
                continue
            state = parent.checkState(COL_NAME)
            if state == Qt.Unchecked:
                continue
            files = self._scan.files_by_cat.get(key, []) if self._scan else []
            ex = self._unchecked_files.get(key, set())
            paths.extend((p, s) for p, s, _ in files if p not in ex)
        return paths, empty_recycle

    def start_clean(self):
        paths, empty_recycle = self._collect_clean_targets()
        if not paths and not empty_recycle:
            QMessageBox.information(self, "Nothing to do", "No items are checked.")
            return
        msg_parts = []
        if paths:
            msg_parts.append(f"Send {len(paths):,} item(s) to the Recycle Bin")
        if empty_recycle:
            msg_parts.append(
                f"permanently empty the Recycle Bin "
                f"({self._recycle_count:,} items, ~{human_size(self._recycle_bytes)})"
            )
        msg = " and ".join(msg_parts) + "?"
        if QMessageBox.question(self, "Confirm clean", msg,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.btn_clean.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.lbl_status.setText("Cleaning...")
        self._clean_errors = []
        self._clean_worker = CleanWorker(paths, empty_recycle, self._recycle_bytes)
        self._clean_worker.progress.connect(self._on_clean_progress)
        self._clean_worker.item_error.connect(self._on_clean_error)
        self._clean_worker.finished_all.connect(self._on_clean_finished)
        self._clean_worker.start()

    def _on_clean_progress(self, done, total):
        self.lbl_status.setText(f"Cleaning... {done:,} / {total:,}")

    def _on_clean_error(self, path, err):
        self._clean_errors.append((path, err))

    def _on_clean_finished(self, ok, fail, freed):
        self.btn_scan.setEnabled(True)
        self.btn_clean.setEnabled(True)
        self.lbl_status.setText(
            f"Done. Cleaned {ok:,} item(s), {fail:,} failure(s), freed ~{human_size(freed)}."
        )
        if self._clean_errors:
            shown = self._clean_errors[:10]
            preview = "\n".join(f"{p}: {e}" for p, e in shown)
            more = f"\n...and {len(self._clean_errors) - 10} more" if len(self._clean_errors) > 10 else ""
            QMessageBox.warning(self, "Some items could not be deleted", preview + more)
        self.start_scan()

    # ---- custom paths ----
    def add_custom_path(self):
        choices = ["Folder...", "File..."]
        kind, ok = QInputDialog.getItem(self, "Add custom path", "Kind:", choices, 0, False)
        if not ok:
            return
        if kind == "Folder...":
            p = QFileDialog.getExistingDirectory(self, "Pick folder to clean")
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Pick file to clean")
        if not p:
            return
        paths = self._config.setdefault("custom_paths", [])
        if p not in paths:
            paths.append(p)
            self._save_config()
            self.lbl_status.setText(f"Added custom path: {p}")

    def manage_custom_paths(self):
        dlg = CustomPathsDialog(self.custom_paths(), self)
        if dlg.exec_() == QDialog.Accepted:
            self._config["custom_paths"] = dlg.paths()
            self._save_config()

    def shutdown(self):
        self._save_checks()
        if self._scan is not None:
            self._scan.stop()
        if self._clean_worker and self._clean_worker.isRunning():
            self._clean_worker.request_stop()
            self._clean_worker.wait(2000)


# =======================================================================
# Registry tab
# =======================================================================

REG_COL_KEY, REG_COL_SUB, REG_COL_VAL, REG_COL_MATCH = 0, 1, 2, 3


class RegistryPage(QWidget):
    """Tab 2: registry cleanup. Search by substring across selected hives.
    Matches are shown in a regedit-style tree so you can see the exact
    keys (and any empty parents) that would be removed.

    Visual cues:
      - Bold + unchecked checkbox = matched key. Nothing is deleted until
        the user explicitly checks the box (use 'Check all' to opt in to
        every match at once).
      - Italic + unchecked checkbox + '(empty after delete)' suffix
        = parent that would be empty once matched children are gone;
          opt-in by checking the box if you want it removed too.
      - No checkbox = navigational node, retained as context.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[RegistrySearchWorker] = None
        self._del_worker: Optional[RegistryDeleteWorker] = None
        self._backup_worker: Optional[RegistryBackupWorker] = None
        self._backup_errors: list = []
        self._search_t0 = 0.0
        self._rows: list = []                          # matched keys only
        self._empty_parents_by_hive: dict = {}
        self._hive_items: dict = {}                    # hive_name -> root QTreeWidgetItem
        self._path_nodes: dict = {}                    # (hive_name, sub_path) -> QTreeWidgetItem

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        self._build_search_row(v)
        self._build_tree(v)
        self._build_action_row(v)
        self._build_status(v)

    def _build_search_row(self, lay):
        row = QHBoxLayout()
        row.addWidget(QLabel("Search:"))
        self.input = QLineEdit()
        row.addWidget(self.input, 1)
        self.cmb_combine = QComboBox()
        self.cmb_combine.addItems(["AND NOT", "OR"])
        row.addWidget(self.cmb_combine)
        self.input2 = QLineEdit()
        row.addWidget(self.input2, 1)
        self.cb_hives = {}
        for name, _ in HIVES:
            cb = QCheckBox(name)
            cb.setChecked(True)
            row.addWidget(cb)
            self.cb_hives[name] = cb
        self.cb_search_values = QCheckBox("Match values")
        self.cb_search_values.setChecked(True)
        row.addWidget(self.cb_search_values)
        self.btn_search = QPushButton("Search")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        row.addWidget(self.btn_search)
        row.addWidget(self.btn_stop)
        lay.addLayout(row)
        self.input.returnPressed.connect(self.start_search)
        self.input2.returnPressed.connect(self.start_search)
        self.btn_search.clicked.connect(self.start_search)
        self.btn_stop.clicked.connect(self.stop_search)

    def _build_tree(self, lay):
        self.tree = CheckRangeTreeWidget()
        self.tree.set_check_column(REG_COL_KEY)
        self.tree.setHeaderLabels(["Key", "Subkeys", "Values", "Matched in"])
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setSortingEnabled(False)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(REG_COL_KEY, QHeaderView.Stretch)
        hdr.setSectionResizeMode(REG_COL_SUB, QHeaderView.Interactive)
        hdr.setSectionResizeMode(REG_COL_VAL, QHeaderView.Interactive)
        hdr.setSectionResizeMode(REG_COL_MATCH, QHeaderView.Interactive)
        self.tree.setColumnWidth(REG_COL_SUB, 80)
        self.tree.setColumnWidth(REG_COL_VAL, 80)
        self.tree.setColumnWidth(REG_COL_MATCH, 320)
        self.tree.setStyleSheet(f"QTreeWidget::item {{ height: {ROW_HEIGHT_PX}px; }}")
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        lay.addWidget(self.tree, 1)

    def _build_action_row(self, lay):
        row = QHBoxLayout()
        self.btn_check_all = QPushButton("Check all")
        self.btn_uncheck_all = QPushButton("Uncheck all")
        self.btn_open_regedit = QPushButton("Open in regedit")
        self.btn_open_regedit.setEnabled(False)
        self.btn_backup = QPushButton("Backup checked")
        self.btn_backup.setEnabled(False)
        self.btn_delete = QPushButton("Delete checked")
        self.btn_delete.setEnabled(False)
        row.addWidget(self.btn_check_all)
        row.addWidget(self.btn_uncheck_all)
        row.addSpacing(8)
        row.addWidget(self.btn_open_regedit)
        row.addStretch(1)
        row.addWidget(self.btn_backup)
        row.addWidget(self.btn_delete)
        lay.addLayout(row)
        self.btn_check_all.clicked.connect(lambda: self._bulk_check(Qt.Checked))
        self.btn_uncheck_all.clicked.connect(lambda: self._bulk_check(Qt.Unchecked))
        self.btn_open_regedit.clicked.connect(self.open_selected_in_regedit)
        self.btn_backup.clicked.connect(self.backup_checked)
        self.btn_delete.clicked.connect(self.delete_checked)

    def _build_status(self, lay):
        row = QHBoxLayout()
        self.lbl_status = QLabel("Idle")
        self.lbl_summary = QLabel("")
        row.addWidget(self.lbl_status, 1)
        row.addWidget(self.lbl_summary)
        lay.addLayout(row)

    # ---- search ----
    def start_search(self):
        needle = self.input.text().strip()
        if not needle:
            QMessageBox.information(self, "Empty search",
                                    "Enter a substring to match against registry key paths.")
            return
        needle2 = self.input2.text().strip()
        mode = self.cmb_combine.currentText()
        hives = [n for n, _ in HIVES if self.cb_hives[n].isChecked()]
        if not hives:
            QMessageBox.information(self, "No hives", "Select at least one hive.")
            return
        if "HKCR" in hives and len(needle) < 3:
            if QMessageBox.question(
                self, "Slow search",
                "Short substrings against HKCR/HKLM will produce many matches and may take a while. Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes:
                return
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(2000)

        self.tree.blockSignals(True)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        self.tree.blockSignals(False)
        self._rows.clear()
        self._hive_items.clear()
        self._path_nodes.clear()
        self._empty_parents_by_hive.clear()
        self.btn_delete.setEnabled(False)
        self.btn_backup.setEnabled(False)
        self.btn_search.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._search_t0 = time.monotonic()
        if needle2:
            self.lbl_status.setText(
                f"Searching for '{needle}' {mode} '{needle2}'..."
            )
        else:
            self.lbl_status.setText(f"Searching for '{needle}'...")
        self.lbl_summary.setText("")

        self._worker = RegistrySearchWorker(
            needle, hives,
            search_values=self.cb_search_values.isChecked(),
            parent=self,
            needle2=needle2,
            mode=mode,
        )
        self._worker.match.connect(self._on_match)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_all.connect(self._on_search_finished)
        self._worker.start()

    def stop_search(self):
        if self._worker is not None:
            self._worker.request_stop()
            self.lbl_status.setText("Stopping search...")

    # ---- tree building ----
    def _ensure_hive_root(self, hive_name: str) -> QTreeWidgetItem:
        item = self._hive_items.get(hive_name)
        if item is not None:
            return item
        item = QTreeWidgetItem([hive_name, "", "", ""])
        item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
        item.setData(REG_COL_KEY, Qt.UserRole, ("reg", hive_name, ""))
        font = item.font(REG_COL_KEY)
        font.setBold(True)
        item.setFont(REG_COL_KEY, font)
        self.tree.blockSignals(True)
        self.tree.addTopLevelItem(item)
        item.setExpanded(True)
        self.tree.blockSignals(False)
        self._hive_items[hive_name] = item
        self._path_nodes[(hive_name, "")] = item
        return item

    def _make_intermediate(self, hive_name: str, sub_path: str, name: str) -> QTreeWidgetItem:
        hive_h = HIVES_BY_NAME[hive_name]
        info = reg_key_info(hive_h, sub_path)
        ns, nv = info if info else (0, 0)
        node = QTreeWidgetItem([name, str(ns), str(nv), ""])
        node.setFlags(node.flags() & ~Qt.ItemIsUserCheckable)
        node.setData(REG_COL_KEY, Qt.UserRole, ("reg", hive_name, sub_path))
        return node

    def _on_match(self, hive_name: str, path: str, n_sub: int, n_val: int,
                  key_matched: bool, value_matches: list):
        hive_item = self._ensure_hive_root(hive_name)
        parts = path.split("\\")
        parent_item = hive_item
        leaf_node = None
        self.tree.blockSignals(True)
        try:
            for i in range(1, len(parts) + 1):
                sub = "\\".join(parts[:i])
                key = (hive_name, sub)
                existing = self._path_nodes.get(key)
                if existing is not None:
                    parent_item = existing
                    continue
                name = parts[i - 1]
                if i == len(parts):
                    node = QTreeWidgetItem([name, str(n_sub), str(n_val), ""])
                    node.setFlags(node.flags() | Qt.ItemIsUserCheckable)
                    parent_item.addChild(node)
                    # Matches start UNCHECKED - user opts in explicitly.
                    node.setCheckState(REG_COL_KEY, Qt.Unchecked)
                    font = node.font(REG_COL_KEY)
                    font.setBold(True)
                    node.setFont(REG_COL_KEY, font)
                    node.setData(REG_COL_KEY, Qt.UserRole, ("reg", hive_name, sub))
                    _apply_checked_bg(node, self.tree, False, REG_COL_KEY)
                    leaf_node = node
                else:
                    node = self._make_intermediate(hive_name, sub, name)
                    parent_item.addChild(node)
                self._path_nodes[key] = node
                parent_item = node
            if leaf_node is not None:
                self._annotate_match_leaf(leaf_node, key_matched, value_matches)
                p = leaf_node.parent()
                while p is not None:
                    p.setExpanded(True)
                    p = p.parent()
        finally:
            self.tree.blockSignals(False)
        leaf = self._path_nodes.get((hive_name, path))
        self._rows.append({
            "hive": hive_name, "path": path, "n_sub": n_sub, "n_val": n_val,
            "item": leaf, "key_matched": key_matched,
            "value_matches": list(value_matches),
        })

    def _annotate_match_leaf(self, leaf, key_matched: bool, value_matches: list):
        """Fill the 'Matched in' column + tooltip describing why this key
        appears in the result set."""
        labels = []
        if key_matched:
            labels.append("key")
        for vm in value_matches:
            nm, data, name_hit, data_hit = vm
            disp = nm or "(default)"
            if name_hit and data_hit:
                labels.append(f"value name+data: {disp}")
            elif name_hit:
                labels.append(f"value name: {disp}")
            else:
                short_data = data if len(data) <= 60 else data[:57] + "..."
                labels.append(f"value data [{disp}] = {short_data}")
        primary = labels[0] if labels else ""
        if len(labels) > 1:
            leaf.setText(REG_COL_MATCH, f"{primary}  (+{len(labels) - 1} more)")
        else:
            leaf.setText(REG_COL_MATCH, primary)
        # Tooltip lists every reason in full.
        tip_lines = []
        if key_matched:
            tip_lines.append("matched in key path")
        for vm in value_matches:
            nm, data, name_hit, data_hit = vm
            disp = nm or "(default)"
            kind = []
            if name_hit:
                kind.append("name")
            if data_hit:
                kind.append("data")
            tip_lines.append(f"{'/'.join(kind)} match - {disp} = {data}")
        leaf.setToolTip(REG_COL_KEY, "\n".join(tip_lines))
        leaf.setToolTip(REG_COL_MATCH, "\n".join(tip_lines))

    def _on_progress(self, location: str, matches: int):
        self.lbl_status.setText(f"Searching... at {location}  ({matches:,} matches)")

    def _on_search_finished(self, total: int):
        dt = time.monotonic() - self._search_t0
        self.btn_search.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_delete.setEnabled(total > 0)
        self.btn_backup.setEnabled(total > 0)
        by_hive: dict = {}
        for r in self._rows:
            by_hive.setdefault(r["hive"], []).append(r["path"])
        self._empty_parents_by_hive = {}
        for hive_name, paths in by_hive.items():
            hive_h = HIVES_BY_NAME.get(hive_name)
            if hive_h is None:
                continue
            self._empty_parents_by_hive[hive_name] = predict_empty_parents(hive_h, paths)

        self.tree.blockSignals(True)
        empty_count = 0
        for hive_name, paths in self._empty_parents_by_hive.items():
            for p in paths:
                node = self._path_nodes.get((hive_name, p))
                if node is None:
                    continue
                node.setFlags(node.flags() | Qt.ItemIsUserCheckable)
                node.setCheckState(REG_COL_KEY, Qt.Unchecked)
                font = node.font(REG_COL_KEY)
                font.setItalic(True)
                node.setFont(REG_COL_KEY, font)
                cur = node.text(REG_COL_KEY)
                if "(empty after delete)" not in cur:
                    node.setText(REG_COL_KEY, cur + "  (empty after delete)")
                empty_count += 1
        self.tree.blockSignals(False)
        self.lbl_status.setText(
            f"Search complete in {dt:0.1f}s - {total:,} match(es), "
            f"{empty_count:,} parent(s) would be empty."
        )
        self._refresh_summary()

    # ---- tree iteration ----
    def _iter_tree_items(self):
        def walk(item):
            yield item
            for i in range(item.childCount()):
                yield from walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            yield from walk(self.tree.topLevelItem(i))

    # ---- selection & bulk ----
    def _bulk_check(self, state):
        self.tree.blockSignals(True)
        is_checked = state == Qt.Checked
        for item in self._iter_tree_items():
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(REG_COL_KEY, state)
                _apply_checked_bg(item, self.tree, is_checked, REG_COL_KEY)
        self.tree.blockSignals(False)
        self._refresh_summary()

    def _on_item_changed(self, item, col):
        if col != REG_COL_KEY:
            return
        _apply_checked_bg(item, self.tree,
                          item.checkState(REG_COL_KEY) == Qt.Checked, REG_COL_KEY)
        self._refresh_summary()

    def _refresh_summary(self):
        matched_checked = 0
        empty_checked = 0
        for item in self._iter_tree_items():
            if not (item.flags() & Qt.ItemIsUserCheckable):
                continue
            if item.checkState(REG_COL_KEY) != Qt.Checked:
                continue
            font = item.font(REG_COL_KEY)
            if font.bold():
                matched_checked += 1
            elif font.italic():
                empty_checked += 1
            else:
                matched_checked += 1
        parts = []
        if matched_checked:
            parts.append(f"{matched_checked:,} matched")
        if empty_checked:
            parts.append(f"{empty_checked:,} empty parent(s) opted-in")
        self.lbl_summary.setText("Checked: " + ", ".join(parts) if parts else "")

    def _checked_targets(self) -> List[Tuple[str, str]]:
        targets = []
        for item in self._iter_tree_items():
            if not (item.flags() & Qt.ItemIsUserCheckable):
                continue
            if item.checkState(REG_COL_KEY) != Qt.Checked:
                continue
            data = item.data(REG_COL_KEY, Qt.UserRole)
            if not data or data[0] != "reg":
                continue
            _, hive_name, path = data
            if not path:
                continue
            targets.append((hive_name, path))
        return targets

    # ---- delete ----
    def delete_checked(self):
        targets = self._checked_targets()
        if not targets:
            QMessageBox.information(self, "Nothing to do", "No keys are checked.")
            return
        msg = (
            f"Delete {len(targets):,} registry key(s).\n\n"
            "This deletion is NOT reversible. "
            "If you want a backup, click 'Backup checked' first.\n\n"
            "Proceed?"
        )
        if QMessageBox.warning(
            self, "Confirm registry deletion", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        self.btn_search.setEnabled(False)
        self.btn_backup.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self.lbl_status.setText("Deleting...")
        self._del_errors: list = []
        self._del_worker = RegistryDeleteWorker(targets, False, parent=self)
        self._del_worker.progress.connect(self._on_del_progress)
        self._del_worker.item_error.connect(self._on_del_error)
        self._del_worker.finished_all.connect(self._on_del_finished)
        self._del_worker.start()

    def _on_del_progress(self, done, total, label):
        self.lbl_status.setText(f"{label}  ({done:,} / {total:,})")

    def _on_del_error(self, what, err):
        self._del_errors.append((what, err))

    def _on_del_finished(self, ok, fail):
        self.btn_search.setEnabled(True)
        self.btn_delete.setEnabled(False)
        self.lbl_status.setText(f"Done. Deleted {ok:,} key(s), {fail:,} failure(s).")
        if self._del_errors:
            shown = self._del_errors[:12]
            preview = "\n".join(f"{w}: {e}" for w, e in shown)
            more = f"\n...and {len(self._del_errors) - 12} more" if len(self._del_errors) > 12 else ""
            QMessageBox.warning(self, "Some operations failed", preview + more
                                + "\n\nNote: HKLM keys often require running as Administrator.")
        needle = self.input.text().strip()
        if needle:
            self.start_search()
        else:
            self.tree.clear()
            self._rows.clear()
            self._hive_items.clear()
            self._path_nodes.clear()

    # ---- open in regedit ----
    def _on_double_click(self, item, _col):
        self._open_item_in_regedit(item)

    def _on_selection_changed(self):
        self.btn_open_regedit.setEnabled(bool(self.tree.selectedItems()))

    def open_selected_in_regedit(self):
        sel = self.tree.selectedItems()
        if not sel:
            return
        self._open_item_in_regedit(sel[0])

    def _open_item_in_regedit(self, item):
        data = item.data(REG_COL_KEY, Qt.UserRole)
        if not data or data[0] != "reg":
            return
        _, hive_name, path = data
        ok, msg = open_in_regedit(hive_name, path)
        if ok:
            self.lbl_status.setText(f"Opened regedit at: {msg}")
        else:
            QMessageBox.warning(self, "Could not open regedit", msg)

    # ---- backup ----
    def backup_checked(self):
        targets = self._checked_targets()
        if not targets:
            QMessageBox.information(self, "Nothing to back up", "No keys are checked.")
            return
        self.btn_search.setEnabled(False)
        self.btn_backup.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self.lbl_status.setText("Backing up...")
        self._backup_errors = []
        self._backup_worker = RegistryBackupWorker(targets, parent=self)
        self._backup_worker.progress.connect(self._on_backup_progress)
        self._backup_worker.item_error.connect(self._on_backup_error)
        self._backup_worker.finished_all.connect(self._on_backup_finished)
        self._backup_worker.start()

    def _on_backup_progress(self, done, total, label):
        self.lbl_status.setText(f"{label}  ({done:,} / {total:,})")

    def _on_backup_error(self, what, err):
        self._backup_errors.append((what, err))

    def _on_backup_finished(self, folder, ok, fail):
        self.btn_search.setEnabled(True)
        if self._rows:
            self.btn_backup.setEnabled(True)
            self.btn_delete.setEnabled(True)
        self.lbl_status.setText(
            f"Backup complete: {ok:,} ok, {fail:,} failed -> {folder}"
        )
        if self._backup_errors:
            shown = self._backup_errors[:12]
            preview = "\n".join(f"{w}: {e}" for w, e in shown)
            more = (f"\n...and {len(self._backup_errors) - 12} more"
                    if len(self._backup_errors) > 12 else "")
            QMessageBox.warning(self, "Some backups failed", preview + more)

    def shutdown(self):
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(2000)
        if self._del_worker and self._del_worker.isRunning():
            self._del_worker.request_stop()
            self._del_worker.wait(2000)
        if self._backup_worker and self._backup_worker.isRunning():
            self._backup_worker.request_stop()
            self._backup_worker.wait(2000)


# =======================================================================
# Orphan paths tab
# =======================================================================

OP_COL_KEY, OP_COL_VALUE, OP_COL_PATH = 0, 1, 2


class OrphanPathsPage(QWidget):
    """Tab 3: scan the registry for values whose data is a filesystem path
    that no longer exists; preview as a regedit-style tree; delete the
    parent keys of confirmed orphans (with opt-in empty-parent cascade)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[OrphanScanWorker] = None
        self._del_worker: Optional[RegistryDeleteWorker] = None
        self._backup_worker: Optional[RegistryBackupWorker] = None
        self._del_errors: list = []
        self._backup_errors: list = []
        self._scan_t0 = 0.0
        self._rows: list = []                          # one entry per orphan key
        self._key_to_row_idx: dict = {}                # (hive, key_path) -> idx
        self._hive_items: dict = {}
        self._path_nodes: dict = {}
        self._empty_parents_by_hive: dict = {}

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        self._build_scan_row(v)
        self._build_tree(v)
        self._build_action_row(v)
        self._build_status(v)

    def _build_scan_row(self, lay):
        row = QHBoxLayout()
        row.addWidget(QLabel("Hives:"))
        self.cb_hives = {}
        for name, _ in HIVES:
            cb = QCheckBox(name)
            cb.setChecked(name in ("HKCR", "HKLM", "HKCU"))
            row.addWidget(cb)
            self.cb_hives[name] = cb
        row.addSpacing(8)
        self.cb_deep = QCheckBox("Deep scan")
        row.addWidget(self.cb_deep)
        row.addStretch(1)
        self.btn_scan = QPushButton("Scan")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        row.addWidget(self.btn_scan)
        row.addWidget(self.btn_stop)
        lay.addLayout(row)
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_stop.clicked.connect(self.stop_scan)

    def _build_tree(self, lay):
        self.tree = CheckRangeTreeWidget()
        self.tree.set_check_column(OP_COL_KEY)
        self.tree.setHeaderLabels(["Key", "Value", "Missing path"])
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setSortingEnabled(False)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(OP_COL_KEY, QHeaderView.Stretch)
        hdr.setSectionResizeMode(OP_COL_VALUE, QHeaderView.Interactive)
        hdr.setSectionResizeMode(OP_COL_PATH, QHeaderView.Interactive)
        self.tree.setColumnWidth(OP_COL_VALUE, 160)
        self.tree.setColumnWidth(OP_COL_PATH, 320)
        self.tree.setStyleSheet(f"QTreeWidget::item {{ height: {ROW_HEIGHT_PX}px; }}")
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        lay.addWidget(self.tree, 1)

    def _build_action_row(self, lay):
        row = QHBoxLayout()
        self.btn_check_all = QPushButton("Check all")
        self.btn_uncheck_all = QPushButton("Uncheck all")
        self.btn_open_regedit = QPushButton("Open in regedit")
        self.btn_open_regedit.setEnabled(False)
        self.btn_backup = QPushButton("Backup checked")
        self.btn_backup.setEnabled(False)
        self.btn_delete = QPushButton("Delete checked keys")
        self.btn_delete.setEnabled(False)
        row.addWidget(self.btn_check_all)
        row.addWidget(self.btn_uncheck_all)
        row.addSpacing(8)
        row.addWidget(self.btn_open_regedit)
        row.addStretch(1)
        row.addWidget(self.btn_backup)
        row.addWidget(self.btn_delete)
        lay.addLayout(row)
        self.btn_check_all.clicked.connect(lambda: self._bulk_check(Qt.Checked))
        self.btn_uncheck_all.clicked.connect(lambda: self._bulk_check(Qt.Unchecked))
        self.btn_open_regedit.clicked.connect(self.open_selected_in_regedit)
        self.btn_backup.clicked.connect(self.backup_checked)
        self.btn_delete.clicked.connect(self.delete_checked)

    def _build_status(self, lay):
        row = QHBoxLayout()
        self.lbl_status = QLabel("Idle")
        self.lbl_summary = QLabel("")
        row.addWidget(self.lbl_status, 1)
        row.addWidget(self.lbl_summary)
        lay.addLayout(row)

    # ---- scan ----
    def start_scan(self):
        hives = [n for n, _ in HIVES if self.cb_hives[n].isChecked()]
        if not hives:
            QMessageBox.information(self, "No hives", "Select at least one hive.")
            return
        deep = self.cb_deep.isChecked()
        if deep:
            if QMessageBox.question(
                self, "Slow scan",
                "Deep scan walks every value under every key in the selected hives. "
                "It can take several minutes (especially for HKLM and HKCR).\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes:
                return
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(2000)

        self.tree.blockSignals(True)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        self.tree.blockSignals(False)
        self._rows.clear()
        self._key_to_row_idx.clear()
        self._hive_items.clear()
        self._path_nodes.clear()
        self._empty_parents_by_hive.clear()
        self.btn_delete.setEnabled(False)
        self.btn_backup.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._scan_t0 = time.monotonic()
        label = "Deep scan" if deep else "Hot-spot scan"
        self.lbl_status.setText(f"{label} running...")
        self.lbl_summary.setText("")

        self._worker = OrphanScanWorker(hives, deep, parent=self)
        self._worker.match.connect(self._on_match)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_all.connect(self._on_scan_finished)
        self._worker.start()

    def stop_scan(self):
        if self._worker is not None:
            self._worker.request_stop()
            self.lbl_status.setText("Stopping scan...")

    # ---- tree building ----
    def _ensure_hive_root(self, hive_name: str) -> QTreeWidgetItem:
        item = self._hive_items.get(hive_name)
        if item is not None:
            return item
        item = QTreeWidgetItem([hive_name, "", ""])
        item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
        item.setData(OP_COL_KEY, Qt.UserRole, ("nav", hive_name, ""))
        font = item.font(OP_COL_KEY)
        font.setBold(True)
        item.setFont(OP_COL_KEY, font)
        self.tree.blockSignals(True)
        self.tree.addTopLevelItem(item)
        item.setExpanded(True)
        self.tree.blockSignals(False)
        self._hive_items[hive_name] = item
        self._path_nodes[(hive_name, "")] = item
        return item

    def _ensure_leaf(self, hive_name: str, path: str) -> QTreeWidgetItem:
        hive_item = self._ensure_hive_root(hive_name)
        parts = path.split("\\")
        parent_item = hive_item
        leaf = None
        self.tree.blockSignals(True)
        try:
            for i in range(1, len(parts) + 1):
                sub = "\\".join(parts[:i])
                key = (hive_name, sub)
                existing = self._path_nodes.get(key)
                if existing is not None:
                    parent_item = existing
                    continue
                name = parts[i - 1]
                if i == len(parts):
                    node = QTreeWidgetItem([name, "", ""])
                    node.setFlags(node.flags() | Qt.ItemIsUserCheckable)
                    parent_item.addChild(node)
                    node.setCheckState(OP_COL_KEY, Qt.Checked)
                    font = node.font(OP_COL_KEY)
                    font.setBold(True)
                    node.setFont(OP_COL_KEY, font)
                    node.setData(OP_COL_KEY, Qt.UserRole, ("orphan", hive_name, sub))
                    _apply_checked_bg(node, self.tree, True, OP_COL_KEY)
                    leaf = node
                    p = node.parent()
                    while p is not None:
                        p.setExpanded(True)
                        p = p.parent()
                else:
                    hh = HIVES_BY_NAME[hive_name]
                    info = reg_key_info(hh, sub)
                    _ns, _nv = info if info else (0, 0)
                    node = QTreeWidgetItem([name, "", ""])
                    node.setFlags(node.flags() & ~Qt.ItemIsUserCheckable)
                    node.setData(OP_COL_KEY, Qt.UserRole, ("nav", hive_name, sub))
                    parent_item.addChild(node)
                self._path_nodes[key] = node
                parent_item = node
        finally:
            self.tree.blockSignals(False)
        return leaf if leaf is not None else self._path_nodes[(hive_name, path)]

    def _on_match(self, m):
        key = (m.hive_name, m.key_path)
        idx = self._key_to_row_idx.get(key)
        if idx is None:
            leaf = self._ensure_leaf(m.hive_name, m.key_path)
            idx = len(self._rows)
            self._key_to_row_idx[key] = idx
            self._rows.append({
                "hive": m.hive_name, "path": m.key_path,
                "item": leaf, "matches": [m],
            })
        else:
            self._rows[idx]["matches"].append(m)
            leaf = self._rows[idx]["item"]
        matches = self._rows[idx]["matches"]
        val_label = (matches[0].value_name or "(default)")
        path_label = matches[0].missing_path
        if len(matches) > 1:
            val_label += f"  (+{len(matches) - 1} more)"
            path_label += f"  (+{len(matches) - 1} more)"
        self.tree.blockSignals(True)
        leaf.setText(OP_COL_VALUE, val_label)
        leaf.setText(OP_COL_PATH, path_label)
        leaf.setToolTip(OP_COL_KEY, "\n".join(
            f"{(mm.value_name or '(default)')}: {mm.missing_path}" for mm in matches
        ))
        self.tree.blockSignals(False)

    def _on_progress(self, location: str, count: int):
        self.lbl_status.setText(f"Scanning... at {location}  ({count:,} orphan(s) so far)")

    def _on_scan_finished(self, total: int):
        dt = time.monotonic() - self._scan_t0
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        has_any = bool(self._rows)
        self.btn_delete.setEnabled(has_any)
        self.btn_backup.setEnabled(has_any)
        by_hive: dict = {}
        for r in self._rows:
            by_hive.setdefault(r["hive"], []).append(r["path"])
        self._empty_parents_by_hive = {}
        for hive_name, paths in by_hive.items():
            hh = HIVES_BY_NAME.get(hive_name)
            if hh is None:
                continue
            self._empty_parents_by_hive[hive_name] = predict_empty_parents(hh, paths)
        self.tree.blockSignals(True)
        empty_count = 0
        for hive_name, paths in self._empty_parents_by_hive.items():
            for p in paths:
                node = self._path_nodes.get((hive_name, p))
                if node is None:
                    continue
                node.setFlags(node.flags() | Qt.ItemIsUserCheckable)
                node.setCheckState(OP_COL_KEY, Qt.Unchecked)
                font = node.font(OP_COL_KEY)
                font.setItalic(True)
                node.setFont(OP_COL_KEY, font)
                cur = node.text(OP_COL_KEY)
                if "(empty after delete)" not in cur:
                    node.setText(OP_COL_KEY, cur + "  (empty after delete)")
                empty_count += 1
        self.tree.blockSignals(False)
        self.lbl_status.setText(
            f"Scan complete in {dt:0.1f}s - {len(self._rows):,} orphan key(s), "
            f"{empty_count:,} parent(s) would be empty."
        )
        self._refresh_summary()

    # ---- tree iteration / selection ----
    def _iter_tree_items(self):
        def walk(item):
            yield item
            for i in range(item.childCount()):
                yield from walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            yield from walk(self.tree.topLevelItem(i))

    def _bulk_check(self, state):
        self.tree.blockSignals(True)
        is_checked = state == Qt.Checked
        for item in self._iter_tree_items():
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(OP_COL_KEY, state)
                _apply_checked_bg(item, self.tree, is_checked, OP_COL_KEY)
        self.tree.blockSignals(False)
        self._refresh_summary()

    def _on_item_changed(self, item, col):
        if col != OP_COL_KEY:
            return
        _apply_checked_bg(item, self.tree,
                          item.checkState(OP_COL_KEY) == Qt.Checked, OP_COL_KEY)
        self._refresh_summary()

    def _refresh_summary(self):
        orphans_checked = 0
        empty_checked = 0
        for item in self._iter_tree_items():
            if not (item.flags() & Qt.ItemIsUserCheckable):
                continue
            if item.checkState(OP_COL_KEY) != Qt.Checked:
                continue
            font = item.font(OP_COL_KEY)
            if font.italic():
                empty_checked += 1
            else:
                orphans_checked += 1
        parts = []
        if orphans_checked:
            parts.append(f"{orphans_checked:,} orphan(s)")
        if empty_checked:
            parts.append(f"{empty_checked:,} empty parent(s) opted-in")
        self.lbl_summary.setText("Checked: " + ", ".join(parts) if parts else "")

    def _checked_targets(self) -> List[Tuple[str, str]]:
        targets = []
        for item in self._iter_tree_items():
            if not (item.flags() & Qt.ItemIsUserCheckable):
                continue
            if item.checkState(OP_COL_KEY) != Qt.Checked:
                continue
            data = item.data(OP_COL_KEY, Qt.UserRole)
            if not data:
                continue
            _, hive_name, path = data
            if not path:
                continue
            targets.append((hive_name, path))
        return targets

    # ---- delete / backup ----
    def delete_checked(self):
        targets = self._checked_targets()
        if not targets:
            QMessageBox.information(self, "Nothing to do", "No keys are checked.")
            return
        msg = (
            f"Delete {len(targets):,} registry key(s).\n\n"
            "Each one either holds a value whose path no longer exists, or is "
            "an opted-in empty parent.\n\n"
            "This deletion is NOT reversible. If you want a backup, click "
            "'Backup checked' first.\n\nProceed?"
        )
        if QMessageBox.warning(
            self, "Confirm deletion", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        self.btn_scan.setEnabled(False)
        self.btn_backup.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self.lbl_status.setText("Deleting...")
        self._del_errors = []
        self._del_worker = RegistryDeleteWorker(targets, False, parent=self)
        self._del_worker.progress.connect(self._on_del_progress)
        self._del_worker.item_error.connect(self._on_del_error)
        self._del_worker.finished_all.connect(self._on_del_finished)
        self._del_worker.start()

    def _on_del_progress(self, done, total, label):
        self.lbl_status.setText(f"{label}  ({done:,} / {total:,})")

    def _on_del_error(self, what, err):
        self._del_errors.append((what, err))

    def _on_del_finished(self, ok, fail):
        self.btn_scan.setEnabled(True)
        self.btn_delete.setEnabled(False)
        self.lbl_status.setText(f"Done. Deleted {ok:,} key(s), {fail:,} failure(s).")
        if self._del_errors:
            shown = self._del_errors[:12]
            preview = "\n".join(f"{w}: {e}" for w, e in shown)
            more = (f"\n...and {len(self._del_errors) - 12} more"
                    if len(self._del_errors) > 12 else "")
            QMessageBox.warning(
                self, "Some operations failed",
                preview + more
                + "\n\nNote: HKLM keys often require running as Administrator.",
            )
        self.tree.clear()
        self._rows.clear()
        self._key_to_row_idx.clear()
        self._hive_items.clear()
        self._path_nodes.clear()

    def backup_checked(self):
        targets = self._checked_targets()
        if not targets:
            QMessageBox.information(self, "Nothing to back up", "No keys are checked.")
            return
        self.btn_scan.setEnabled(False)
        self.btn_backup.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self.lbl_status.setText("Backing up...")
        self._backup_errors = []
        self._backup_worker = RegistryBackupWorker(targets, parent=self)
        self._backup_worker.progress.connect(self._on_backup_progress)
        self._backup_worker.item_error.connect(self._on_backup_error)
        self._backup_worker.finished_all.connect(self._on_backup_finished)
        self._backup_worker.start()

    def _on_backup_progress(self, done, total, label):
        self.lbl_status.setText(f"{label}  ({done:,} / {total:,})")

    def _on_backup_error(self, what, err):
        self._backup_errors.append((what, err))

    def _on_backup_finished(self, folder, ok, fail):
        self.btn_scan.setEnabled(True)
        if self._rows:
            self.btn_backup.setEnabled(True)
            self.btn_delete.setEnabled(True)
        self.lbl_status.setText(
            f"Backup complete: {ok:,} ok, {fail:,} failed -> {folder}"
        )
        if self._backup_errors:
            shown = self._backup_errors[:12]
            preview = "\n".join(f"{w}: {e}" for w, e in shown)
            more = (f"\n...and {len(self._backup_errors) - 12} more"
                    if len(self._backup_errors) > 12 else "")
            QMessageBox.warning(self, "Some backups failed", preview + more)

    # ---- open in regedit ----
    def _on_double_click(self, item, _col):
        self._open_item_in_regedit(item)

    def _on_selection_changed(self):
        self.btn_open_regedit.setEnabled(bool(self.tree.selectedItems()))

    def open_selected_in_regedit(self):
        sel = self.tree.selectedItems()
        if not sel:
            return
        self._open_item_in_regedit(sel[0])

    def _open_item_in_regedit(self, item):
        data = item.data(OP_COL_KEY, Qt.UserRole)
        if not data:
            return
        _, hive_name, path = data
        ok, msg = open_in_regedit(hive_name, path)
        if ok:
            self.lbl_status.setText(f"Opened regedit at: {msg}")
        else:
            QMessageBox.warning(self, "Could not open regedit", msg)

    def shutdown(self):
        for w in (self._worker, self._del_worker, self._backup_worker):
            if w and w.isRunning():
                w.request_stop()
                w.wait(2000)


# =======================================================================
# Uninstall tab
# =======================================================================

(UN_COL_NAME, UN_COL_VER, UN_COL_PUB, UN_COL_DATE, UN_COL_SIZE, UN_COL_ARCH, UN_COL_VALID,
 UN_COL_SILENT, UN_COL_CMD) = range(9)


class UninstallPage(QWidget):
    """Tab 3: enumerate Add/Remove Programs entries; either run their
    uninstaller or strip orphaned entries from the registry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[UninstallEntry] = []
        self._enum_worker: Optional[UninstallEnumWorker] = None
        self._run_worker: Optional[UninstallRunWorker] = None
        self._remove_worker: Optional[UninstallRemoveWorker] = None
        self._remove_errors: list = []
        self._enum_t0 = 0.0
        self._icon_cache: dict = {}    # (norm_path, idx) -> QIcon | None
        self._checked: set = set()     # _entry_key of checked rows, kept across filtering

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        self._build_top(v)
        self._build_tree(v)
        self._build_action_row(v)
        self._build_status(v)

        self.refresh()

    def _build_top(self, lay):
        row = QHBoxLayout()
        row.addWidget(QLabel("Filter:"))
        self.input = QLineEdit()
        row.addWidget(self.input, 1)
        self.cb_invalid_only = QCheckBox("Invalid only")
        self.cb_show_hidden = QCheckBox("Show system components")
        self.btn_refresh = QPushButton("Refresh")
        row.addWidget(self.cb_invalid_only)
        row.addWidget(self.cb_show_hidden)
        row.addWidget(self.btn_refresh)
        lay.addLayout(row)
        self.input.textChanged.connect(self._apply_filter)
        self.cb_invalid_only.toggled.connect(self._apply_filter)
        self.cb_show_hidden.toggled.connect(self._apply_filter)
        self.btn_refresh.clicked.connect(self.refresh)

    def _build_tree(self, lay):
        from PyQt5.QtCore import QSize
        self.tree = CheckRangeTreeWidget()
        self.tree.set_check_column(UN_COL_NAME)
        self.tree.setHeaderLabels(
            ["Name", "Version", "Publisher", "Installed", "Size", "Source", "Valid", "Silent",
             "Uninstall command"]
        )
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setIconSize(QSize(16, 16))
        hdr = self.tree.header()
        for c in (UN_COL_NAME, UN_COL_VER, UN_COL_PUB, UN_COL_DATE,
                  UN_COL_SIZE, UN_COL_ARCH, UN_COL_VALID, UN_COL_SILENT):
            hdr.setSectionResizeMode(c, QHeaderView.Interactive)
        hdr.setSectionResizeMode(UN_COL_CMD, QHeaderView.Stretch)
        self.tree.setColumnWidth(UN_COL_NAME, 280)
        self.tree.setColumnWidth(UN_COL_VER, 90)
        self.tree.setColumnWidth(UN_COL_PUB, 180)
        self.tree.setColumnWidth(UN_COL_DATE, 80)
        self.tree.setColumnWidth(UN_COL_SIZE, 80)
        self.tree.setColumnWidth(UN_COL_ARCH, 60)
        self.tree.setColumnWidth(UN_COL_VALID, 120)
        self.tree.setColumnWidth(UN_COL_SILENT, 55)
        self.tree.setStyleSheet(f"QTreeWidget::item {{ height: {ROW_HEIGHT_PX}px; }}")
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(lambda it, _col: self.run_selected([it]))
        lay.addWidget(self.tree, 1)

    def _build_action_row(self, lay):
        row = QHBoxLayout()
        self.btn_run = QPushButton("Uninstall")
        self.btn_run.setEnabled(False)
        self.cb_quiet = QCheckBox("Silent when possible")
        self.cb_quiet.setChecked(True)
        self.cb_quiet.setToolTip(
            "Uses the program's QuietUninstallString, or the standard silent switches for\n"
            "MSI, Inno Setup and NSIS uninstallers (see the Silent column). Others still\n"
            "show their own dialogs.")
        self.btn_uncheck = QPushButton("Uncheck all")
        self.btn_uncheck.setEnabled(False)
        self.btn_remove_entry = QPushButton("Remove list entry")
        self.btn_remove_entry.setEnabled(False)
        self.cb_backup = QCheckBox("Auto-backup to .reg before removal")
        self.cb_backup.setChecked(True)
        row.addWidget(self.btn_run)
        row.addWidget(self.cb_quiet)
        row.addWidget(self.btn_uncheck)
        row.addStretch(1)
        row.addWidget(self.btn_remove_entry)
        row.addWidget(self.cb_backup)
        lay.addLayout(row)
        self.btn_run.clicked.connect(lambda: self.run_selected())
        self.btn_uncheck.clicked.connect(self._uncheck_all)
        self.btn_remove_entry.clicked.connect(lambda: self.remove_selected())

    def _build_status(self, lay):
        row = QHBoxLayout()
        self.lbl_status = QLabel("Loading installed programs...")
        self.lbl_summary = QLabel("")
        row.addWidget(self.lbl_status, 1)
        row.addWidget(self.lbl_summary)
        lay.addLayout(row)

    # ---- enum/refresh ----
    def refresh(self):
        if self._enum_worker is not None and self._enum_worker.isRunning():
            self._enum_worker.request_stop()
            self._enum_worker.wait(2000)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        self._entries.clear()
        self.btn_refresh.setEnabled(False)
        self.lbl_status.setText("Enumerating installed programs...")
        self._enum_t0 = time.monotonic()
        self._enum_worker = UninstallEnumWorker(parent=self)
        self._enum_worker.entry.connect(self._on_entry)
        self._enum_worker.finished_all.connect(self._on_enum_finished)
        self._enum_worker.start()

    def _on_entry(self, e: UninstallEntry):
        self._entries.append(e)

    def _on_enum_finished(self, total: int):
        self._checked &= {self._entry_key(e) for e in self._entries}
        self._populate_tree()
        self._on_selection_changed()
        self.tree.setSortingEnabled(True)
        self.btn_refresh.setEnabled(True)
        dt = time.monotonic() - self._enum_t0
        invalid_count = sum(1 for e in self._entries if not e.is_valid)
        self.lbl_status.setText(
            f"Loaded {total:,} entries in {dt:0.1f}s "
            f"({invalid_count:,} invalid)."
        )

    def _icon_for(self, e: UninstallEntry):
        entry_key = ("entry", e.hive_name, e.arch_tag, e.key_path)
        if entry_key in self._icon_cache:
            return self._icon_cache[entry_key]

        icon = None
        for path, idx in _icon_candidates_for(e):
            expanded = os.path.expandvars(path)
            if not os.path.isfile(expanded):
                continue
            src_key = ("ext", os.path.normcase(expanded), idx)
            if src_key in self._icon_cache:
                cached = self._icon_cache[src_key]
                if cached is not None:
                    icon = cached
                    break
                continue
            pix = _extract_icon_from_path(expanded, idx)
            if pix is not None:
                icon = QIcon(pix)
                self._icon_cache[src_key] = icon
                break
            self._icon_cache[src_key] = None

        if icon is None:
            for path, _idx in _icon_candidates_for(e):
                expanded = os.path.expandvars(path)
                sh_key = ("shgfi", os.path.normcase(expanded))
                if sh_key in self._icon_cache:
                    cached = self._icon_cache[sh_key]
                    if cached is not None:
                        icon = cached
                        break
                    continue
                pix = _shgetfileinfo_icon(expanded)
                if pix is not None:
                    icon = QIcon(pix)
                    self._icon_cache[sh_key] = icon
                    break
                self._icon_cache[sh_key] = None

        if icon is None:
            gen_key = "generic"
            if gen_key in self._icon_cache:
                icon = self._icon_cache[gen_key]
            else:
                pix = _extract_icon_from_path(*GENERIC_ICON_SOURCE)
                icon = QIcon(pix) if pix is not None else None
                self._icon_cache[gen_key] = icon

        self._icon_cache[entry_key] = icon
        return icon

    def _populate_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        items = []
        for e in self._entries:
            if not self._passes_filter(e):
                continue
            size = human_size(e.estimated_size_kb * 1024) if e.estimated_size_kb else ""
            valid_label = "yes" if e.is_valid else f"NO - {e.invalid_reason}"
            cmd = e.uninstall_string or e.quiet_uninstall_string
            silent = silent_command(e)[1] if cmd or e.is_msi else ""
            it = QTreeWidgetItem([
                e.display, e.display_version, e.publisher, e.install_date,
                size, e.arch_tag, valid_label, silent, cmd,
            ])
            it.setData(UN_COL_NAME, Qt.UserRole, e)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            checked = self._entry_key(e) in self._checked
            it.setCheckState(UN_COL_NAME, Qt.Checked if checked else Qt.Unchecked)
            if checked:
                _apply_checked_bg(it, self.tree, True)
            icon = self._icon_for(e)
            if icon is not None:
                it.setIcon(UN_COL_NAME, icon)
            items.append(it)
        self.tree.addTopLevelItems(items)
        self.tree.blockSignals(False)
        self._refresh_summary()

    @staticmethod
    def _entry_key(e: UninstallEntry):
        return (e.hive_name, e.arch_tag, e.key_path)

    def _on_item_changed(self, item, col):
        if col != UN_COL_NAME:
            return
        e = item.data(UN_COL_NAME, Qt.UserRole)
        checked = item.checkState(UN_COL_NAME) == Qt.Checked
        (self._checked.add if checked else self._checked.discard)(self._entry_key(e))
        self.tree.blockSignals(True)
        _apply_checked_bg(item, self.tree, checked)
        self.tree.blockSignals(False)
        self._on_selection_changed()

    def _uncheck_all(self):
        self._checked.clear()
        self._populate_tree()
        self._on_selection_changed()

    def _refresh_summary(self):
        shown = self.tree.topLevelItemCount()
        text = f"Showing {shown:,} of {len(self._entries):,}"
        if self._checked:
            text += f"   {len(self._checked):,} checked"
        self.lbl_summary.setText(text)

    def _passes_filter(self, e: UninstallEntry) -> bool:
        if not self.cb_show_hidden.isChecked():
            if e.system_component:
                return False
            if e.parent_key_name:
                return False
            if e.display_name.lower().startswith("windows driver package"):
                return False
            if not e.display_name and not e.is_valid:
                return False
        if self.cb_invalid_only.isChecked() and e.is_valid:
            return False
        needle = self.input.text().strip().lower()
        if needle:
            hay = " ".join([
                e.display_name, e.publisher, e.install_location,
                e.uninstall_string, e.sub_name,
            ]).lower()
            if needle not in hay:
                return False
        return True

    def _apply_filter(self, *_):
        self._populate_tree()

    # ---- selection / button enabling ----
    def _on_selection_changed(self):
        entries = self._selected_entries()
        runnable = [e for e in entries if e.uninstall_string or e.quiet_uninstall_string]
        n = f" ({len(entries):,})" if len(entries) > 1 else ""
        self.btn_run.setText(f"Uninstall{n}")
        self.btn_remove_entry.setText(f"Remove list entry{n}")
        self.btn_run.setEnabled(bool(runnable))
        self.btn_remove_entry.setEnabled(bool(entries))
        self.btn_uncheck.setEnabled(bool(self._checked))
        self._refresh_summary()

    def _selected_entries(self) -> List[UninstallEntry]:
        """The checked entries, or the selected rows when nothing is checked."""
        if self._checked:
            return [e for e in self._entries if self._entry_key(e) in self._checked]
        return [it.data(UN_COL_NAME, Qt.UserRole) for it in self.tree.selectedItems()]

    @staticmethod
    def _name_list(entries, limit=15):
        names = "\n  ".join(e.display for e in entries[:limit])
        more = f"\n  ... and {len(entries) - limit} more" if len(entries) > limit else ""
        return f"  {names}{more}"

    # ---- actions ----
    def run_selected(self, items=None, confirm=True):
        source = ([it.data(UN_COL_NAME, Qt.UserRole) for it in items] if items
                  else self._selected_entries())
        entries = [e for e in source if e.uninstall_string or e.quiet_uninstall_string]
        if not entries:
            return
        quiet = self.cb_quiet.isChecked()
        loud = [e for e in entries if not quiet or not silent_command(e)[1]]
        notes = []
        if loud:
            notes.append(f"{len(loud):,} of them will show their own uninstaller dialogs.")
        if not ctypes.windll.shell32.IsUserAnAdmin():
            notes.append("wintools is not elevated, so each may ask for UAC.")
        if confirm and QMessageBox.question(
            self, "Uninstall",
            f"Uninstall {len(entries):,} program(s), one after another?\n\n"
            f"{self._name_list(entries)}\n\n" + " ".join(notes),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        self._checked -= {self._entry_key(e) for e in entries}
        self.btn_run.setEnabled(False)
        self.btn_remove_entry.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.lbl_status.setText("Running uninstallers...")
        self._run_worker = UninstallRunWorker(entries, quiet, parent=self)
        self._run_worker.starting.connect(self._on_run_starting)
        self._run_worker.finished_one.connect(self._on_run_one)
        self._run_worker.finished_all.connect(self._on_run_all)
        self._run_worker.start()

    def _on_run_starting(self, e: UninstallEntry):
        self.lbl_status.setText(f"Uninstalling: {e.display}...")

    def _on_run_one(self, e: UninstallEntry, rc: int):
        self.lbl_status.setText(f"Finished: {e.display} (exit={rc}).")

    def _on_run_all(self, ok: int, fail: int):
        self.lbl_status.setText(f"Uninstall run complete. {ok:,} exit-0, {fail:,} non-zero.")
        self.btn_refresh.setEnabled(True)
        self.refresh()

    def remove_selected(self, confirm=True):
        entries = self._selected_entries()
        if not entries:
            return
        valid_ones = [e for e in entries if e.is_valid]
        do_backup = self.cb_backup.isChecked()
        msg = f"Remove {len(entries):,} Add/Remove Programs entr{'y' if len(entries) == 1 else 'ies'}?"
        msg += f"\n\n{self._name_list(entries)}\n\n"
        if valid_ones:
            msg += (f"{len(valid_ones):,} of them still have a working uninstaller; removing "
                    "the entry leaves the program's files on disk. ")
        msg += ("A .reg restore file is written for each." if do_backup
                else "No backup will be made.")
        if confirm and QMessageBox.warning(
            self, "Remove list entries", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        self._checked -= {self._entry_key(e) for e in entries}
        self.btn_run.setEnabled(False)
        self.btn_remove_entry.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.lbl_status.setText("Removing entries...")
        self._remove_errors = []
        self._remove_worker = UninstallRemoveWorker(entries, do_backup, parent=self)
        self._remove_worker.progress.connect(self._on_remove_progress)
        self._remove_worker.item_error.connect(
            lambda w, e: self._remove_errors.append((w, e))
        )
        self._remove_worker.backup_done.connect(
            lambda folder, ok, fail: self.lbl_status.setText(
                f"Backup: {ok:,} ok, {fail:,} failed -> {folder}"
            )
        )
        self._remove_worker.finished_all.connect(self._on_remove_finished)
        self._remove_worker.start()

    def _on_remove_progress(self, done, total, label):
        self.lbl_status.setText(f"{label}  ({done:,} / {total:,})")

    def _on_remove_finished(self, ok, fail):
        self.btn_refresh.setEnabled(True)
        self.lbl_status.setText(f"Removed {ok:,} entry/entries, {fail:,} failure(s).")
        if self._remove_errors:
            shown = self._remove_errors[:12]
            preview = "\n".join(f"{w}: {e}" for w, e in shown)
            more = (f"\n...and {len(self._remove_errors) - 12} more"
                    if len(self._remove_errors) > 12 else "")
            QMessageBox.warning(
                self, "Some operations failed",
                preview + more
                + "\n\nNote: HKLM entries often require running as Administrator."
            )
        self.refresh()

    def shutdown(self):
        for w in (self._enum_worker, self._run_worker, self._remove_worker):
            if w and w.isRunning():
                w.request_stop()
                w.wait(2000)


# =======================================================================
# Empty folders + Largest files tabs
# =======================================================================

# Windows file-attribute bits (FILE_ATTRIBUTE_*). Mirrors winnt.h.
_FA_HIDDEN        = 0x00000002
_FA_SYSTEM        = 0x00000004
_FA_REPARSE_POINT = 0x00000400

# Files that we consider "cruft" - a folder containing ONLY these is empty.
_EMPTY_MARKER_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}


def _reveal_in_explorer(path: str):
    """Open Explorer focused on `path`. Folder -> open it; file -> select it."""
    try:
        p = os.path.normpath(path)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if os.path.isdir(p):
            subprocess.Popen(["explorer", p], creationflags=flags)
        else:
            subprocess.Popen(["explorer", "/select,", p], creationflags=flags)
    except Exception:
        pass


_DOPUSRT_CACHE: list = []  # one-shot cache: [] = not searched, [None] = absent


def _find_dopusrt() -> Optional[str]:
    """Locate dopusrt.exe (Directory Opus runtime). Cached after first call."""
    if _DOPUSRT_CACHE:
        return _DOPUSRT_CACHE[0]
    found: Optional[str] = None
    candidates = []
    for env in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            candidates.append(
                os.path.join(base, "GPSoftware", "Directory Opus", "dopusrt.exe")
            )
    # Registry install path: HKLM\SOFTWARE\GPSoftware\Directory Opus\InstallPath
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root,
                                r"SOFTWARE\GPSoftware\Directory Opus",
                                0, winreg.KEY_READ) as k:
                try:
                    val, _ = winreg.QueryValueEx(k, "InstallPath")
                    if isinstance(val, str) and val:
                        candidates.append(os.path.join(val, "dopusrt.exe"))
                except OSError:
                    pass
        except OSError:
            continue
    for c in candidates:
        if c and os.path.isfile(c):
            found = c
            break
    _DOPUSRT_CACHE.append(found)
    return found


def _open_in_dopus(path: str) -> bool:
    """Open `path` in Directory Opus via dopusrt.exe /cmd Go. Returns True
    on success, False if DOpus isn't installed or the call failed."""
    rt = _find_dopusrt()
    if not rt:
        return False
    try:
        p = os.path.normpath(path)
        subprocess.Popen(
            [rt, "/cmd", "Go", p],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:
        return False


def _reveal_in_file_manager(path: str):
    """Open `path` in Directory Opus when available, else fall back to
    Explorer. Used by tabs that want a 'view this' affordance."""
    if not _open_in_dopus(path):
        _reveal_in_explorer(path)


class EmptyFolderScanWorker(QThread):
    """Recursively scans `root`, emitting ONLY strictly-empty leaf folders.

    A folder is "empty" iff its own scandir yields nothing - no files,
    no subfolders. (With 'treat markers as empty' on, desktop.ini /
    Thumbs.db / .DS_Store don't count as files.) Parent folders whose
    only children are empty subfolders are NOT reported - the user has
    to recycle each leaf. Junctions / symlinks / (optionally) hidden +
    system dirs are never descended into.
    """
    progress = pyqtSignal(str, int)
    found = pyqtSignal(str)
    finished_all = pyqtSignal(int, int)  # found_count, errors

    def __init__(self, root: str, skip_reparse: bool = True,
                 skip_hidden: bool = True, treat_markers_empty: bool = True,
                 parent=None):
        super().__init__(parent)
        self._root = os.path.normpath(root)
        self._skip_reparse = skip_reparse
        self._skip_hidden = skip_hidden
        self._treat_markers_empty = treat_markers_empty
        self._stop = False
        self._count = 0
        self._errors = 0
        self._last_progress = 0.0

    def request_stop(self):
        self._stop = True

    def run(self):
        try:
            self._scan(self._root)
        except Exception:
            self._errors += 1
        self.finished_all.emit(self._count, self._errors)

    def _emit_found(self, path: str):
        self._count += 1
        self.found.emit(path)

    def _emit_progress(self, path: str):
        now = time.monotonic()
        if now - self._last_progress < 0.1:
            return
        self._last_progress = now
        self.progress.emit(path, self._count)

    def _is_marker(self, name: str) -> bool:
        return self._treat_markers_empty and name.lower() in _EMPTY_MARKER_NAMES

    def _is_skippable_dir(self, entry) -> bool:
        try:
            st = entry.stat(follow_symlinks=False)
            attrs = getattr(st, "st_file_attributes", 0)
        except OSError:
            return True
        if self._skip_reparse and (attrs & _FA_REPARSE_POINT):
            return True
        if self._skip_hidden and (attrs & (_FA_HIDDEN | _FA_SYSTEM)):
            return True
        return False

    def _scan(self, path: str):
        """Walk `path`. Emit it (and only it) if it's a strictly-empty leaf
        - no non-marker files AND no subfolders. Recurse into subfolders
        regardless so we find empty leaves further down."""
        if self._stop:
            return
        self._emit_progress(path)
        has_any_file = False
        has_any_dir = False
        subdirs: list = []
        try:
            it = os.scandir(path)
        except (OSError, PermissionError):
            self._errors += 1
            return
        try:
            for entry in it:
                if self._stop:
                    return
                try:
                    if entry.is_file(follow_symlinks=False):
                        if not self._is_marker(entry.name):
                            has_any_file = True
                    elif entry.is_dir(follow_symlinks=False):
                        has_any_dir = True
                        if not self._is_skippable_dir(entry):
                            subdirs.append(entry.path)
                    else:
                        # Special device / unknown -> treat as content.
                        has_any_file = True
                except OSError:
                    has_any_file = True
                    continue
        finally:
            try:
                it.close()
            except Exception:
                pass
        if not has_any_file and not has_any_dir:
            # Strictly empty (modulo allowed marker files). Emit and stop.
            self._emit_found(path)
            return
        for p in subdirs:
            if self._stop:
                return
            self._scan(p)


class EmptyFoldersPage(QWidget):
    """Tab: find recursively-empty folders beneath a root, recycle them."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[EmptyFolderScanWorker] = None
        self._scan_t0 = 0.0
        self._items: list = []
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        self._build_top_row(v)
        self._build_tree(v)
        self._build_action_row(v)
        self._build_status(v)

    def _build_top_row(self, lay):
        row = QHBoxLayout()
        row.addWidget(QLabel("Root:"))
        self.input_root = QLineEdit()
        row.addWidget(self.input_root, 1)
        self.btn_browse = QPushButton("Browse...")
        row.addWidget(self.btn_browse)
        self.cb_skip_reparse = QCheckBox("Skip junctions / symlinks")
        self.cb_skip_reparse.setChecked(True)
        row.addWidget(self.cb_skip_reparse)
        self.cb_skip_hidden = QCheckBox("Skip hidden / system")
        self.cb_skip_hidden.setChecked(True)
        row.addWidget(self.cb_skip_hidden)
        self.cb_markers = QCheckBox("Treat desktop.ini / Thumbs.db as empty")
        self.cb_markers.setChecked(True)
        row.addWidget(self.cb_markers)
        self.btn_scan = QPushButton("Scan")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        row.addWidget(self.btn_scan)
        row.addWidget(self.btn_stop)
        lay.addLayout(row)
        self.btn_browse.clicked.connect(self._browse_root)
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_stop.clicked.connect(self.stop_scan)
        self.input_root.returnPressed.connect(self.start_scan)

    def _build_tree(self, lay):
        self.tree = CheckRangeTreeWidget()
        self.tree.set_check_column(0)
        self.tree.setHeaderLabels(["Empty folder"])
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setSortingEnabled(True)
        self.tree.setStyleSheet(
            f"QTreeWidget::item {{ height: {ROW_HEIGHT_PX}px; }}"
        )
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        lay.addWidget(self.tree, 1)

    def _build_action_row(self, lay):
        row = QHBoxLayout()
        self.btn_check_all = QPushButton("Check all")
        self.btn_uncheck_all = QPushButton("Uncheck all")
        # Prefer Directory Opus; the helper falls back to Explorer when
        # dopusrt.exe isn't installed.
        has_dopus = _find_dopusrt() is not None
        self.btn_open = QPushButton(
            "Open in DOpus" if has_dopus else "Open in Explorer"
        )
        self.btn_open.setEnabled(False)
        self.btn_recycle = QPushButton("Recycle checked")
        self.btn_recycle.setEnabled(False)
        row.addWidget(self.btn_check_all)
        row.addWidget(self.btn_uncheck_all)
        row.addSpacing(8)
        row.addWidget(self.btn_open)
        row.addStretch(1)
        row.addWidget(self.btn_recycle)
        lay.addLayout(row)
        self.btn_check_all.clicked.connect(lambda: self._bulk_check(Qt.Checked))
        self.btn_uncheck_all.clicked.connect(lambda: self._bulk_check(Qt.Unchecked))
        self.btn_open.clicked.connect(self._open_selected)
        self.btn_recycle.clicked.connect(self._recycle_checked)

    def _build_status(self, lay):
        row = QHBoxLayout()
        self.lbl_status = QLabel("Idle")
        self.lbl_summary = QLabel("")
        row.addWidget(self.lbl_status, 1)
        row.addWidget(self.lbl_summary)
        lay.addLayout(row)

    def _browse_root(self):
        start = self.input_root.text().strip() or os.path.expanduser("~")
        p = QFileDialog.getExistingDirectory(self, "Pick root folder", start)
        if p:
            self.input_root.setText(p)

    def start_scan(self):
        root = self.input_root.text().strip()
        if not root or not os.path.isdir(root):
            QMessageBox.information(
                self, "Pick a root",
                "Choose an existing folder to scan."
            )
            return
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(2000)
        self.tree.blockSignals(True)
        self.tree.clear()
        self.tree.blockSignals(False)
        self._items.clear()
        self.btn_recycle.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._scan_t0 = time.monotonic()
        self.lbl_status.setText(f"Scanning {root}...")
        self.lbl_summary.setText("")
        self._worker = EmptyFolderScanWorker(
            root,
            skip_reparse=self.cb_skip_reparse.isChecked(),
            skip_hidden=self.cb_skip_hidden.isChecked(),
            treat_markers_empty=self.cb_markers.isChecked(),
            parent=self,
        )
        self._worker.found.connect(self._on_found)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.start()

    def stop_scan(self):
        if self._worker is not None:
            self._worker.request_stop()
            self.lbl_status.setText("Stopping scan...")

    def _on_found(self, path: str):
        item = QTreeWidgetItem([path])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Unchecked)
        item.setToolTip(0, path)
        self.tree.blockSignals(True)
        self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)
        self._items.append(item)

    def _on_progress(self, location: str, found: int):
        self.lbl_status.setText(
            f"Scanning... at {location}  ({found:,} empty)"
        )

    def _on_finished(self, count: int, errors: int):
        dt = time.monotonic() - self._scan_t0
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        msg = f"Scan complete: {count:,} empty folder(s) in {dt:,.1f}s"
        if errors:
            msg += f"  ({errors:,} error(s))"
        self.lbl_status.setText(msg)
        self._update_summary()

    def _bulk_check(self, state):
        self.tree.blockSignals(True)
        try:
            for it in self._items:
                it.setCheckState(0, state)
        finally:
            self.tree.blockSignals(False)
        self._update_summary()

    def _on_item_changed(self, item, col):
        if col == 0:
            self._update_summary()

    def _update_summary(self):
        n = sum(1 for it in self._items
                if it.checkState(0) == Qt.Checked)
        self.lbl_summary.setText(f"{n:,} checked")
        self.btn_recycle.setEnabled(n > 0)

    def _on_selection_changed(self):
        self.btn_open.setEnabled(bool(self.tree.selectedItems()))

    def _on_double_click(self, item, col):
        _reveal_in_file_manager(item.text(0))

    def _open_selected(self):
        sel = self.tree.selectedItems()
        if not sel:
            return
        _reveal_in_file_manager(sel[0].text(0))

    def _recycle_checked(self):
        targets = [it for it in self._items
                   if it.checkState(0) == Qt.Checked]
        if not targets:
            return
        if QMessageBox.question(
            self, "Recycle empty folders",
            f"Send {len(targets):,} empty folder(s) to the Recycle Bin?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        ok = fail = 0
        recycled = []
        for it in targets:
            if recycle([it.text(0)])[1]:
                fail += 1
            else:
                ok += 1
                recycled.append(it)
        self.tree.blockSignals(True)
        try:
            for it in recycled:
                idx = self.tree.indexOfTopLevelItem(it)
                if idx >= 0:
                    self.tree.takeTopLevelItem(idx)
            done = set(id(it) for it in recycled)
            self._items = [it for it in self._items if id(it) not in done]
        finally:
            self.tree.blockSignals(False)
        msg = f"Recycled {ok:,} folder(s)"
        if fail:
            msg += f"; {fail:,} failed"
        self.lbl_status.setText(msg + ".")
        self._update_summary()

    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(2000)


class LargestFilesScanWorker(QThread):
    """Walks `root` and keeps a top-N min-heap of the largest files seen."""
    progress = pyqtSignal(str, int)               # current path, files scanned
    finished_all = pyqtSignal(list, int)          # [(size, path), ...], errors

    def __init__(self, root: str, top_n: int, min_bytes: int,
                 skip_reparse: bool = True, parent=None):
        super().__init__(parent)
        self._root = os.path.normpath(root)
        self._top_n = max(1, int(top_n))
        self._min_bytes = max(0, int(min_bytes))
        self._skip_reparse = skip_reparse
        self._stop = False
        self._scanned = 0
        self._errors = 0
        self._last_progress = 0.0

    def request_stop(self):
        self._stop = True

    def run(self):
        heap: list = []
        try:
            self._walk(self._root, heap)
        except Exception:
            self._errors += 1
        ordered = sorted(heap, key=lambda x: -x[0])
        self.finished_all.emit(ordered, self._errors)

    def _emit_progress(self, path: str):
        now = time.monotonic()
        if now - self._last_progress < 0.15:
            return
        self._last_progress = now
        self.progress.emit(path, self._scanned)

    def _is_reparse(self, entry) -> bool:
        if not self._skip_reparse:
            return False
        try:
            st = entry.stat(follow_symlinks=False)
            return bool(getattr(st, "st_file_attributes", 0)
                        & _FA_REPARSE_POINT)
        except OSError:
            return True

    def _walk(self, path: str, heap: list):
        if self._stop:
            return
        try:
            it = os.scandir(path)
        except (OSError, PermissionError):
            self._errors += 1
            return
        try:
            for entry in it:
                if self._stop:
                    return
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if self._is_reparse(entry):
                            continue
                        self._walk(entry.path, heap)
                    elif entry.is_file(follow_symlinks=False):
                        if self._is_reparse(entry):
                            continue
                        try:
                            sz = entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            self._errors += 1
                            continue
                        self._scanned += 1
                        if sz < self._min_bytes:
                            continue
                        if len(heap) < self._top_n:
                            heapq.heappush(heap, (sz, entry.path))
                        elif sz > heap[0][0]:
                            heapq.heapreplace(heap, (sz, entry.path))
                        self._emit_progress(entry.path)
                except OSError:
                    self._errors += 1
                    continue
        finally:
            try:
                it.close()
            except Exception:
                pass


LF_COL_CHK, LF_COL_SIZE, LF_COL_PATH = 0, 1, 2


class LargestFilesPage(QWidget):
    """Tab: find the largest files under a root and recycle the checked ones."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: Optional[LargestFilesScanWorker] = None
        self._scan_t0 = 0.0
        self._items: list = []
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        self._build_top_row(v)
        self._build_tree(v)
        self._build_action_row(v)
        self._build_status(v)

    def _build_top_row(self, lay):
        row = QHBoxLayout()
        row.addWidget(QLabel("Root:"))
        self.input_root = QLineEdit()
        row.addWidget(self.input_root, 1)
        self.btn_browse = QPushButton("Browse...")
        row.addWidget(self.btn_browse)
        row.addSpacing(8)
        row.addWidget(QLabel("Top N:"))
        self.sb_topn = QSpinBox()
        self.sb_topn.setRange(10, 100000)
        self.sb_topn.setSingleStep(50)
        self.sb_topn.setValue(500)
        row.addWidget(self.sb_topn)
        row.addWidget(QLabel("Min size (MB):"))
        self.sb_min = QSpinBox()
        self.sb_min.setRange(0, 1_000_000)
        self.sb_min.setSingleStep(10)
        self.sb_min.setValue(10)
        row.addWidget(self.sb_min)
        self.cb_skip_reparse = QCheckBox("Skip junctions / symlinks")
        self.cb_skip_reparse.setChecked(True)
        row.addWidget(self.cb_skip_reparse)
        self.btn_scan = QPushButton("Scan")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        row.addWidget(self.btn_scan)
        row.addWidget(self.btn_stop)
        lay.addLayout(row)
        self.btn_browse.clicked.connect(self._browse_root)
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_stop.clicked.connect(self.stop_scan)
        self.input_root.returnPressed.connect(self.start_scan)

    def _build_tree(self, lay):
        self.tree = CheckRangeTreeWidget()
        self.tree.set_check_column(LF_COL_CHK)
        self.tree.setHeaderLabels(["", "Size", "Path"])
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setSortingEnabled(False)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(LF_COL_CHK, QHeaderView.Fixed)
        hdr.setSectionResizeMode(LF_COL_SIZE, QHeaderView.Interactive)
        hdr.setSectionResizeMode(LF_COL_PATH, QHeaderView.Stretch)
        self.tree.setColumnWidth(LF_COL_CHK, 28)
        self.tree.setColumnWidth(LF_COL_SIZE, 110)
        self.tree.setStyleSheet(
            f"QTreeWidget::item {{ height: {ROW_HEIGHT_PX}px; }}"
        )
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        lay.addWidget(self.tree, 1)

    def _build_action_row(self, lay):
        row = QHBoxLayout()
        self.btn_check_all = QPushButton("Check all")
        self.btn_uncheck_all = QPushButton("Uncheck all")
        self.btn_open = QPushButton("Open in Explorer")
        self.btn_open.setEnabled(False)
        self.btn_recycle = QPushButton("Recycle checked")
        self.btn_recycle.setEnabled(False)
        row.addWidget(self.btn_check_all)
        row.addWidget(self.btn_uncheck_all)
        row.addSpacing(8)
        row.addWidget(self.btn_open)
        row.addStretch(1)
        row.addWidget(self.btn_recycle)
        lay.addLayout(row)
        self.btn_check_all.clicked.connect(lambda: self._bulk_check(Qt.Checked))
        self.btn_uncheck_all.clicked.connect(lambda: self._bulk_check(Qt.Unchecked))
        self.btn_open.clicked.connect(self._open_selected)
        self.btn_recycle.clicked.connect(self._recycle_checked)

    def _build_status(self, lay):
        row = QHBoxLayout()
        self.lbl_status = QLabel("Idle")
        self.lbl_summary = QLabel("")
        row.addWidget(self.lbl_status, 1)
        row.addWidget(self.lbl_summary)
        lay.addLayout(row)

    def _browse_root(self):
        start = self.input_root.text().strip() or os.path.expanduser("~")
        p = QFileDialog.getExistingDirectory(self, "Pick root folder", start)
        if p:
            self.input_root.setText(p)

    def start_scan(self):
        root = self.input_root.text().strip()
        if not root or not os.path.isdir(root):
            QMessageBox.information(
                self, "Pick a root",
                "Choose an existing folder to scan."
            )
            return
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(2000)
        self.tree.blockSignals(True)
        self.tree.clear()
        self.tree.blockSignals(False)
        self._items.clear()
        self.btn_recycle.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._scan_t0 = time.monotonic()
        self.lbl_status.setText(f"Scanning {root}...")
        self.lbl_summary.setText("")
        self._worker = LargestFilesScanWorker(
            root,
            top_n=self.sb_topn.value(),
            min_bytes=self.sb_min.value() * 1024 * 1024,
            skip_reparse=self.cb_skip_reparse.isChecked(),
            parent=self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.start()

    def stop_scan(self):
        if self._worker is not None:
            self._worker.request_stop()
            self.lbl_status.setText("Stopping scan...")

    def _on_progress(self, location: str, scanned: int):
        self.lbl_status.setText(
            f"Scanning... at {location}  ({scanned:,} files seen)"
        )

    def _on_finished(self, results: list, errors: int):
        dt = time.monotonic() - self._scan_t0
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.tree.blockSignals(True)
        try:
            for sz, path in results:
                item = QTreeWidgetItem(["", human_size(sz), path])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(LF_COL_CHK, Qt.Unchecked)
                item.setData(LF_COL_SIZE, Qt.UserRole, sz)
                item.setToolTip(LF_COL_PATH, path)
                item.setTextAlignment(
                    LF_COL_SIZE, Qt.AlignRight | Qt.AlignVCenter
                )
                self.tree.addTopLevelItem(item)
                self._items.append(item)
        finally:
            self.tree.blockSignals(False)
        total = sum(sz for sz, _ in results)
        msg = (f"Scan complete: {len(results):,} file(s), "
               f"{human_size(total)} total, in {dt:,.1f}s")
        if errors:
            msg += f"  ({errors:,} error(s))"
        self.lbl_status.setText(msg)
        self._update_summary()

    def _bulk_check(self, state):
        self.tree.blockSignals(True)
        try:
            for it in self._items:
                it.setCheckState(LF_COL_CHK, state)
        finally:
            self.tree.blockSignals(False)
        self._update_summary()

    def _on_item_changed(self, item, col):
        if col == LF_COL_CHK:
            self._update_summary()

    def _update_summary(self):
        n = 0
        total = 0
        for it in self._items:
            if it.checkState(LF_COL_CHK) == Qt.Checked:
                n += 1
                sz = it.data(LF_COL_SIZE, Qt.UserRole) or 0
                total += int(sz)
        self.lbl_summary.setText(f"{n:,} checked  -  {human_size(total)}")
        self.btn_recycle.setEnabled(n > 0)

    def _on_selection_changed(self):
        self.btn_open.setEnabled(bool(self.tree.selectedItems()))

    def _on_double_click(self, item, col):
        _reveal_in_explorer(item.text(LF_COL_PATH))

    def _open_selected(self):
        sel = self.tree.selectedItems()
        if not sel:
            return
        _reveal_in_explorer(sel[0].text(LF_COL_PATH))

    def _recycle_checked(self):
        targets = [it for it in self._items
                   if it.checkState(LF_COL_CHK) == Qt.Checked]
        if not targets:
            return
        total = sum(int(it.data(LF_COL_SIZE, Qt.UserRole) or 0)
                    for it in targets)
        if QMessageBox.question(
            self, "Recycle files",
            f"Send {len(targets):,} file(s) ({human_size(total)}) "
            "to the Recycle Bin?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        ok = fail = 0
        recycled = []
        for it in targets:
            if recycle([it.text(LF_COL_PATH)])[1]:
                fail += 1
            else:
                ok += 1
                recycled.append(it)
        self.tree.blockSignals(True)
        try:
            for it in recycled:
                idx = self.tree.indexOfTopLevelItem(it)
                if idx >= 0:
                    self.tree.takeTopLevelItem(idx)
            done = set(id(it) for it in recycled)
            self._items = [it for it in self._items if id(it) not in done]
        finally:
            self.tree.blockSignals(False)
        msg = f"Recycled {ok:,} file(s)"
        if fail:
            msg += f"; {fail:,} failed"
        self.lbl_status.setText(msg + ".")
        self._update_summary()

    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(2000)


# =======================================================================
# Custom-paths dialog
# =======================================================================

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def save_config(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


class CustomPathsDialog(QDialog):
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom paths")
        self.resize(640, 400)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Folders and files to scan as 'Custom paths':"))
        self.list = QListWidget()
        self.list.setAlternatingRowColors(False)
        self.list.setTextElideMode(Qt.ElideMiddle)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        for p in paths:
            QListWidgetItem(p, self.list)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        b_add_dir = QPushButton("Add folder...")
        b_add_file = QPushButton("Add file...")
        b_remove = QPushButton("Remove selected")
        row.addWidget(b_add_dir)
        row.addWidget(b_add_file)
        row.addWidget(b_remove)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        b_add_dir.clicked.connect(self._add_dir)
        b_add_file.clicked.connect(self._add_file)
        b_remove.clicked.connect(self._remove)

    def _add_dir(self):
        p = QFileDialog.getExistingDirectory(self, "Pick folder")
        if p and not self._has(p):
            QListWidgetItem(p, self.list)

    def _add_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "Pick file")
        if p and not self._has(p):
            QListWidgetItem(p, self.list)

    def _remove(self):
        for it in list(self.list.selectedItems()):
            self.list.takeItem(self.list.row(it))

    def _has(self, p):
        for i in range(self.list.count()):
            if self.list.item(i).text() == p:
                return True
        return False

    def paths(self):
        return [self.list.item(i).text() for i in range(self.list.count())]
