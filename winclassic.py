#!/usr/bin/env python3
# winclassic.py - the Classic rows of New PC: replay this PC's classic Windows
# setup from resource\winclassic, and Capture it again from this PC.

import ctypes
import ctypes.wintypes as wt
import filecmp
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import time
import winreg
from datetime import datetime
from pathlib import Path

import clean
import tweaks

INSTALLERS = {
    "explorerpatcher": "ep_setup.exe",
    "openshell": "openshell_setup.exe",
    "windhawk": "windhawk_setup_offline.exe",
    "taskbartweaker": "7tt_setup.exe",
    "marlett": "marlett.ttf",
}

# ExplorerPatcher ep_setup/ep_setup.c (raw.githubusercontent.com/valinet/
# ExplorerPatcher/master/ep_setup/ep_setup.c): /update_silent is an install
# without prompts that also sets IsUpdatePending, and setup restarts Explorer
# itself. It exits with GetLastError(), a non-zero value even on success, so
# the step is judged by the installed version instead of the exit code.
EP_ARGS = ["/update_silent"]
# Open-Shell Src/Setup/Setup.cpp (raw.githubusercontent.com/Open-Shell/
# Open-Shell-Menu/master/Src/Setup/Setup.cpp) passes the command line to
# msiexec, so /qn is msiexec's quiet mode; Src/Setup/Setup.wxs names the
# features, and StartMenu is the Start Menu alone. REBOOT=ReallySuppress
# (learn.microsoft.com/en-us/windows/win32/msi/reboot) keeps msiexec from
# restarting; 3010 and 1641 are its success-with-restart exit codes
# (learn.microsoft.com/en-us/windows/win32/msi/error-codes).
OPENSHELL_ARGS = ["/qn", "ADDLOCAL=StartMenu", "REBOOT=ReallySuppress"]
OPENSHELL_OK = (0, 3010, 1641)
# Windhawk's installer is NSIS (/S, nsis.sourceforge.io/Docs/Chapter3.html);
# its maintainer gives "windhawk_setup.exe /S /STANDARD" as the silent install
# (github.com/ramensoftware/windhawk/discussions/868): /STANDARD skips the
# standard-or-portable prompt that /S alone leaves open.
WINDHAWK_ARGS = ["/S", "/STANDARD"]
# 7tt_setup.exe is NSIS too (winget-pkgs lists InstallerType nullsoft), so /S
# is the NSIS silent switch (nsis.sourceforge.io/Docs/Chapter3.html).
TT_ARGS = ["/S"]
INSTALLER_TIMEOUT = 15 * 60
POWERSHELL_TIMEOUT = 60

EP_DIR = r"C:\Program Files\ExplorerPatcher"
# The uninstall entry's DisplayVersion is not rewritten by every update (one
# PC showed 22621.3880.66.6 over 22631.5335.68.2 files), so the version is
# read from the DLL itself.
EP_DLL = "ExplorerPatcher.amd64.dll"
DEFENDER_ADD = f"Add-MpPreference -ExclusionPath '{EP_DIR}'"
DEFENDER_GET = "(Get-MpPreference).ExclusionPath"
WINDHAWK_SERVICE = "Windhawk"

HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
TYPE_NAMES = {
    winreg.REG_NONE: "NONE", winreg.REG_SZ: "SZ", winreg.REG_EXPAND_SZ: "EXPAND_SZ",
    winreg.REG_BINARY: "BINARY", winreg.REG_DWORD: "DWORD",
    winreg.REG_MULTI_SZ: "MULTI_SZ", winreg.REG_QWORD: "QWORD",
}
TYPE_IDS = {name: typ for typ, name in TYPE_NAMES.items()}
WM_FONTCHANGE = 0x001D

ADVANCED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
FONTS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
NT_VERSION = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
COMPUTER_NAME = r"SYSTEM\CurrentControlSet\Control\ComputerName\ActiveComputerName"
DEFAULT_COLORS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\DefaultColors"
MARLETT_VALUE = ("HKCU", FONTS_KEY, "Marlett (TrueType)")
CLSID_86CA = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}"
CLSID_1EEB = r"Software\Classes\CLSID\{1eeb5b5a-06fb-4732-96b3-975c0194eb39}"

WM_METRICS = r"Control Panel\Desktop\WindowMetrics"

