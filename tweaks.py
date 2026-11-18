#!/usr/bin/env python3
"""tweaks.py - registry/service tweak catalog for wintools."""

import ctypes
import ctypes.wintypes as wt
import errno
import functools
import json
import os
import struct
import subprocess
import tempfile
import uuid
import winreg
import xml.etree.ElementTree as ET
import zlib

import filterkeys

CREATE_NO_WINDOW = 0x08000000

HKCU = winreg.HKEY_CURRENT_USER
HKLM = winreg.HKEY_LOCAL_MACHINE

DELETE = "<delete-value>"
DELETE_KEY = "<delete-key>"
UNKNOWN = "<unreadable>"

ADVANCED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
EXPLORER = r"Software\Microsoft\Windows\CurrentVersion\Explorer"
CDM = r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
POL = r"SOFTWARE\Policies\Microsoft\Windows"
SEARCH = r"Software\Microsoft\Windows\CurrentVersion\Search"
DESKTOP = r"Control Panel\Desktop"
SYS_POL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
DWM = r"Software\Microsoft\Windows\DWM"
HIDE_ICONS = EXPLORER + r"\HideDesktopIcons\NewStartPanel"


class RegOp:
    __slots__ = ("hive", "path", "name", "kind", "on", "off", "create", "off_key")

    def __init__(self, hive, path, name, on, off,
                 kind=winreg.REG_DWORD, create=True, off_key=None):
        self.hive = hive
        self.path = path
        self.name = name
        self.on = on
        self.off = off
        self.kind = kind
        self.create = create
        self.off_key = off_key

    def _open(self, access):
        return winreg.OpenKey(self.hive, self.path, 0, access | winreg.KEY_WOW64_64KEY)

    def available(self):
        # create=False marks a key we must never fabricate (a service key, a
        # vendor key) - the tweak is simply not applicable on this machine.
        # A key we may not read is NOT absent, so it stays available and
        # read() reports UNKNOWN instead.
        if self.create:
            return True
        try:
            self._open(winreg.KEY_READ).Close()
            return True
        except FileNotFoundError:
            return False
        except PermissionError:
            return True

    def read(self):
        try:
            with self._open(winreg.KEY_READ) as k:
                return winreg.QueryValueEx(k, self.name)[0]
        except FileNotFoundError:
            return None
        except PermissionError:
            return UNKNOWN

    def is_on(self):
        return self.read() == self.on

    def write(self, on):
        val = self.on if on else self.off
        if val is DELETE:
            self._del_value()
        elif val is DELETE_KEY:
            _delete_tree(self.hive, self.off_key or self.path)
        else:
            with winreg.CreateKeyEx(
                self.hive, self.path, 0,
                winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
            ) as k:
                winreg.SetValueEx(k, self.name, 0, self.kind, val)

    def _del_value(self):
        try:
            with self._open(winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, self.name)
        except FileNotFoundError:
            pass


def _delete_tree(hive, path):
    try:
        k = winreg.OpenKey(hive, path, 0,
                           winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except FileNotFoundError:
        return
    with k:
        while True:
            try:
                _delete_tree(hive, path + "\\" + winreg.EnumKey(k, 0))
            except OSError:
                break
    winreg.DeleteKeyEx(hive, path, winreg.KEY_WOW64_64KEY, 0)


def D(hive, path, name, on, off, create=True, off_key=None):
    return RegOp(hive, path, name, on, off, winreg.REG_DWORD, create, off_key)


def S(hive, path, name, on, off, create=True, off_key=None):
    return RegOp(hive, path, name, on, off, winreg.REG_SZ, create, off_key)


def X(hive, path, name, on, off, create=True):
    return RegOp(hive, path, name, on, off, winreg.REG_EXPAND_SZ, create)


def B(hive, path, name, on, off, create=True):
    return RegOp(hive, path, name, on, off, winreg.REG_BINARY, create)


def SVC(name, off=3):
    """Service start type: 4 = disabled, 3 = manual, 2 = automatic."""
    return D(HKLM, rf"SYSTEM\CurrentControlSet\Services\{name}", "Start",
             4, off, create=False)


class FilterKeysOp:
    """FilterKeys lives in a live SPI setting as well as the registry, so a
    registry-only write would not take effect until the next sign-in.  Same
    duck type as RegOp; SystemParametersInfoW persists the registry side."""

    on = True
    off = False
    off_key = None
    path = "SPI_SETFILTERKEYS"

    def available(self):
        return True

    def read(self):
        return filterkeys.is_removed()

    def is_on(self):
        return self.read()

    def write(self, on):
        filterkeys.set_removed(on)


LOCK_BLACK = os.path.join(os.environ["ProgramData"], "wintools",
                          "lockscreen-black.png")
LOCK_DEFAULT = os.path.join(os.environ["SystemRoot"], r"Web\Screen\img100.jpg")
LOCK_USER = r"Software\Microsoft\Windows\CurrentVersion\Lock Screen"
LOCK_PREV = S(HKCU, r"Software\wintools", "LockScreenPrevious", None, DELETE)

# Same WinRT call the Settings app makes; prints the picture it replaces.
_LOCK_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.System.UserProfile.LockScreen, Windows.System.UserProfile, ContentType = WindowsRuntime]
$prev = [Windows.System.UserProfile.LockScreen]::OriginalImageFile
if ($prev) { $prev.LocalPath }
$ext = [System.WindowsRuntimeSystemExtensions].GetMethods()
$asOp = ($ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asAct = ($ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
$f = $asOp.MakeGenericMethod([Windows.Storage.StorageFile]).Invoke($null, @([Windows.Storage.StorageFile]::GetFileFromPathAsync('%s')))
$f.Wait(-1) | Out-Null
$a = $asAct.Invoke($null, @([Windows.System.UserProfile.LockScreen]::SetImageFileAsync($f.Result)))
$a.Wait(-1) | Out-Null
"""


def write_black_png(path, w=1920, h=1080):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))
    raw = (b"\0" + b"\0\0\0" * w) * h
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def set_lock_image(path):
    """Returns the path of the picture it replaced ('' when none)."""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         _LOCK_PS % path.replace("'", "''")],
        capture_output=True, text=True, encoding="utf-8",
        creationflags=CREATE_NO_WINDOW, check=False)
    if r.returncode:
        raise OSError(r.stderr.strip() or f"powershell exit {r.returncode}")
    return r.stdout.strip()


@functools.cache
def _user_sid():
    r = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                       capture_output=True, text=True, check=True,
                       creationflags=CREATE_NO_WINDOW)
    return r.stdout.strip().split(",")[1].strip('"')


class BlackLockScreenOp:
    """Lock screen picture (which the sign-in screen reuses) set to a black
    image. The active cache slot is the first letter of the AnyoneRead order
    string; its OriginalFile blob carries the source file's long name."""

    on = True
    off = False
    off_key = None
    path = "LockScreen"

    def available(self):
        return True

    def read(self):
        order_key = (r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                     rf"\SystemProtectedUserData\{_user_sid()}\AnyoneRead"
                     r"\LockScreen")
        try:
            with winreg.OpenKey(HKLM, order_key, 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                slot = winreg.QueryValueEx(k, "")[0][0]
            with winreg.OpenKey(HKCU, LOCK_USER) as k:
                blob = winreg.QueryValueEx(k, f"OriginalFile_{slot}")[0]
        except FileNotFoundError:
            # no custom picture was ever set: Spotlight or the stock image
            return False
        except PermissionError:
            return UNKNOWN
        return os.path.basename(LOCK_BLACK).encode("utf-16-le") in blob

    def is_on(self):
        return self.read() is True

    def write(self, on):
        if on:
            write_black_png(LOCK_BLACK)
            prev = set_lock_image(LOCK_BLACK)
            if prev and os.path.normcase(prev) != os.path.normcase(LOCK_BLACK):
                with winreg.CreateKeyEx(HKCU, LOCK_PREV.path) as k:
                    winreg.SetValueEx(k, LOCK_PREV.name, 0, winreg.REG_SZ, prev)
            return
        prev = LOCK_PREV.read()
        set_lock_image(prev if isinstance(prev, str) and os.path.isfile(prev)
                       else LOCK_DEFAULT)
        LOCK_PREV.write(False)


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SystemParametersInfoW.restype = wt.BOOL
_user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p,
                                          wt.UINT]
_user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
_user32.SendMessageTimeoutW.argtypes = [
    wt.HWND, wt.UINT, wt.WPARAM, ctypes.c_wchar_p, wt.UINT, wt.UINT,
    ctypes.POINTER(ctypes.c_size_t)]
_user32.SetSysColors.restype = wt.BOOL
_user32.SetSysColors.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]

# persist to the user profile and broadcast, so the change applies live
SPIF_PERSIST = filterkeys.SPIF_UPDATEINIFILE | filterkeys.SPIF_SENDCHANGE


def _spi(action, ui, pv, flags=0):
    if not _user32.SystemParametersInfoW(action, ui, pv, flags):
        raise ctypes.WinError(ctypes.get_last_error())


class SpiOp:
    """One SystemParametersInfoW setting.  via says where the SET value goes:
    "pv" in pvParam, "ui" in uiParam; GET always answers through pvParam."""

    off_key = None

    def __init__(self, get, set_, on, off, via):
        self.get = get
        self.set_ = set_
        self.on = on
        self.off = off
        self.via = via
        self.path = f"SPI 0x{set_:04X}"

    def available(self):
        return True

    def read(self):
        val = ctypes.c_uint()
        _spi(self.get, 0, ctypes.byref(val))
        return val.value

    def is_on(self):
        return self.read() == self.on

    def write(self, on):
        self._set(self.on if on else self.off)

    def _set(self, val):
        if self.via == "pv":
            _spi(self.set_, 0, val, SPIF_PERSIST)
        elif self.via == "ui":
            _spi(self.set_, val, None, SPIF_PERSIST)
        else:
            raise ValueError(self.via)


class ANIMATIONINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("iMinAnimate", ctypes.c_int)]