_shell32 = ctypes.WinDLL("shell32")
_shell32.IsUserAnAdmin.restype = wt.BOOL
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_gdi32.AddFontResourceW.restype = ctypes.c_int
_gdi32.AddFontResourceW.argtypes = [wt.LPCWSTR]
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
_user32.SendMessageTimeoutW.argtypes = [
    wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
    ctypes.POINTER(ctypes.c_size_t)]
_version = ctypes.WinDLL("version", use_last_error=True)
_version.GetFileVersionInfoSizeW.restype = wt.DWORD
_version.GetFileVersionInfoSizeW.argtypes = [wt.LPCWSTR, ctypes.POINTER(wt.DWORD)]
_version.GetFileVersionInfoW.restype = wt.BOOL
_version.GetFileVersionInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p]
_version.VerQueryValueW.restype = wt.BOOL
_version.VerQueryValueW.argtypes = [ctypes.c_void_p, wt.LPCWSTR,
                                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.UINT)]


# --------------------------------------------------------------------
#  the package folder
# --------------------------------------------------------------------

def package_dir():
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    path = base / "resource" / "winclassic"
    if not path.is_dir():
        raise FileNotFoundError(f"missing {path}")
    return path


def package_path(*parts):
    path = package_dir().joinpath(*parts)
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    return path


def windhawk_data():
    return Path(os.environ["ProgramData"]) / "Windhawk"


def fonts_dir():
    return Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"


def ep_dir():
    return Path(EP_DIR)


def backup_root():
    # next to the Registry Cleaner's backups
    return clean.REG_BACKUP_DIR


# --------------------------------------------------------------------
#  the registry (the tests swap in a dict-backed copy of WinReg)
# --------------------------------------------------------------------

def _plain(typ, data):
    # winreg hands back None for an empty BINARY or NONE value
    if typ in (winreg.REG_BINARY, winreg.REG_NONE) and data is None:
        return b""
    return data