class AnimationOp(SpiOp):
    def __init__(self):
        super().__init__(0x0048, 0x0049, 0, 1, "struct")

    def read(self):
        info = ANIMATIONINFO(ctypes.sizeof(ANIMATIONINFO), 0)
        _spi(self.get, info.cbSize, ctypes.byref(info))
        return info.iMinAnimate

    def _set(self, val):
        info = ANIMATIONINFO(ctypes.sizeof(ANIMATIONINFO), val)
        _spi(self.set_, info.cbSize, ctypes.byref(info), SPIF_PERSIST)


HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A
SMTO_ABORTIFHUNG = 0x0002
PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def _broadcast_setting(area):
    # A hung or slow window just misses the notice (the call returns 0); the
    # registry value it announces has already been written.
    _user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, area,
                                SMTO_ABORTIFHUNG, 1000,
                                ctypes.byref(ctypes.c_size_t()))


class DarkModeOp:
    on = True
    off = False
    off_key = None
    path = PERSONALIZE
    _ops = (D(HKCU, PERSONALIZE, "AppsUseLightTheme", 0, 1),
            D(HKCU, PERSONALIZE, "SystemUsesLightTheme", 0, 1))

    def available(self):
        return True

    def read(self):
        return all(op.is_on() for op in self._ops)

    def is_on(self):
        return self.read()

    def write(self, on):
        for op in self._ops:
            op.write(on)
        _broadcast_setting("ImmersiveColorSet")


SPI_SETDESKWALLPAPER = 0x0014
COLOR_DESKTOP = 1
WALLPAPER_DEFAULT = os.path.join(os.environ["SystemRoot"],
                                 r"Web\Wallpaper\Windows\img0.jpg")


class BlackDesktopOp:
    on = True
    off = False
    off_key = None
    path = "Wallpaper"
    _wallpaper = S(HKCU, DESKTOP, "Wallpaper", "", "")
    # off leaves the desktop colour alone, so only the on value is ever written
    _color = S(HKCU, r"Control Panel\Colors", "Background", "0 0 0", "0 0 0")
    _type = D(HKCU, EXPLORER + r"\Wallpapers", "BackgroundType", 1, 0)

    def available(self):
        return True

    def read(self):
        return self._wallpaper.is_on() and self._color.is_on()

    def is_on(self):
        return self.read()

    def write(self, on):
        if on:
            if not _user32.SetSysColors(1, (ctypes.c_int * 1)(COLOR_DESKTOP),
                                        (wt.COLORREF * 1)(0)):
                raise ctypes.WinError(ctypes.get_last_error())
            self._color.write(True)
            _spi(SPI_SETDESKWALLPAPER, 0, "", SPIF_PERSIST)
        else:
            _spi(SPI_SETDESKWALLPAPER, 0, WALLPAPER_DEFAULT, SPIF_PERSIST)
        self._type.write(on)


SCREENSAVER_BLANK = os.path.join(os.environ["SystemRoot"],
                                 r"System32\scrnsave.scr")

# Microsoft "Power setting" pages (windows-hardware/customize/power-settings)
# and powercfg /aliases; the USB pair has no alias but is in powercfg /qh.
SUB_SLEEP = "{238c9fa8-0aad-41ed-83f4-97be242c8f20}"
STANDBYIDLE = "{29f6c1db-86da-48c5-9fdb-f2b67b1f44da}"
HIBERNATEIDLE = "{9d7815a6-7ee4-497e-8888-515a05f02364}"
HYBRIDSLEEP = "{94ac6d29-73ce-41a6-809f-6363ba21b47e}"
SUB_DISK = "{0012ee47-9041-4b5d-9b77-535fba8b1442}"
DISKIDLE = "{6738e2c4-e8a5-4a42-b16a-e040e769756e}"
SUB_USB = "{2a737441-1930-4402-8d77-b2bebba308a3}"
USBSUSPEND = "{48e6b7a6-50f5-4782-a5d4-53bb8f07e226}"
# every one of these is 0 when "always on": never / off / disabled
ALWAYS_ON = (
    (SUB_SLEEP, STANDBYIDLE),
    (SUB_SLEEP, HIBERNATEIDLE),
    (SUB_SLEEP, HYBRIDSLEEP),
    (SUB_DISK, DISKIDLE),
    (SUB_USB, USBSUSPEND),
)
ERROR_FILE_NOT_FOUND = 2

_VP = ctypes.c_void_p
_READ_ARGS = [_VP] * 4 + [ctypes.POINTER(wt.DWORD)]
_WRITE_ARGS = [_VP] * 4 + [wt.DWORD]
_powrprof = ctypes.WinDLL("powrprof")
_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.LocalFree.restype = _VP
_kernel32.LocalFree.argtypes = [_VP]
for _fn, _args in (
        ("PowerGetActiveScheme", [_VP, ctypes.POINTER(_VP)]),
        ("PowerSetActiveScheme", [_VP, _VP]),
        ("PowerReadACValueIndex", _READ_ARGS),
        ("PowerReadDCValueIndex", _READ_ARGS),
        ("PowerReadACDefaultIndex", _READ_ARGS),
        ("PowerReadDCDefaultIndex", _READ_ARGS),
        ("PowerWriteACValueIndex", _WRITE_ARGS),
        ("PowerWriteDCValueIndex", _WRITE_ARGS)):
    getattr(_powrprof, _fn).restype = wt.DWORD
    getattr(_powrprof, _fn).argtypes = _args


def guid(text):
    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


def _power_check(rc):
    if rc:
        raise ctypes.WinError(rc)


def _index(fn, scheme, sub, setting):
    val = wt.DWORD()
    rc = fn(None, ctypes.byref(scheme), ctypes.byref(sub),
            ctypes.byref(setting), ctypes.byref(val))
    if rc == ERROR_FILE_NOT_FOUND:
        return None
    _power_check(rc)
    return val.value


class AlwaysOnOp:
    # scheme=None means the active scheme; a "{guid}" targets that scheme
    on = True
    off = False
    off_key = None
    path = "Power Scheme"

    def __init__(self, scheme=None):
        self.scheme = scheme

    def _scheme(self):
        if self.scheme:
            return guid(self.scheme)
        out = _VP()
        _power_check(_powrprof.PowerGetActiveScheme(None, ctypes.byref(out)))
        try:
            return (ctypes.c_ubyte * 16).from_buffer_copy(
                ctypes.string_at(out.value, 16))
        finally:
            _kernel32.LocalFree(out)

    def _apply(self, scheme):
        # changes to the active scheme take effect only after this call
        _power_check(_powrprof.PowerSetActiveScheme(None, ctypes.byref(scheme)))

    def _slots(self, scheme):
        # (AC|DC, subgroup, setting, current index) for each one that exists
        for sub, setting in ALWAYS_ON:
            sub, setting = guid(sub), guid(setting)
            for tag in ("AC", "DC"):
                val = _index(getattr(_powrprof, f"PowerRead{tag}ValueIndex"),
                             scheme, sub, setting)
                if val is not None:
                    yield tag, sub, setting, val

    def available(self):
        return any(True for _ in self._slots(self._scheme()))

    def read(self):
        vals = [s[3] for s in self._slots(self._scheme())]
        return bool(vals) and all(v == 0 for v in vals)

    def is_on(self):
        return self.read()

    def write(self, on):
        scheme = self._scheme()
        for tag, sub, setting, _val in self._slots(scheme):
            val = 0
            if not on:
                # the scheme's own personality default, not Balanced's: High
                # performance must not come back sleeping after 15 minutes
                val = _index(getattr(_powrprof, f"PowerRead{tag}DefaultIndex"),
                             scheme, sub, setting)
                if val is None:
                    raise ctypes.WinError(ERROR_FILE_NOT_FOUND)
            _power_check(getattr(_powrprof, f"PowerWrite{tag}ValueIndex")(
                None, ctypes.byref(scheme), ctypes.byref(sub),
                ctypes.byref(setting), val))
        if self.scheme is None:
            self._apply(scheme)


def SHELLEXT(clsid):
    """Win11 shell-extension opt-out: an empty default value on the CLSID's
    InprocServer32 makes the shell fall back to the classic implementation.
    Reverting means removing the whole CLSID key, not just the value."""
    path = rf"Software\Classes\CLSID\{clsid}\InprocServer32"
    return S(HKCU, path, "", "", DELETE_KEY,
             off_key=rf"Software\Classes\CLSID\{clsid}")


# --------------------------------------------------------------------
#  scheduled tasks
# --------------------------------------------------------------------

def _schtasks(args):
    return subprocess.run(["schtasks", *args], creationflags=CREATE_NO_WINDOW,
                          capture_output=True, text=True, check=False)


def task_disabled(name):
    r = _schtasks(["/Query", "/TN", name, "/FO", "LIST"])
    if r.returncode:
        return None
    for line in r.stdout.splitlines():
        if line.lower().startswith("status:"):
            return line.split(":", 1)[1].strip().lower() == "disabled"
    return None


def set_task(name, disable):
    r = _schtasks(["/Change", "/TN", name,
                   "/DISABLE" if disable else "/ENABLE"])
    return r.returncode == 0


TELEMETRY_TASKS = (
    r"\Microsoft\Windows\Application Experience\Microsoft Compatibility Appraiser",
    r"\Microsoft\Windows\Application Experience\ProgramDataUpdater",
    r"\Microsoft\Windows\Application Experience\StartupAppTask",
    r"\Microsoft\Windows\Application Experience\PcaPatchDbTask",
    r"\Microsoft\Windows\Autochk\Proxy",
    r"\Microsoft\Windows\Customer Experience Improvement Program\Consolidator",
    r"\Microsoft\Windows\Customer Experience Improvement Program\UsbCeip",
    r"\Microsoft\Windows\DiskDiagnostic\Microsoft-Windows-DiskDiagnosticDataCollector",
    r"\Microsoft\Windows\Feedback\Siuf\DmClient",
    r"\Microsoft\Windows\Feedback\Siuf\DmClientOnScenarioDownload",
    r"\Microsoft\Windows\Windows Error Reporting\QueueReporting",
)


class Tweak:
    __slots__ = ("key", "tab", "section", "label", "ops", "tasks")

    def __init__(self, key, tab, section, label, ops, tasks=()):
        self.key = key
        self.tab = tab
        self.section = section
        self.label = label
        self.ops = ops
        self.tasks = tasks

    def state(self):
        """True / False, or None when this tweak touches nothing that exists
        or something this process may not read."""
        vals = []
        for op in self.ops:
            if not op.available():
                continue
            val = op.read()
            if val is UNKNOWN:
                return None
            vals.append(val == op.on)
        # ponytail: the first task that exists stands in for the whole set
        # rather than querying all of them on every refresh.
        for name in self.tasks:
            disabled = task_disabled(name)
            if disabled is not None:
                vals.append(disabled)
                break
        if not vals:
            return None
        return all(vals)

    def apply(self, on):
        """Returns the number of scheduled tasks that could not be changed."""
        for op in self.ops:
            if op.available():
                op.write(on)
        # a task this Windows build doesn't ship has nothing to change
        return sum(1 for t in self.tasks
                   if task_disabled(t) is not None and not set_task(t, on))


# --------------------------------------------------------------------
#  catalog
# --------------------------------------------------------------------

def _photo_viewer_ops():
    caps = r"SOFTWARE\Microsoft\Windows Photo Viewer\Capabilities\FileAssociations"
    exts = (".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".gif", ".bmp",
            ".tif", ".tiff", ".ico", ".wdp", ".dib")
    ops = [S(HKLM, caps, e, "PhotoViewer.FileAssoc.Tiff", DELETE) for e in exts]
    cmd = r"SOFTWARE\Classes\Applications\photoviewer.dll\shell\open\command"
    drop = r"SOFTWARE\Classes\Applications\photoviewer.dll\shell\open\DropTarget"
    ops.append(X(
        HKLM, cmd, "",
        '%SystemRoot%\\System32\\rundll32.exe "%ProgramFiles%\\Windows Photo '
        'Viewer\\PhotoViewer.dll", ImageView_Fullscreen %1',
        DELETE_KEY))
    ops.append(S(HKLM, drop, "Clsid",
                 "{FFE2A43C-56B9-4bf5-9A79-CC6D4285608A}", DELETE))
    return ops


class JsonMergeOp:
    """One JSON object kept in a single registry value that other tools may
    also edit: on merges our entries in, off removes only our keys (and the
    value itself once nothing is left). Firefox reads such a value from
    REG_SZ or REG_MULTI_SZ (WindowsGPOParser.sys.mjs), so both are read and
    REG_MULTI_SZ is written, as the policy reference gives it."""

    on = True
    off = False
    off_key = None

    def __init__(self, hive, path, name, entries):
        self.hive = hive
        self.path = path
        self.name = name
        self.entries = entries
        self._raw = RegOp(hive, path, name, None, DELETE, winreg.REG_MULTI_SZ)

    def available(self):
        return True

    def _doc(self):
        """dict, None (no value yet), or UNKNOWN (unreadable / not a JSON object)"""
        raw = self._raw.read()
        if raw is None or raw is UNKNOWN:
            return raw
        text = "\n".join(raw) if isinstance(raw, list) else str(raw)
        try:
            doc = json.loads(text)
        except ValueError:
            return UNKNOWN
        return doc if isinstance(doc, dict) else UNKNOWN

    def read(self):
        doc = self._doc()
        if doc is UNKNOWN:
            return UNKNOWN
        doc = doc or {}
        return all(doc.get(k) == v for k, v in self.entries.items())

    def is_on(self):
        return self.read() is True

    def write(self, on):
        doc = self._doc()
        if doc is UNKNOWN:
            raise OSError(errno.EINVAL,
                          f"{self.name} is not a readable JSON object", self.path)
        doc = doc or {}
        if on:
            doc.update(self.entries)
        else:
            for k in self.entries:
                doc.pop(k, None)
        if not doc:
            self._raw._del_value()
            return
        with winreg.CreateKeyEx(
            self.hive, self.path, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
        ) as k:
            winreg.SetValueEx(k, self.name, 0, winreg.REG_MULTI_SZ,
                              [json.dumps(doc, separators=(",", ":"))])