class WinReg:
    # the 64-bit view; values are (name, type name, data), data bytes for BINARY and NONE

    def _open(self, hive, path, access=winreg.KEY_READ):
        return winreg.OpenKey(HIVES[hive], path, 0, access | winreg.KEY_WOW64_64KEY)

    def exists(self, hive, path):
        try:
            self._open(hive, path).Close()
        except FileNotFoundError:
            return False
        return True

    def values(self, hive, path):
        out = []
        with self._open(hive, path) as k:
            for i in range(winreg.QueryInfoKey(k)[1]):
                name, data, typ = winreg.EnumValue(k, i)
                out.append((name, TYPE_NAMES.get(typ, f"TYPE_{typ}"), _plain(typ, data)))
        return out

    def subkeys(self, hive, path):
        with self._open(hive, path) as k:
            return [winreg.EnumKey(k, i) for i in range(winreg.QueryInfoKey(k)[0])]

    def get(self, hive, path, name):
        with self._open(hive, path) as k:
            data, typ = winreg.QueryValueEx(k, name)
        return TYPE_NAMES.get(typ, f"TYPE_{typ}"), _plain(typ, data)

    def set(self, hive, path, name, typ, data):
        with winreg.CreateKeyEx(HIVES[hive], path, 0,
                                winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as k:
            winreg.SetValueEx(k, name, 0, TYPE_IDS[typ], data)

    def create_key(self, hive, path):
        winreg.CreateKeyEx(HIVES[hive], path, 0,
                           winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY).Close()

    def delete_tree(self, hive, path):
        for sub in self.subkeys(hive, path):
            self.delete_tree(hive, f"{path}\\{sub}")
        winreg.DeleteKeyEx(HIVES[hive], path, winreg.KEY_WOW64_64KEY, 0)


REG = WinReg()


def encode_value(typ, data):
    if typ in ("DWORD", "QWORD"):
        return int(data)
    if typ in ("SZ", "EXPAND_SZ"):
        return str(data)
    if typ == "MULTI_SZ":
        return [str(s) for s in data]
    return bytes(data).hex()


def decode_value(typ, data):
    if typ in ("BINARY", "NONE"):
        return bytes.fromhex(data)
    return data


def record(hive, path, name, typ, data):
    if typ not in TYPE_IDS:
        raise ValueError(
            f"unsupported registry type {typ} at {hive}\\{path}\\{name or '(Default)'}")
    return {"hive": hive, "path": path, "name": name, "type": typ,
            "data": encode_value(typ, data)}


def write_records(records):
    for r in records:
        REG.set(r["hive"], r["path"], r["name"], r["type"], decode_value(r["type"], r["data"]))


def records_match(records):
    for r in records:
        try:
            live = REG.get(r["hive"], r["path"], r["name"])
        except FileNotFoundError:
            return False
        if live != (r["type"], decode_value(r["type"], r["data"])):
            return False
    return True


# --------------------------------------------------------------------
#  what Capture reads
# --------------------------------------------------------------------

class Tree:
    # root=False leaves out the values of the root key; skip_keys (paths below
    # the root) go with everything under them and skip_values are root value
    # names; only_named keeps just the keys with those names and everything
    # below them

    def __init__(self, hive, path, root=True, skip_keys=(), skip_values=(), only_named=None):
        self.hive = hive
        self.path = path
        self.root = root
        self.skip_keys = {k.lower() for k in skip_keys}
        self.skip_values = {v.lower() for v in skip_values}
        self.only_named = None if only_named is None else {n.lower() for n in only_named}

    def records(self):
        if not REG.exists(self.hive, self.path):
            raise FileNotFoundError(f"missing {self.hive}\\{self.path}")
        out = []

        def walk(rel, kept):
            key = f"{self.path}\\{rel}" if rel else self.path
            leaf = rel.rsplit("\\", 1)[-1].lower()
            if self.only_named is not None and rel and leaf in self.only_named:
                kept = True
            if kept and (rel or self.root):
                for name, typ, data in REG.values(self.hive, key):
                    if rel or name.lower() not in self.skip_values:
                        out.append(record(self.hive, key, name, typ, data))
            for sub in REG.subkeys(self.hive, key):
                child = f"{rel}\\{sub}" if rel else sub
                if child.lower() not in self.skip_keys:
                    walk(child, kept)

        walk("", self.only_named is None)
        return out


class Values:
    # named values of one key; "" is its default value

    def __init__(self, hive, path, names):
        self.hive = hive
        self.path = path
        self.names = names

    def records(self):
        out = []
        for name in self.names:
            try:
                typ, data = REG.get(self.hive, self.path, name)
            except FileNotFoundError:
                raise FileNotFoundError(
                    f"missing {self.hive}\\{self.path}\\{name or '(Default)'}") from None
            out.append(record(self.hive, self.path, name, typ, data))
        return out


# Left out of ExplorerPatcher: the explorer and twinui.pcshell symbol caches
# (per Windows build, rewritten at runtime), CrashCounter and
# SymbolsLastNotifiedOSBuild (runtime counters), LastSectionInProperties (UI
# state, changes whenever Properties is browsed). Left out of Open-Shell:
# everything outside the Settings keys (MRU, ItemRanks, Order, window and
# timestamp values rewritten while the menu is used). Left out of 7+ Taskbar
# Tweaker: install_dir and MementoSection_* (written by its installer),
# inspector_w/h (window size), updchecktime (timestamp). Left out of the
# appearance: AppliedDPI (follows the display scaling).
PLAN = {
    "explorerpatcher": (
        Tree("HKCU", r"Software\ExplorerPatcher", skip_keys=("explorer", "twinui.pcshell"),
             skip_values=("CrashCounter", "LastSectionInProperties",
                          "SymbolsLastNotifiedOSBuild")),
        Values("HKCU", ADVANCED, ("TaskbarAl", "TaskbarSmallIcons", "TaskbarSD",
                                  "TaskbarGlomLevel", "MMTaskbarGlomLevel",
                                  "Start_ShowClassicMode")),
        Values("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\ImmersiveShell",
               ("UseWin32BatteryFlyout",)),
        Values("HKCU", CLSID_86CA + r"\InprocServer32", ("",)),
        Values("HKCU", CLSID_1EEB + r"\InprocServer32", ("",)),
    ),
    "openshell": (
        Tree("HKCU", r"Software\OpenShell", root=False, only_named=("Settings",)),
    ),
    "taskbartweaker": (
        Tree("HKCU", r"Software\7 Taskbar Tweaker", root=False),
        Values("HKCU", r"Software\7 Taskbar Tweaker",
               ("language", "hidetray", "lefttrayfunc", "updcheck", "updcheckauto",
                "nounsupportedwarning_w11")),
        Values("HKCU", RUN, ("7 Taskbar Tweaker",)),
    ),
    "appearance": (
        Tree("HKCU", r"Control Panel\Colors"),
        Tree("HKCU", WM_METRICS, skip_values=("AppliedDPI",)),
        Tree("HKCU", r"Control Panel\Appearance"),
        Values(*MARLETT_VALUE[:2], (MARLETT_VALUE[2],)),
    ),
}
# Engine\ModsWritable holds the mods' per-build symbol caches and the WinSxS
# path of this build's comctl32.
WINDHAWK_TREE = Tree("HKLM", r"SOFTWARE\Windhawk", skip_keys=(r"Engine\ModsWritable",))
WINDHAWK_MODS = WINDHAWK_TREE.path + r"\Engine\Mods"
ARCH_DIRS = {"x86-64": "64", "amd64": "64", "x86": "32"}
# a mod without @architecture is built for x86 and x86-64
# (github.com/ramensoftware/windhawk/wiki/Creating-a-new-mod)
DEFAULT_ARCHS = ("32", "64")

LABELS = {"explorerpatcher": "ExplorerPatcher", "openshell": "Open-Shell",
          "windhawk": "Windhawk", "taskbartweaker": "7+ Taskbar Tweaker"}
UNINSTALL_NAMES = {
    "explorerpatcher": r"ExplorerPatcher$",
    "openshell": r"Open-Shell$",
    "windhawk": r"Windhawk( v[\d.]+)?$",
    "taskbartweaker": r"7\+ Taskbar Tweaker( v[\d.]+)?$",
}


class VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [("dwSignature", wt.DWORD), ("dwStrucVersion", wt.DWORD),
                ("dwFileVersionMS", wt.DWORD), ("dwFileVersionLS", wt.DWORD)]


def file_version(path):
    # "a.b.c.d" from the file's version resource, None when the file is missing
    if not os.path.isfile(path):
        return None
    size = _version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        raise ctypes.WinError(ctypes.get_last_error())
    buf = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(str(path), 0, size, buf):
        raise ctypes.WinError(ctypes.get_last_error())
    ptr, n = ctypes.c_void_p(), wt.UINT()
    if not _version.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(n)) or not n.value:
        raise OSError(f"no version in {path}")
    info = VS_FIXEDFILEINFO.from_address(ptr.value)
    ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def installed_versions():
    entries = clean.enumerate_uninstall_entries()
    out = {}
    for comp, pattern in UNINSTALL_NAMES.items():
        found = next((e for e in entries if re.match(pattern, e.display_name)), None)
        out[comp] = (found.display_version or None) if found else None
    out["explorerpatcher"] = file_version(ep_dir() / EP_DLL)
    return out