FIREFOX_POL = r"SOFTWARE\Policies\Mozilla\Firefox"
UBLOCK_ID = "uBlock0@raymondhill.net"
_NEWTAB = "browser.newtabpage.activity-stream."


def firefox_ops(root=FIREFOX_POL, hive=HKLM):
    """Firefox Clean Setup as enterprise policy under root (a scratch key in
    tests). Names and registry forms: https://firefox-admin-docs.mozilla.org
    /reference/policies/ (SearchEngines, FirefoxHome, ExtensionSettings,
    Preferences; Windows GPO sections). SearchEngines is available on release
    Firefox since 139 (ESR since 60); FirefoxHome Pocket/SponsoredPocket are
    the pre-141 names of Stories/SponsoredStories (same prefs) and Snippets has
    been a no-op since 122, kept for older builds.
    FirefoxHome\\Weather only exists from Firefox 152, so weather and the
    logo go through the Preferences policy (Status "default" = the user can
    still change them). The pref names are those the FirefoxHome handler sets
    in Policies.sys.mjs (showWeather, widgets.weather.enabled) and the newtab
    PREFS_CONFIG entry "Show the logo and wordmark" (logowordmark.alwaysVisible,
    bugzilla 1688189); browser.* is on the Preferences policy's allow-list."""
    home = root + r"\FirefoxHome"
    ops = [
        S(hive, root + r"\SearchEngines", "Default", "DuckDuckGo", DELETE),
        D(hive, home, "Search", 1, DELETE),
    ]
    ops += [D(hive, home, name, 0, DELETE) for name in (
        "TopSites", "SponsoredTopSites", "Highlights", "Pocket", "Stories",
        "SponsoredPocket", "SponsoredStories", "Snippets", "Locked")]
    ops.append(JsonMergeOp(hive, root, "ExtensionSettings", {UBLOCK_ID: {
        "installation_mode": "normal_installed",
        "install_url": "https://addons.mozilla.org/firefox/downloads/latest/"
                       "ublock-origin/latest.xpi"}}))
    ops.append(JsonMergeOp(hive, root, "Preferences", {
        _NEWTAB + pref: {"Value": False, "Status": "default"}
        for pref in ("showWeather", "widgets.weather.enabled",
                     "logowordmark.alwaysVisible")}))
    return ops