def version_key(version):
    return tuple(int(n) for n in re.findall(r"\d+", version))


def at_least(installed, wanted):
    # the installed version is the captured one or newer
    return installed is not None and version_key(installed) >= version_key(wanted)


def current_build():
    return REG.get("HKLM", NT_VERSION, "CurrentBuild")[1]


def current_ubr():
    return REG.get("HKLM", NT_VERSION, "UBR")[1]


def computer_name():
    return REG.get("HKLM", COMPUTER_NAME, "ComputerName")[1]


def applied_dpi():
    try:
        return REG.get("HKCU", WM_METRICS, "AppliedDPI")[1]
    except FileNotFoundError:
        raise FileNotFoundError(f"missing HKCU\\{WM_METRICS}\\AppliedDPI") from None


def build_manifest():
    versions = installed_versions()
    for comp, version in versions.items():
        if version is None:
            raise OSError(f"{LABELS[comp]} not installed")
    return {"captured": datetime.now().astimezone().isoformat(timespec="seconds"),
            "computer": computer_name(), "build": current_build(), "ubr": current_ubr(),
            "dpi": applied_dpi(), "versions": versions}


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8")


def mod_archs(mod, arch):
    # the Engine\Mods subfolders a mod's DLL is built into
    try:
        return [ARCH_DIRS[a] for a in arch.split("|")] if arch else list(DEFAULT_ARCHS)
    except KeyError as e:
        raise ValueError(f"unknown architecture {e.args[0]} for {mod}") from None


def _capture_windhawk(dest):
    write_json(dest / "windhawk.json", sorted(
        WINDHAWK_TREE.records(), key=lambda r: (r["path"].lower(), r["name"].lower())))
    data = windhawk_data()
    mods_dir = data / "Engine" / "Mods"
    (dest / "Engine" / "Mods").mkdir(parents=True)
    (dest / "ModsSource").mkdir()
    for mod in REG.subkeys("HKLM", WINDHAWK_MODS):
        key = f"{WINDHAWK_MODS}\\{mod}"
        dll = REG.get("HKLM", key, "LibraryFileName")[1]
        for sub in mod_archs(mod, REG.get("HKLM", key, "Architecture")[1]):
            src = mods_dir / sub / dll
            if not src.is_file():
                raise FileNotFoundError(f"missing {src} for {mod}")
            (dest / "Engine" / "Mods" / sub).mkdir(exist_ok=True)
            shutil.copy2(src, dest / "Engine" / "Mods" / sub / dll)
        source = data / "ModsSource" / f"{mod}.wh.cpp"
        if not source.is_file():
            raise FileNotFoundError(f"missing {source} for {mod}")
        shutil.copy2(source, dest / "ModsSource" / source.name)


def _rename(src, dst):
    # Dropbox or a scanner can hold a just-written folder for a moment, and
    # Windows then refuses to rename it
    for pause in (0.2, 0.5, 1, 2):
        try:
            src.rename(dst)
            return
        except PermissionError:
            time.sleep(pause)
    src.rename(dst)


def _discard(path):
    # the same hold shows up as a folder that stays after its files are gone;
    # one that still stays is left for the next capture to clear
    for pause in (0.2, 0.5, 1):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(pause)
    shutil.rmtree(path, ignore_errors=True)


def capture():
    # returns the number of components written; a failure leaves the previous capture in place
    pkg = package_dir()
    final, fresh, old = pkg / "capture", pkg / "capture.new", pkg / "capture.old"
    if old.exists():  # a swap that died half way
        if final.exists():
            _discard(old)
        else:
            old.rename(final)
    shutil.rmtree(fresh, ignore_errors=True)
    fresh.mkdir()
    try:
        for name, sources in PLAN.items():
            write_json(fresh / f"{name}.json", sorted(
                (r for s in sources for r in s.records()),
                key=lambda r: (r["hive"], r["path"].lower(), r["name"].lower())))
        _capture_windhawk(fresh / "windhawk")
        write_json(fresh / "manifest.json", build_manifest())
        count = sum(1 for _ in fresh.iterdir())
    except BaseException:
        shutil.rmtree(fresh, ignore_errors=True)
        raise
    try:
        if final.exists():
            _rename(final, old)
        try:
            _rename(fresh, final)
        except OSError:
            if old.exists():
                _rename(old, final)
            raise
    except OSError:
        shutil.rmtree(fresh, ignore_errors=True)
        raise
    _discard(old)
    return count


# --------------------------------------------------------------------
#  side effects, each behind one function so the tests can replace it
# --------------------------------------------------------------------

def is_admin():
    return bool(_shell32.IsUserAnAdmin())