TWEAKS = [
    # ---------------- System / Performance ----------------
    Tweak("perf", "System", "Performance", "Optimize Performance", [
        D(HKCU, EXPLORER + r"\VisualEffects", "VisualFXSetting", 2, DELETE),
        S(HKCU, DESKTOP, "DragFullWindows", "0", "1"),
        S(HKCU, DESKTOP + r"\WindowMetrics", "MinAnimate", "0", "1"),
        D(HKCU, ADVANCED, "TaskbarAnimations", 0, 1),
        D(HKCU, ADVANCED, "ListviewAlphaSelect", 0, 1),
        D(HKCU, ADVANCED, "ListviewShadow", 0, 1),
        D(HKCU, r"Software\Microsoft\Windows\DWM", "EnableAeroPeek", 0, 1),
    ]),
    Tweak("menudelay", "System", "Performance", "Remove menus delay", [
        S(HKCU, DESKTOP, "MenuShowDelay", "0", "400"),
    ]),
    Tweak("network", "System", "Performance", "Optimizer Network", [
        D(HKLM, r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
          "Tcp1323Opts", 1, DELETE),
        D(HKLM, r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
          "DefaultTTL", 64, DELETE),
        D(HKLM, r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
          "MaxUserPort", 65534, DELETE),
        D(HKLM, r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters",
          "TcpTimedWaitDelay", 30, DELETE),
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
          "MaxConnectionsPerServer", 10, DELETE),
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
          "MaxConnectionsPer1_0Server", 10, DELETE),
    ]),
    Tweak("utc", "System", "Performance", "Enable UTC Time", [
        D(HKLM, r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
          "RealTimeIsUniversal", 1, DELETE),
    ]),
    Tweak("modernstandby", "System", "Performance", "Disable Modern Standby", [
        D(HKLM, r"SYSTEM\CurrentControlSet\Control\Power",
          "PlatformAoAcOverride", 0, DELETE),
    ]),
    Tweak("longpaths", "System", "Performance", "Enable Long Paths", [
        D(HKLM, r"SYSTEM\CurrentControlSet\Control\FileSystem",
          "LongPathsEnabled", 1, 0),
    ]),
    Tweak("faststartup", "System", "Performance", "Disable Fast Startup", [
        D(HKLM, r"SYSTEM\CurrentControlSet\Control\Session Manager\Power",
          "HiberbootEnabled", 0, 1),
    ]),
    Tweak("killtimeout", "System", "Performance", "Faster App Shutdown", [
        S(HKCU, DESKTOP, "WaitToKillAppTimeout", "2000", DELETE),
        S(HKCU, DESKTOP, "HungAppTimeout", "2000", DELETE),
        S(HKLM, r"SYSTEM\CurrentControlSet\Control",
          "WaitToKillServiceTimeout", "2000", "5000"),
    ]),
    Tweak("alwayson", "System", "Performance", "Always On Power",
          [AlwaysOnOp()]),

    # ---------------- System / Shell ----------------
    Tweak("trayicons", "System", "Shell", "Show all notification icons", [
        D(HKCU, EXPLORER, "EnableAutoTray", 0, 1),
    ]),
    Tweak("classicexplorer", "System", "Shell", "Restore Classic File Explorer", [
        SHELLEXT("{d93ed569-3b3e-4bff-8355-3c44f6a52bb5}"),
    ]),
    Tweak("classicmenu", "System", "Shell", "Enable Classic Right-Click Menu", [
        SHELLEXT("{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}"),
    ]),
    Tweak("photoviewer", "System", "Shell", "Restore Classic Photo Viewer",
          _photo_viewer_ops()),
    Tweak("legacyprintdlg", "System", "Shell", "Restore Legacy Print Dialog", [
        D(HKCU, r"Software\Microsoft\Print\UnifiedPrintDialog",
          "PreferLegacyPrintDialog", 1, DELETE),
    ]),
    Tweak("compactmode", "System", "Shell", "Enable Compact Mode in Explorer", [
        D(HKCU, ADVANCED, "UseCompactMode", 1, 0),
    ]),
    Tweak("snapassist", "System", "Shell", "Disable Snap Assist", [
        D(HKCU, ADVANCED, "EnableSnapAssistFlyout", 0, 1),
        D(HKCU, ADVANCED, "SnapAssist", 0, 1),
        D(HKCU, ADVANCED, "EnableSnapBar", 0, 1),
    ]),
    Tweak("castdevice", "System", "Shell", "Remove Cast to Device", [
        S(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion"
                r"\Shell Extensions\Blocked",
          "{7AD84985-87B4-4a16-BE58-8B72A5B390F7}", "Play to menu", DELETE),
    ]),
    Tweak("mypeople", "System", "Shell", "Disable My People", [
        D(HKLM, POL + r"\Explorer", "HidePeopleBar", 1, DELETE),
    ]),

    # ---------------- System / Appearance ----------------
    Tweak("darkmode", "System", "Appearance", "Dark Mode", [DarkModeOp()]),
    Tweak("blackdesktop", "System", "Appearance", "Black Desktop",
          [BlackDesktopOp()]),
    Tweak("blacksignin", "System", "Appearance", "Black Sign-in Screen", [
        BlackLockScreenOp(),
    ]),
    Tweak("visualfx", "System", "Appearance", "Lean Visual Effects", [
        SpiOp(0x1042, 0x1043, 0, 1, "pv"),      # animate controls in windows
        AnimationOp(),                          # minimize / maximize
        D(HKCU, ADVANCED, "TaskbarAnimations", 0, 1),
        D(HKCU, DWM, "EnableAeroPeek", 0, 1),
        SpiOp(0x1002, 0x1003, 0, 1, "pv"),      # menu fade / slide
        SpiOp(0x1016, 0x1017, 0, 1, "pv"),      # tooltip fade / slide
        SpiOp(0x1014, 0x1015, 0, 1, "pv"),      # menu item fade out
        D(HKCU, DWM, "AlwaysHibernateThumbnails", 1, 1),
        SpiOp(0x101A, 0x101B, 0, 1, "pv"),      # pointer shadow
        SpiOp(0x1024, 0x1025, 0, 1, "pv"),      # window shadows
        D(HKCU, ADVANCED, "IconsOnly", 0, 0),
        D(HKCU, ADVANCED, "ListviewAlphaSelect", 1, 1),
        SpiOp(0x0026, 0x0025, 1, 1, "ui"),      # window contents while dragging
        SpiOp(0x1004, 0x1005, 0, 1, "pv"),      # combo box slide
        SpiOp(0x004A, 0x004B, 1, 1, "ui"),      # font smoothing
        SpiOp(0x1006, 0x1007, 0, 1, "pv"),      # list box smooth scroll
        D(HKCU, ADVANCED, "ListviewShadow", 1, 1),
        D(HKCU, EXPLORER + r"\VisualEffects", "VisualFXSetting", 3, 0),
    ]),
    Tweak("noanimations", "System", "Appearance", "All Animations Off", [
        SpiOp(0x1042, 0x1043, 0, 1, "pv"),      # Accessibility > Animation effects
        AnimationOp(),                          # minimize / maximize
        D(HKCU, ADVANCED, "TaskbarAnimations", 0, 1),
        SpiOp(0x1002, 0x1003, 0, 1, "pv"),      # menu fade / slide
        SpiOp(0x1016, 0x1017, 0, 1, "pv"),      # tooltip fade / slide
        SpiOp(0x1014, 0x1015, 0, 1, "pv"),      # menu item fade out
        SpiOp(0x1004, 0x1005, 0, 1, "pv"),      # combo box slide
        SpiOp(0x1006, 0x1007, 0, 1, "pv"),      # list box smooth scroll
    ]),
    Tweak("mousemax", "System", "Appearance", "Max Mouse Speed", [
        SpiOp(0x0070, 0x0071, 20, 10, "pv"),
    ]),
    # off switches the saver off and leaves the timeout alone
    Tweak("screensaver", "System", "Appearance", "Blank Screen Saver 10 min", [
        S(HKCU, DESKTOP, "SCRNSAVE.EXE", SCREENSAVER_BLANK, DELETE),
        SpiOp(0x0010, 0x0011, 1, 0, "ui"),      # screen saver active
        SpiOp(0x000E, 0x000F, 600, 600, "ui"),  # time-out, seconds
    ]),
    Tweak("desktopicons", "System", "Appearance", "Desktop: Recycle Bin Only", [
        *[D(HKCU, HIDE_ICONS, guid, 1, DELETE) for guid in (
            "{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
            "{59031a47-3f72-44a7-89c5-5595fe6b30ee}",
            "{F02C1A0D-BE21-4350-88B0-7367FC96EF3C}",
            "{5399E694-6CE5-4D6C-8FCE-1D8870FDCBA0}",
            "{2cc5ca98-6485-489a-920e-b3e88a6ccce3}")],
        D(HKCU, HIDE_ICONS, "{645FF040-5081-101B-9F08-00AA002F954E}", 0, DELETE),
        D(HKCU, ADVANCED, "HideIcons", 0, DELETE),
    ]),

    # ---------------- System / Services ----------------
    Tweak("printsvc", "System", "Services", "Disable Print Service",
          [SVC("Spooler", off=2)]),
    Tweak("faxsvc", "System", "Services", "Disable Fax Service",
          [SVC("Fax")]),
    Tweak("sensorsvc", "System", "Services", "Disable Sensor Services",
          [SVC("SensorService"), SVC("SensrSvc"), SVC("SensorDataService")]),
    Tweak("wmpsharing", "System", "Services", "Disable Media Player Sharing",
          [SVC("WMPNetworkSvc")]),
    Tweak("homegroup", "System", "Services", "Disable HomeGroup",
          [SVC("HomeGroupListener"), SVC("HomeGroupProvider")]),

    # ---------------- System / Security ----------------
    Tweak("errorreport", "System", "Security", "Disable Error Reporting", [
        D(HKLM, r"SOFTWARE\Microsoft\Windows\Windows Error Reporting",
          "Disabled", 1, 0),
    ]),
    Tweak("compatassist", "System", "Security", "Disable Compatibility Assistant", [
        D(HKLM, POL + r"\AppCompat", "DisablePCA", 1, DELETE),
    ]),
    Tweak("smartscreen", "System", "Security", "Disable SmartScreen", [
        S(HKLM, POL + r"\System", "EnableSmartScreen", "0", DELETE),
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion\AppHost",
          "EnableWebContentEvaluation", 0, 1),
    ]),
    Tweak("stickykeys", "System", "Security", "Disable Sticky Keys", [
        S(HKCU, r"Control Panel\Accessibility\StickyKeys", "Flags", "506", "510"),
        S(HKCU, r"Control Panel\Accessibility\ToggleKeys", "Flags", "58", "62"),
    ]),
    Tweak("filterkeys", "System", "Security", "Disable Filter Keys", [
        FilterKeysOp(),
    ]),
    Tweak("tpmcheck", "System", "Security", "Disable TPM Check", [
        D(HKLM, r"SYSTEM\Setup\LabConfig", "BypassTPMCheck", 1, DELETE),
        D(HKLM, r"SYSTEM\Setup\LabConfig", "BypassSecureBootCheck", 1, DELETE),
        D(HKLM, r"SYSTEM\Setup\LabConfig", "BypassRAMCheck", 1, DELETE),
        D(HKLM, r"SYSTEM\Setup\MoSetup",
          "AllowUpgradesWithUnsupportedTPMOrCPU", 1, DELETE),
    ]),
    Tweak("vbs", "System", "Security", "Disable Virtualization Based Security", [
        D(HKLM, r"SYSTEM\CurrentControlSet\Control\DeviceGuard",
          "EnableVirtualizationBasedSecurity", 0, 1),
        D(HKLM, r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios"
                r"\HypervisorEnforcedCodeIntegrity", "Enabled", 0, 1),
    ]),
    Tweak("smb1", "System", "Security", "Disable SMBv1 Protocol", [
        D(HKLM, r"SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters",
          "SMB1", 0, DELETE),
    ]),
    Tweak("smb2", "System", "Security", "Disable SMBv2 Protocol", [
        D(HKLM, r"SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters",
          "SMB2", 0, DELETE),
    ]),

    # ---------------- Taskbar ----------------
    Tweak("taskbarleft", "Taskbar", "Taskbar", "Align Taskbar to Left", [
        D(HKCU, ADVANCED, "TaskbarAl", 0, 1),
    ]),
    # TaskbarDa and ShellFeedsTaskbarViewMode are write-protected by UCPD.sys
    # (access denied even to SYSTEM), so only the supported policy is used; it
    # also removes the taskbar weather, which is the Widgets button on 11.
    Tweak("widgets", "Taskbar", "Taskbar", "Disable Widgets", [
        D(HKLM, r"SOFTWARE\Policies\Microsoft\Dsh", "AllowNewsAndInterests",
          0, DELETE),
    ]),
    Tweak("chat", "Taskbar", "Taskbar", "Disable Chat", [
        D(HKCU, ADVANCED, "TaskbarMn", 0, 1),
        D(HKLM, POL + r"\Windows Chat", "ChatIcon", 3, DELETE),
    ]),
    Tweak("taskbarsearch", "Taskbar", "Taskbar", "Hide Taskbar Search", [
        D(HKCU, SEARCH, "SearchboxTaskbarMode", 0, 1),
    ]),
    Tweak("taskview", "Taskbar", "Taskbar", "Hide Task View Button", [
        D(HKCU, ADVANCED, "ShowTaskViewButton", 0, 1),
    ]),
    Tweak("stickers", "Taskbar", "Taskbar", "Disable Stickers", [
        D(HKLM, r"SOFTWARE\Microsoft\PolicyManager\current\device\Stickers",
          "EnableStickers", 0, 1),
    ]),
    Tweak("clockseconds", "Taskbar", "Taskbar", "Show Seconds in Clock", [
        D(HKCU, ADVANCED, "ShowSecondsInSystemClock", 1, DELETE),
    ]),
    Tweak("showdesktop", "Taskbar", "Taskbar", "Hide Show Desktop Button", [
        D(HKCU, ADVANCED, "TaskbarSd", 0, 1),
    ]),
    Tweak("endtask", "Taskbar", "Taskbar", "Enable End Task on Taskbar", [
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                r"\Advanced\TaskbarDeveloperSettings",
          "TaskbarEndTask", 1, 0),
    ]),

    # ---------------- Taskbar / Start menu ----------------
    Tweak("startads", "Taskbar", "Start menu", "Disable Start Menu Ads", [
        D(HKCU, CDM, "SystemPaneSuggestionsEnabled", 0, 1),
        D(HKCU, CDM, "SilentInstalledAppsEnabled", 0, 1),
        D(HKCU, CDM, "PreInstalledAppsEnabled", 0, 1),
        D(HKCU, CDM, "OemPreInstalledAppsEnabled", 0, 1),
        D(HKCU, CDM, "SubscribedContent-338388Enabled", 0, 1),
        D(HKCU, CDM, "ContentDeliveryAllowed", 0, 1),
        D(HKCU, CDM, "SoftLandingEnabled", 0, 1),
        D(HKCU, ADVANCED, "Start_IrisRecommendations", 0, 1),
    ]),
    Tweak("bingsearch", "Taskbar", "Start menu", "Disable Bing Search in Start", [
        D(HKCU, r"Software\Policies\Microsoft\Windows\Explorer",
          "DisableSearchBoxSuggestions", 1, DELETE),
        D(HKCU, SEARCH, "BingSearchEnabled", 0, 1),
        D(HKCU, SEARCH, "CortanaConsent", 0, DELETE),
        D(HKLM, POL + r"\Windows Search", "AllowCloudSearch", 0, DELETE),
    ]),
    Tweak("searchhighlights", "Taskbar", "Start menu", "Disable Search Highlights", [
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion\SearchSettings",
          "IsDynamicSearchBoxEnabled", 0, 1),
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Feeds\DSB",
          "ShowDynamicContent", 0, 1),
    ]),
    Tweak("recommended", "Taskbar", "Start menu", "Hide Recommended Section", [
        D(HKLM, r"SOFTWARE\Microsoft\PolicyManager\current\device\Start",
          "HideRecommendedSection", 1, 0),
        D(HKLM, POL + r"\Explorer", "HideRecommendedSection", 1, DELETE),
    ]),

    # ---------------- Taskbar / Explorer ----------------
    Tweak("fileext", "Taskbar", "Explorer", "Show File Extensions", [
        D(HKCU, ADVANCED, "HideFileExt", 0, 1),
    ]),
    Tweak("hiddenfiles", "Taskbar", "Explorer", "Show Hidden Files", [
        D(HKCU, ADVANCED, "Hidden", 1, 2),
    ]),
    Tweak("openthispc", "Taskbar", "Explorer", "Open Explorer to This PC", [
        D(HKCU, ADVANCED, "LaunchTo", 1, DELETE),
    ]),
    Tweak("quickaccessrecent", "Taskbar", "Explorer", "Disable Recent Files", [
        D(HKCU, EXPLORER, "ShowRecent", 0, 1),
    ]),
    Tweak("quickaccessfrequent", "Taskbar", "Explorer", "Disable Frequent Folders", [
        D(HKCU, EXPLORER, "ShowFrequent", 0, 1),
    ]),
    Tweak("syncads", "Taskbar", "Explorer", "Disable Sync Provider Ads", [
        D(HKCU, ADVANCED, "ShowSyncProviderNotifications", 0, 1),
    ]),
    Tweak("aeroshake", "Taskbar", "Explorer", "Disable Aero Shake", [
        D(HKCU, ADVANCED, "DisallowShaking", 1, 0),
    ]),
    Tweak("shortcutsuffix", "Taskbar", "Explorer", "Remove Shortcut Suffix", [
        B(HKCU, EXPLORER, "link", b"\x00\x00\x00\x00", DELETE),
    ]),
    # shell32 icon ID 50 is fully transparent; the often-cited imageres,197 is
    # not, which is where the black-square overlays come from.
    Tweak("shortcutarrow", "Taskbar", "Explorer", "Hide Shortcut Arrows", [
        X(HKLM, EXPLORER + r"\Shell Icons", "29",
          r"%SystemRoot%\System32\shell32.dll,-50", DELETE),
    ]),
    Tweak("storeopenwith", "Taskbar", "Explorer", "Disable Store Open With", [
        D(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer",
          "NoUseStoreOpenWith", 1, DELETE),
    ]),

    # ---------------- Privacy / Telemetry ----------------
    Tweak("telemetrysvc", "Privacy", "Telemetry", "Disable Telemetry Services", [
        D(HKLM, POL + r"\DataCollection", "AllowTelemetry", 0, DELETE),
        D(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies"
                r"\DataCollection", "AllowTelemetry", 0, DELETE),
        SVC("DiagTrack", off=2),
        SVC("dmwappushservice"),
    ]),
    Tweak("telemetrytasks", "Privacy", "Telemetry", "Disable Telemetry Tasks",
          [], tasks=TELEMETRY_TASKS),
    Tweak("enhanceprivacy", "Privacy", "Telemetry", "Enhance Privacy", [
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo",
          "Enabled", 0, 1),
        D(HKLM, POL + r"\AdvertisingInfo", "DisabledByGroupPolicy", 1, DELETE),
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Privacy",
          "TailoredExperiencesWithDiagnosticDataEnabled", 0, 1),
        D(HKLM, POL + r"\CloudContent", "DisableWindowsConsumerFeatures",
          1, DELETE),
        D(HKLM, POL + r"\DataCollection", "DoNotShowFeedbackNotifications",
          1, DELETE),
        D(HKCU, r"Software\Microsoft\Siuf\Rules", "NumberOfSIUFInPeriod",
          0, DELETE),
    ]),
    Tweak("cortana", "Privacy", "Telemetry", "Disable Cortana", [
        D(HKLM, POL + r"\Windows Search", "AllowCortana", 0, DELETE),
    ]),
    Tweak("newsinterests", "Privacy", "Telemetry", "Disable News & Interests", [
        D(HKLM, POL + r"\Windows Feeds", "EnableFeeds", 0, DELETE),
    ]),
    Tweak("copilot", "Privacy", "Telemetry", "Disable CoPilot AI", [
        D(HKCU, r"Software\Policies\Microsoft\Windows\WindowsCopilot",
          "TurnOffWindowsCopilot", 1, DELETE),
        D(HKLM, POL + r"\WindowsCopilot", "TurnOffWindowsCopilot", 1, DELETE),
        D(HKCU, ADVANCED, "ShowCopilotButton", 0, 1),
        D(HKCU, r"Software\Microsoft\Windows\Shell\Copilot",
          "IsCopilotAvailable", 0, 1),
    ]),
    Tweak("recall", "Privacy", "Telemetry", "Disable Recall AI", [
        D(HKLM, POL + r"\WindowsAI", "DisableAIDataAnalysis", 1, DELETE),
        D(HKLM, POL + r"\WindowsAI", "AllowRecallEnablement", 0, DELETE),
        D(HKLM, POL + r"\WindowsAI", "DisableClickToDo", 1, DELETE),
        D(HKLM, POL + r"\WindowsAI", "TurnOffSavingSnapshots", 1, DELETE),
        D(HKCU, r"Software\Policies\Microsoft\Windows\WindowsAI",
          "DisableAIDataAnalysis", 1, DELETE),
    ]),
    Tweak("cloudclipboard", "Privacy", "Telemetry", "Disable Cloud Clipboard", [
        D(HKLM, POL + r"\System", "AllowCrossDeviceClipboard", 0, DELETE),
    ]),
    Tweak("activityhistory", "Privacy", "Telemetry", "Disable Activity History", [
        D(HKLM, POL + r"\System", "EnableActivityFeed", 0, DELETE),
        D(HKLM, POL + r"\System", "PublishUserActivities", 0, DELETE),
        D(HKLM, POL + r"\System", "UploadUserActivities", 0, DELETE),
    ]),
    Tweak("location", "Privacy", "Telemetry", "Disable Location Tracking", [
        S(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Sensor"
                r"\Overrides\{BFA794E4-F964-4FDB-90F6-51056BFE4B44}",
          "SensorPermissionState", "0", "1"),
        D(HKLM, r"SYSTEM\CurrentControlSet\Services\lfsvc\Service"
                r"\Configuration", "Status", 0, 1, create=False),
    ]),
    Tweak("backgroundapps", "Privacy", "Telemetry", "Disable Background Apps", [
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion"
                r"\BackgroundAccessApplications", "GlobalUserDisabled", 1, 0),
        D(HKLM, POL + r"\AppPrivacy", "LetAppsRunInBackground", 2, DELETE),
    ]),

    # ---------------- Privacy / Edge ----------------
    Tweak("edgetelemetry", "Privacy", "Edge", "Disable Edge Telemetry", [
        D(HKLM, r"SOFTWARE\Policies\Microsoft\Edge",
          "MetricsReportingEnabled", 0, DELETE),
        D(HKLM, r"SOFTWARE\Policies\Microsoft\Edge",
          "PersonalizationReportingEnabled", 0, DELETE),
        D(HKLM, r"SOFTWARE\Policies\Microsoft\Edge",
          "UserFeedbackAllowed", 0, DELETE),
    ]),
    Tweak("edgediscover", "Privacy", "Edge", "Disable Edge Discover & AI", [
        D(HKLM, r"SOFTWARE\Policies\Microsoft\Edge",
          "HubsSidebarEnabled", 0, DELETE),
        D(HKLM, r"SOFTWARE\Policies\Microsoft\Edge",
          "EdgeCollectionsEnabled", 0, DELETE),
        D(HKLM, r"SOFTWARE\Policies\Microsoft\Edge",
          "CopilotPageContext", 0, DELETE),
        D(HKLM, r"SOFTWARE\Policies\Microsoft\Edge",
          "ComposeInlineEnabled", 0, DELETE),
        D(HKLM, r"SOFTWARE\Policies\Microsoft\Edge",
          "GenAILocalFoundationalModelSettings", 1, DELETE),
    ]),

    # ---------------- Privacy / Input ----------------
    Tweak("windowsink", "Privacy", "Input", "Disable Windows Ink", [
        D(HKLM, r"SOFTWARE\Policies\Microsoft\WindowsInkWorkspace",
          "AllowWindowsInkWorkspace", 0, DELETE),
    ]),
    Tweak("spellcheck", "Privacy", "Input", "Disable Spell Checking", [
        D(HKCU, r"Software\Microsoft\TabletTip\1.7", "EnableSpellchecking", 0, 1),
        D(HKCU, r"Software\Microsoft\TabletTip\1.7", "EnableAutocorrection", 0, 1),
    ]),
    Tweak("inkpersonalization", "Privacy", "Input",
          "Disable Typing Personalization", [
        D(HKCU, r"Software\Microsoft\InputPersonalization",
          "RestrictImplicitTextCollection", 1, 0),
        D(HKCU, r"Software\Microsoft\InputPersonalization",
          "RestrictImplicitInkCollection", 1, 0),
        D(HKCU, r"Software\Microsoft\InputPersonalization\TrainedDataStore",
          "HarvestContacts", 0, 1),
        D(HKCU, r"Software\Microsoft\Personalization\Settings",
          "AcceptedPrivacyPolicy", 0, 1),
    ]),

    # ---------------- Apps ----------------
    Tweak("officetelemetry", "Apps", "Apps", "Disable Office Telemetry", [
        D(HKCU, r"Software\Policies\Microsoft\Office\Common\ClientTelemetry",
          "DisableTelemetry", 1, DELETE),
        D(HKCU, r"Software\Policies\Microsoft\Office\16.0\Common",
          "qmenable", 0, DELETE),
        D(HKCU, r"Software\Policies\Microsoft\Office\16.0\Common",
          "sendcustomerdata", 0, DELETE),
        D(HKCU, r"Software\Policies\Microsoft\Office\16.0\Common",
          "updatereliabilitydata", 0, DELETE),
        D(HKCU, r"Software\Policies\Microsoft\Office\16.0\osm",
          "Enablelogging", 0, DELETE),
        D(HKCU, r"Software\Policies\Microsoft\Office\16.0\osm",
          "EnableUpload", 0, DELETE),
    ]),
    Tweak("firefoxtelemetry", "Apps", "Apps", "Disable Mozilla Firefox Telemetry", [
        D(HKLM, r"SOFTWARE\Policies\Mozilla\Firefox", "DisableTelemetry",
          1, DELETE),
    ]),
    Tweak("firefoxsetup", "Apps", "Apps", "Firefox Clean Setup", firefox_ops()),
    Tweak("chrometelemetry", "Apps", "Apps", "Disable Google Chrome Telemetry", [
        D(HKLM, r"SOFTWARE\Policies\Google\Chrome",
          "MetricsReportingEnabled", 0, DELETE),
    ]),
    Tweak("nvidiatelemetry", "Apps", "Apps", "Disable NVIDIA Telemetry", [
        D(HKLM, r"SOFTWARE\NVIDIA Corporation\NvControlPanel2\Client",
          "OptInOrOutPreference", 0, 1, create=False),
        SVC("NvTelemetryContainer", off=2),
    ]),
    Tweak("vstelemetry", "Apps", "Apps", "Disable Visual Studio Telemetry", [
        D(HKCU, r"Software\Microsoft\VisualStudio\Telemetry",
          "TurnOffSwitch", 1, DELETE),
    ]),

    # ---------------- Apps / Gaming ----------------
    Tweak("gamemode", "Apps", "Gaming", "Enable Gaming Mode", [
        D(HKCU, r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1, 0),
        D(HKCU, r"Software\Microsoft\GameBar", "AllowAutoGameMode", 1, 0),
    ]),
    Tweak("xboxlive", "Apps", "Gaming", "Disable Xbox Live", [
        SVC("XblAuthManager"), SVC("XblGameSave"),
        SVC("XboxNetApiSvc"), SVC("XboxGipSvc"),
    ]),
    Tweak("gamebar", "Apps", "Gaming", "Disable Game Bar", [
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
          "AppCaptureEnabled", 0, 1),
        D(HKCU, r"System\GameConfigStore", "GameDVR_Enabled", 0, 1),
        D(HKLM, POL + r"\GameDVR", "AllowGameDVR", 0, DELETE),
    ]),

    # ---------------- Updates ----------------
    Tweak("autoupdates", "Updates", "Windows Update", "Disable Automatic Updates", [
        D(HKLM, POL + r"\WindowsUpdate\AU", "NoAutoUpdate", 1, DELETE),
    ]),
    Tweak("storeupdates", "Updates", "Windows Update",
          "Disable Microsoft Store Updates", [
        D(HKLM, r"SOFTWARE\Policies\Microsoft\WindowsStore",
          "AutoDownload", 2, DELETE),
    ]),
    Tweak("insider", "Updates", "Windows Update", "Disable Insider Service", [
        D(HKLM, r"SOFTWARE\Microsoft\WindowsSelfHost\UI\Visibility",
          "HideInsiderPage", 1, DELETE),
        SVC("wisvc"),
    ]),
    Tweak("excludedrivers", "Updates", "Windows Update",
          "Exclude Drivers from Updates", [
        D(HKLM, POL + r"\WindowsUpdate",
          "ExcludeWUDriversInQualityUpdate", 1, DELETE),
    ]),
    Tweak("autorestart", "Updates", "Windows Update", "Disable Auto Restart", [
        D(HKLM, POL + r"\WindowsUpdate\AU",
          "NoAutoRebootWithLoggedOnUsers", 1, DELETE),
    ]),
    Tweak("deliveryopt", "Updates", "Windows Update",
          "Disable Delivery Optimization", [
        D(HKLM, POL + r"\DeliveryOptimization", "DODownloadMode", 0, DELETE),
    ]),
    Tweak("reservedstorage", "Updates", "Storage", "Disable Reserved Storage", [
        D(HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\ReserveManager",
          "ShippedWithReserves", 0, 1),
    ]),

    # ---------------- Hidden ----------------
    Tweak("verbosestatus", "Hidden", "Annoyances", "Verbose Startup Messages", [
        D(HKLM, SYS_POL, "VerboseStatus", 1, DELETE),
    ]),
    Tweak("lockscreenads", "Hidden", "Annoyances", "Disable Lock Screen Ads", [
        D(HKCU, CDM, "RotatingLockScreenOverlayEnabled", 0, 1),
        D(HKCU, CDM, "RotatingLockScreenEnabled", 0, 1),
        D(HKCU, CDM, "SubscribedContent-338387Enabled", 0, 1),
    ]),
    Tweak("scoobe", "Hidden", "Annoyances", "Disable OOBE Experience Page", [
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion"
                r"\UserProfileEngagement", "ScoobeSystemSettingEnabled", 0, 1),
        D(HKCU, CDM, "SubscribedContent-310093Enabled", 0, 1),
    ]),
    Tweak("windowstips", "Hidden", "Annoyances", "Disable Windows Tips", [
        D(HKCU, CDM, "SubscribedContent-338389Enabled", 0, 1),
        D(HKLM, POL + r"\CloudContent", "DisableSoftLanding", 1, DELETE),
    ]),
    Tweak("suggestedcontent", "Hidden", "Annoyances",
          "Disable Suggested Content in Settings", [
        D(HKCU, CDM, "SubscribedContent-338393Enabled", 0, 1),
        D(HKCU, CDM, "SubscribedContent-353694Enabled", 0, 1),
        D(HKCU, CDM, "SubscribedContent-353696Enabled", 0, 1),
    ]),
    Tweak("websearch", "Hidden", "Annoyances", "Disable Web Search Results", [
        D(HKLM, POL + r"\Windows Search", "DisableWebSearch", 1, DELETE),
        D(HKLM, POL + r"\Windows Search", "ConnectedSearchUseWeb", 0, DELETE),
    ]),
    Tweak("logonanimation", "Hidden", "Annoyances",
          "Disable First Sign-in Animation", [
        D(HKLM, SYS_POL, "EnableFirstLogonAnimation", 0, 1),
    ]),
    Tweak("maintenance", "Hidden", "Annoyances", "Disable Automatic Maintenance", [
        D(HKLM, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule"
                r"\Maintenance", "MaintenanceDisabled", 1, DELETE),
    ]),
    Tweak("autoplay", "Hidden", "Annoyances", "Disable AutoPlay", [
        D(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                r"\AutoplayHandlers", "DisableAutoplay", 1, 0),
        D(HKLM, POL + r"\Explorer", "NoDriveTypeAutoRun", 255, DELETE),
    ]),
    Tweak("lockscreencamera", "Hidden", "Annoyances", "Disable Lock Screen Camera", [
        D(HKLM, POL + r"\Personalization", "NoLockScreenCamera", 1, DELETE),
    ]),
    Tweak("hibernate", "Hidden", "Annoyances", "Disable Hibernation", [
        D(HKLM, r"SYSTEM\CurrentControlSet\Control\Power",
          "HibernateEnabled", 0, 1),
    ]),
    Tweak("mousewheelinactive", "Hidden", "Annoyances",
          "Scroll Inactive Windows", [
        D(HKCU, r"Control Panel\Desktop", "MouseWheelRouting", 2, 0),
    ]),
]