def run_installer(path, args, ok=(0,)):
    # returns the exit code; ok=None accepts any code
    try:
        r = subprocess.run([str(path), *args], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=tweaks.CREATE_NO_WINDOW,
                           timeout=INSTALLER_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise OSError(f"{Path(path).name} timed out") from None
    if ok is not None and r.returncode not in ok:
        raise OSError(f"{Path(path).name} exit {r.returncode}")
    return r.returncode


def run_powershell(script):
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "$ErrorActionPreference = 'Stop'; "
             "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, creationflags=tweaks.CREATE_NO_WINDOW,
            timeout=POWERSHELL_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise OSError("powershell timed out") from None
    if r.returncode:
        lines = [ln.strip() for ln in r.stderr.splitlines() if ln.strip()]
        raise OSError(lines[0] if lines else f"powershell exit {r.returncode}")
    return r.stdout


def set_service(name, running):
    run_powershell(f"{'Start' if running else 'Stop'}-Service -Name '{name}'")


def load_font(path):
    if not _gdi32.AddFontResourceW(str(path)):
        raise ctypes.WinError(ctypes.get_last_error())
    _user32.SendMessageTimeoutW(tweaks.HWND_BROADCAST, WM_FONTCHANGE, 0, 0,
                                tweaks.SMTO_ABORTIFHUNG, 1000,
                                ctypes.byref(ctypes.c_size_t()))


# --------------------------------------------------------------------
#  the rows
# --------------------------------------------------------------------

# The rows of one refresh share one uninstall enumeration and one
# Get-MpPreference; InitConfigPage.refresh_states clears these first.
@functools.cache
def _versions():
    return installed_versions()


@functools.cache
def _exclusions():
    return run_powershell(DEFENDER_GET)


def clear_cache():
    _versions.cache_clear()
    _exclusions.cache_clear()


def load_records(*parts):
    return json.loads(package_path("capture", *parts).read_text(encoding="utf-8"))


def load_manifest():
    return load_records("manifest.json")


# (manifest "captured" stamp, reasons) the user agreed to apply despite;
# initcfg sets it for one New PC run after asking, and clears it afterwards
_accepted = [None]


def capture_mismatch(man=None):
    # why the capture may not suit this PC: it came from another PC, or from
    # another update of this build (the 2026-10-14 capture from a 22631.4249
    # PC pointed a 22631.3958 PC's Windhawk mods at DLLs that never loaded)
    man = load_manifest() if man is None else man
    reasons = []
    here, there = computer_name(), man.get("computer")
    if not there:
        reasons.append("capture does not name its PC")
    elif there.lower() != here.lower():
        reasons.append(f"captured on {there}, this is {here}")
    ubr = current_ubr()
    if ubr != man.get("ubr"):
        reasons.append(f"UBR {ubr}, capture is {man.get('ubr')}")
    return reasons


def accept_mismatch(reasons):
    # reasons from capture_mismatch the user confirmed, or None to accept nothing
    _accepted[0] = None if reasons is None else (load_manifest()["captured"], tuple(reasons))


def preflight():
    # the captured manifest, once this process is elevated, the build matches
    # it and it came from this PC (or the user accepted that it did not)
    if not is_admin():
        raise OSError("not elevated")
    man = load_manifest()
    running = current_build()
    if running != man["build"]:
        raise OSError(f"build {running}, capture is {man['build']}")
    reasons = capture_mismatch(man)
    if reasons and _accepted[0] != (man["captured"], tuple(reasons)):
        raise OSError("; ".join(reasons) + " (not confirmed)")
    return man


def export_key(hive, path, dest):
    ok, msg = clean.reg_export(hive, path, str(dest))
    if not ok:
        raise OSError(f"backup of {hive}\\{path} failed: {msg}")


def top_keys(records):
    # the keys the records write to, without those inside another of them
    out = []
    for hive, path in sorted({(r["hive"], r["path"]) for r in records},
                             key=lambda k: (k[0], k[1].lower())):
        low = path.lower()
        if not any(h == hive and (low == p.lower() or low.startswith(p.lower() + "\\"))
                   for h, p in out):
            out.append((hive, path))
    return out


def backup(key, keys, paths=()):
    # a .reg export of every key and a copy of every file or folder the step
    # may change, taken before it changes anything; returns the folder
    dest = backup_root() / f"winclassic_{key}_{datetime.now():%Y%m%d_%H%M%S}"
    dest.mkdir(parents=True, exist_ok=True)
    for hive, path in keys:
        if REG.exists(hive, path):
            name = clean._safe_filename(f"{hive}__{path.replace(chr(92), '__')}")
            export_key(hive, path, dest / f"{name}.reg")
    for p in map(Path, paths):
        if p.is_dir():
            shutil.copytree(p, dest / "files" / p.name, dirs_exist_ok=True)
        elif p.is_file():
            (dest / "files").mkdir(exist_ok=True)
            shutil.copy2(p, dest / "files" / p.name)
    return dest


def _needs_install(comp, man):
    # an installer never runs over the captured version or a newer one
    return not at_least(installed_versions()[comp], man["versions"][comp])


def _copy_changed(src, dst):
    # a loaded DLL cannot be overwritten, and the same bytes need no copy
    if not (os.path.isfile(dst) and filecmp.cmp(src, dst, shallow=False)):
        shutil.copy2(src, dst)


def _same_tree(src, dst, skip=frozenset()):
    for p in src.rglob("*"):
        if p.is_file() and p not in skip:
            there = dst / p.relative_to(src)
            if not (there.is_file() and filecmp.cmp(p, there, shallow=False)):
                return False
    return True


def _apply_defender():
    preflight()
    run_powershell(DEFENDER_ADD)


def _state_defender():
    lines = [ln.strip() for ln in _exclusions().splitlines() if ln.strip()]
    if any(ln.startswith("N/A") for ln in lines):
        return None
    return any(ln.rstrip("\\").lower() == EP_DIR.lower() for ln in lines)


def _apply_explorerpatcher():
    man = preflight()
    installer = package_path("installers", INSTALLERS["explorerpatcher"])
    records = load_records("explorerpatcher.json")
    install = _needs_install("explorerpatcher", man)
    backup("explorerpatcher", top_keys(records), [ep_dir()] if install else ())
    if install:
        code = run_installer(installer, EP_ARGS, ok=None)
        if not at_least(installed_versions()["explorerpatcher"],
                        man["versions"]["explorerpatcher"]):
            raise OSError(f"{installer.name} exit {code}")
    write_records(records)


def _apply_component(comp, args, captured, ok=(0,)):
    man = preflight()
    installer = package_path("installers", INSTALLERS[comp])
    records = load_records(captured)
    backup(comp, top_keys(records))
    if _needs_install(comp, man):
        run_installer(installer, args, ok)
    write_records(records)


def _version_ok(comp):
    return at_least(_versions()[comp], load_manifest()["versions"][comp])


def _state_component(comp, captured):
    return _version_ok(comp) and records_match(load_records(captured))


class ModConflict(OSError):
    # a mod built here from a source that differs from the capture's
    pass


def _local_build(mod):
    # this PC's LibraryFileName for the mod, when all its DLLs are here
    key = f"{WINDHAWK_MODS}\\{mod}"
    try:
        dll = REG.get("HKLM", key, "LibraryFileName")[1]
        arch = REG.get("HKLM", key, "Architecture")[1]
    except FileNotFoundError:
        return None
    mods_dir = windhawk_data() / "Engine" / "Mods"
    if dll and all((mods_dir / sub / dll).is_file() for sub in mod_archs(mod, arch)):
        return dll
    return None


def _windhawk_plan():
    # (records to write, capture files to leave out). Windhawk compiles a mod
    # on the PC it runs on, and a DLL built elsewhere may never load here, so
    # a mod this PC already built from the same source keeps its own DLL and
    # LibraryFileName; only a mod with no build here gets the captured one.
    records = load_records("windhawk", "windhawk.json")
    source = package_path("capture", "windhawk")
    prefix = WINDHAWK_MODS.lower() + "\\"
    captured = {}
    for r in records:
        low = r["path"].lower()
        if low.startswith(prefix) and "\\" not in low[len(prefix):]:
            captured.setdefault(r["path"][len(prefix):], {})[r["name"].lower()] = r["data"]
    kept, skip = set(), set()
    for mod, vals in captured.items():
        if _local_build(mod) is None:
            continue
        here = windhawk_data() / "ModsSource" / f"{mod}.wh.cpp"
        theirs = source / "ModsSource" / f"{mod}.wh.cpp"
        if not (here.is_file() and theirs.is_file()
                and filecmp.cmp(theirs, here, shallow=False)):
            raise ModConflict(f"{mod} is built here from another source than the capture's")
        kept.add(mod.lower())
        dll = vals.get("libraryfilename")
        if dll:
            for sub in mod_archs(mod, vals.get("architecture")):
                skip.add(source / "Engine" / "Mods" / sub / dll)
    out = [r for r in records
           if not (r["name"].lower() == "libraryfilename"
                   and r["path"].lower().startswith(prefix)
                   and r["path"].lower()[len(prefix):] in kept)]
    return out, skip


def _apply_windhawk():
    man = preflight()
    installer = package_path("installers", INSTALLERS["windhawk"])
    source = package_path("capture", "windhawk")
    records, skip = _windhawk_plan()
    data = windhawk_data()
    backup("windhawk", [("HKLM", WINDHAWK_TREE.path)],
           [data / "Engine", data / "ModsSource"])
    if _needs_install("windhawk", man):
        run_installer(installer, WINDHAWK_ARGS)
    set_service(WINDHAWK_SERVICE, False)
    try:
        for sub in ("Engine", "ModsSource"):
            shutil.copytree(source / sub, data / sub, dirs_exist_ok=True,
                            copy_function=_copy_changed,
                            ignore=lambda d, names: [n for n in names if Path(d, n) in skip])
        write_records(records)
    finally:
        set_service(WINDHAWK_SERVICE, True)


def _state_windhawk():
    source = package_path("capture", "windhawk")
    try:
        records, skip = _windhawk_plan()
    except ModConflict:  # off, and apply says why it leaves it
        return False
    return (_version_ok("windhawk") and records_match(records)
            and all(_same_tree(source / sub, windhawk_data() / sub, skip)
                    for sub in ("Engine", "ModsSource")))


def _marlett():
    return fonts_dir() / INSTALLERS["marlett"]


def _appearance_records():
    out = []
    for r in load_records("appearance.json"):
        if (r["hive"], r["path"], r["name"]) == MARLETT_VALUE:
            # the captured path names the profile of the PC it came from
            r = dict(r, data=str(_marlett()))
        out.append(r)
    return out


def _copy_tree(hive, src, dst):
    REG.create_key(hive, dst)
    for name, typ, data in REG.values(hive, src):
        REG.set(hive, dst, name, typ, data)
    for sub in REG.subkeys(hive, src):
        _copy_tree(hive, f"{src}\\{sub}", f"{dst}\\{sub}")


def _rename_default_colors():
    if not REG.exists("HKLM", DEFAULT_COLORS):  # renamed already
        return
    backup = DEFAULT_COLORS + ".bak"
    if REG.exists("HKLM", backup):
        REG.delete_tree("HKLM", backup)
    _copy_tree("HKLM", DEFAULT_COLORS, backup)
    REG.delete_tree("HKLM", DEFAULT_COLORS)


def _apply_appearance():
    man = preflight()
    running = applied_dpi()
    if running != man["dpi"]:
        raise OSError(f"DPI {running}, capture is {man['dpi']}")
    records = _appearance_records()
    font_src = package_path("installers", INSTALLERS["marlett"])
    font = _marlett()
    backup("classicappearance",
           [*top_keys(records), ("HKLM", DEFAULT_COLORS), ("HKLM", DEFAULT_COLORS + ".bak")],
           [font])
    font.parent.mkdir(parents=True, exist_ok=True)
    _copy_changed(font_src, font)
    write_records(records)
    load_font(font)
    _rename_default_colors()


def _state_appearance():
    font = _marlett()
    return (records_match(_appearance_records()) and os.path.isfile(font)
            and filecmp.cmp(package_path("installers", INSTALLERS["marlett"]), font,
                            shallow=False)
            and not REG.exists("HKLM", DEFAULT_COLORS))


class Step:
    # the same duck type as tweaks.Tweak, for what initcfg needs of a row
    section = "Classic"

    def __init__(self, key, label, apply, state):
        self.key = key
        self.label = label
        self._apply = apply
        self._state = state

    def state(self):
        try:
            return self._state()
        except (OSError, ValueError):  # a missing or unreadable capture reads n/a
            return None

    def apply(self, on):
        if not on:
            raise NotImplementedError(self.key)
        self._apply()
        return 0


STEPS = (
    Step("defenderep", "ExplorerPatcher Defender Exclusion", _apply_defender, _state_defender),
    Step("explorerpatcher", "ExplorerPatcher", _apply_explorerpatcher,
         functools.partial(_state_component, "explorerpatcher", "explorerpatcher.json")),
    Step("openshell", "Open-Shell",
         functools.partial(_apply_component, "openshell", OPENSHELL_ARGS,
                           "openshell.json", OPENSHELL_OK),
         functools.partial(_state_component, "openshell", "openshell.json")),
    Step("windhawk", "Windhawk", _apply_windhawk, _state_windhawk),
    Step("taskbartweaker", "7+ Taskbar Tweaker",
         functools.partial(_apply_component, "taskbartweaker", TT_ARGS, "taskbartweaker.json"),
         functools.partial(_state_component, "taskbartweaker", "taskbartweaker.json")),
    Step("classicappearance", "Classic Appearance", _apply_appearance, _state_appearance),
)