TAB_ORDER = ("System", "Taskbar", "Privacy", "Apps", "Updates", "Hidden")


def tabs():
    """[(tab_name, [(section_name, [tweak, ...]), ...]), ...] in catalog order."""
    out = []
    for tab in TAB_ORDER:
        sections = {}
        for t in TWEAKS:
            if t.tab == tab:
                sections.setdefault(t.section, []).append(t)
        out.append((tab, list(sections.items())))
    return out


def config_to_xml(items, extra=()):
    """items: iterable of (key, on_bool) -> pretty UTF-8 XML bytes.
    extra: further elements appended after the tweaks (GPU profiles)."""
    root = ET.Element("wintools", version="1")
    for key, on in items:
        ET.SubElement(root, "tweak", key=key, on="1" if on else "0")
    root.extend(extra)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    from io import BytesIO
    buf = BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def xml_to_config(data):
    """data: XML bytes/str -> list of (key, on_bool) in document order."""
    root = ET.fromstring(data)
    return [(el.get("key"), el.get("on") == "1") for el in root.findall("tweak")]


def export_config(path, extra=()):
    """Write every readable tweak's live on/off state. Returns count written."""
    items = []
    for tw in TWEAKS:
        st = tw.state()
        if st is not None:
            items.append((tw.key, st))
    with open(path, "wb") as f:
        f.write(config_to_xml(items, extra))
    return len(items)


def import_config(path):
    """Apply tweak states from an XML file. Returns (applied, skipped, failed)."""
    with open(path, "rb") as f:
        pairs = xml_to_config(f.read())
    by_key = {t.key: t for t in TWEAKS}
    applied = skipped = failed = 0
    for key, on in pairs:
        tw = by_key.get(key)
        if tw is None:
            skipped += 1
            continue
        try:
            tw.apply(on)
            applied += 1
        except OSError:
            failed += 1
    return applied, skipped, failed


COPILOT_APPX = (
    "Microsoft.Copilot",
    "Microsoft.Windows.Ai.Copilot.Provider",
    "Microsoft.549981C3F5F10",
)


def remove_copilot_appx():
    """Uninstall the Copilot AppX packages via a one-shot elevated PowerShell.
    One-way (no reversible state).  Returns True if the elevated process
    launched, False if the UAC prompt was declined."""
    lines = ["$ErrorActionPreference = 'Continue'"]
    for name in COPILOT_APPX:
        lines.append(
            f"Get-AppxPackage -Name '{name}' -AllUsers -EA SilentlyContinue | "
            f"Remove-AppxPackage -AllUsers -EA Continue")
        lines.append(
            f"Get-AppxProvisionedPackage -Online -EA SilentlyContinue | "
            f"Where-Object {{ $_.DisplayName -like '{name}' }} | "
            f"Remove-AppxProvisionedPackage -Online -EA Continue | Out-Null")
    path = os.path.join(tempfile.gettempdir(),
                        f"wintools-copilot-{uuid.uuid4().hex[:8]}.ps1")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    params = ("-NoProfile -NonInteractive -ExecutionPolicy Bypass "
              f'-WindowStyle Hidden -File "{path}"')
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "powershell.exe", params, None, 0)
    return int(rc) > 32
