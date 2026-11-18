#!/usr/bin/env python3
"""pawnio.py - user-mode client for the PawnIO driver (CreateFileW +
DeviceIoControl, no PawnIOLib.dll): request packing, driver and module
loading, the shared-bus mutexes, per-core thread pinning, and extraction of the
official signed modules from resource\\release_0_2_11.zip.

Protocol facts come from namazso/PawnIO tag 2.1.0 (the installed driver is
2.1.0.0), commit e1043d7750f501b6b0d3ac0a71bd5b9406cd17b6, and from
namazso/PawnIO.Modules tag 0.2.11, commit 52a7e536dff3e53c96917a28caac5e0fa6510696
(the zip's release).  Line numbers are from the raw files at those commits."""

import contextlib
import ctypes
import ctypes.wintypes as wt
import hashlib
import struct
import sys
import time
import winreg
import zipfile
from pathlib import Path


class PawnIOError(OSError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# ====================================================================
#  PROTOCOL  (PawnIO 2.1.0)
# ====================================================================

# PawnIO/include/pawnio_um.h L47-48: k_device_type = 41394, k_device_path =
# L"\\Device\\PawnIO".  PawnIO/src/driver.cpp L100 creates that named device with
# IoCreateDeviceSecure and registers no symbolic link in this version, so the
# Win32 name is the GLOBALROOT form of the NT path.
DEVICE_PATH = "\\\\?\\GLOBALROOT\\Device\\PawnIO"
SERVICE_NAME = "PawnIO"
DEVICE_TYPE = 41394


def ctl_code(device_type, function, method=0, access=0):
    return (device_type << 16) | (access << 14) | (function << 2) | method


# pawnio_um.h L52-54: CTL_CODE(k_device_type, 0x821 / 0x841 / 0x861,
# METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_LOAD_BINARY = ctl_code(DEVICE_TYPE, 0x821)
IOCTL_EXECUTE_FN = ctl_code(DEVICE_TYPE, 0x841)
IOCTL_VERSION = ctl_code(DEVICE_TYPE, 0x861)

# PawnIOLib/PawnIOLib.cpp L204 FN_NAME_LENGTH = 32; L232 copies the inputs to p + 32;
# L245 return_size = written / sizeof(*out).  Every cell is a 64-bit integer
# (PawnIOLib.h: const ULONG64* in, PULONG64 out).  PawnIO/src/vm.cpp L830-849
# (vm_execute_function): at least 32 input bytes, the name is NUL-terminated
# inside its 32-byte field (a full 32 bytes is rejected) and starts with "ioctl_".
FN_NAME_LEN = 32
CELL = 8
_U64 = (1 << 64) - 1

# driver.cpp L91: the device SDDL is D:P(A;;GA;;;SY)(A;;GA;;;BA), SYSTEM and
# Administrators only.  driver.cpp L152-154: FsContext is per file object and a
# second load on one handle returns STATUS_ALREADY_INITIALIZED, so every module
# gets its own handle.


def pack_execute(name, inputs):
    if not name.startswith("ioctl_"):
        raise PawnIOError(f"PawnIO: function name {name!r} must start with ioctl_")
    raw = name.encode("ascii")
    if len(raw) >= FN_NAME_LEN:
        raise PawnIOError(f"PawnIO: function name {name!r} is {len(raw)} characters, limit "
                          f"{FN_NAME_LEN - 1}")
    cells = []
    for i, v in enumerate(inputs):
        if not -(1 << 63) <= v <= _U64:
            raise PawnIOError(f"PawnIO: input {i} = {v} does not fit in 64 bits")
        cells.append(v & _U64)
    return raw.ljust(FN_NAME_LEN, b"\0") + struct.pack(f"<{len(cells)}Q", *cells)


def unpack_cells(data):
    if len(data) % CELL:
        raise PawnIOError(f"PawnIO: output length {len(data)} is not a multiple of {CELL}")
    return list(struct.unpack(f"<{len(data) // CELL}Q", data))


def unpack_version(data):
    # driver.cpp L188: IOCTL_PIO_VERSION replies with exactly one ULONG,
    # (major << 16) | (minor << 8) | patch
    if len(data) != 4:
        raise PawnIOError(f"PawnIO: version reply is {len(data)} bytes, expected 4 bytes")
    v = struct.unpack("<I", data)[0]
    return v >> 16 & 0xFFFF, v >> 8 & 0xFF, v & 0xFF


def check_blob(blob):
    # vm.cpp L718: the blob is a 4-byte signature length, the signature, the image
    if len(blob) < 4:
        raise PawnIOError(f"PawnIO: module blob is {len(blob)} bytes")
    sig_len = struct.unpack_from("<I", blob)[0]
    if sig_len > len(blob) - 4:
        raise PawnIOError(f"PawnIO: module blob signature length {sig_len} exceeds the blob")


# ====================================================================
#  MODULES  (PawnIO.Modules 0.2.11)
# ====================================================================

# Exported ioctl_* names, from the .p sources at the 0.2.11 commit (line of the
# DEFINE_IOCTL in parentheses) and cross-checked against the names inside each
# .bin by sandbox\test_pawnio.py.  Cells are 64-bit.
#   AMDFamily17.p L153 read_msr(1 in, 1 out), L174 write_msr(2, 0), L193 read_smn(1, 1)
#   RyzenSMU.p L650 resolve_pm_table(0, 2: version, base), L682 update_pm_table(0, 0),
#     L693 read_pm_table(out_size qwords, at most 512), L755 get_code_name(0, 1),
#     L768 get_smu_version(0, 1), L802 read_smu_register(1, 1),
#     L827 write_smu_register(2, 0), L848 send_smu_command(7, 6)
#   IntelMSR.p L107 read_msr(1, 1), L127 write_msr(2, 0)
#   IntelMCHBAR.p L224 read_dword(1, 1), L246 read_qword(1, 1), L268 get_mchbar_addr(0, 1)
#   SmbusPIIX4.p L528 piix4_port_sel(1, 1), L548 identity(0, 3), L585 clock_freq(1, 1),
#     L631 smbus_xfer(in 4..9, out 0..5); set_sleep_mode(1, 0) comes from
#     sleepmode.inc (included at L22)
#   SmbusI801.p L730 identity(0, 3), L762 clock_freq(1, 1), L780 write_protection(0, 1),
#     L801 smbus_xfer; set_sleep_mode as above
#   LpcIO.p L136 select_slot(1, 0), L161 find_bars(0, 0), L202 pio_inb(1, 1),
#     L221 pio_outb(2, 0), L243 superio_inb(1, 1), L261 superio_inw(1, 1),
#     L277 superio_outb(2, 0)
MODULES = {
    "AMDFamily17": ("ioctl_read_msr", "ioctl_write_msr", "ioctl_read_smn"),
    "RyzenSMU": ("ioctl_resolve_pm_table", "ioctl_update_pm_table", "ioctl_read_pm_table",
                 "ioctl_get_code_name", "ioctl_get_smu_version", "ioctl_read_smu_register",
                 "ioctl_write_smu_register", "ioctl_send_smu_command"),
    "IntelMSR": ("ioctl_read_msr", "ioctl_write_msr"),
    "IntelMCHBAR": ("ioctl_read_dword", "ioctl_read_qword", "ioctl_get_mchbar_addr"),
    "SmbusPIIX4": ("ioctl_identity", "ioctl_clock_freq", "ioctl_piix4_port_sel",
                   "ioctl_smbus_xfer", "ioctl_set_sleep_mode"),
    "SmbusI801": ("ioctl_identity", "ioctl_clock_freq", "ioctl_write_protection",
                  "ioctl_smbus_xfer", "ioctl_set_sleep_mode"),
    "LpcIO": ("ioctl_select_slot", "ioctl_find_bars", "ioctl_pio_inb", "ioctl_pio_outb",
              "ioctl_superio_inb", "ioctl_superio_inw", "ioctl_superio_outb"),
}

# The module sources ask callers to hold these named mutants (\BaseNamedObjects\ is
# the Global\ namespace): SmbusPIIX4.p / SmbusI801.p above ioctl_smbus_xfer,
# LpcIO.p above every ioctl, AMDFamily17.p above ioctl_read_smn, RyzenSMU.p above
# the mailbox ioctls.
MUTEX_SMBUS = "Global\\Access_SMBUS.HTP.Method"
MUTEX_ISABUS = "Global\\Access_ISABUS.HTP.Method"
MUTEX_PCI = "Global\\Access_PCI"

ZIP_NAME = "release_0_2_11.zip"
ZIP_SHA256 = "43608cb89bc84247fef1368a139013f7d043e17db6d6c8dfc9b46bf0905a81f4"
EXTRACT_FILES = tuple(f"{m}.bin" for m in MODULES) + ("COPYING",)


# ====================================================================
#  PACKAGING  (same resolution as winclassic.package_dir)
# ====================================================================

def _base():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def zip_path():
    return _base() / "resource" / ZIP_NAME


def resource_dir():
    path = _base() / "resource" / "pawnio"
    if not path.is_dir():
        raise FileNotFoundError(f"missing {path}")
    return path


def module_bytes(name):
    if name not in MODULES:
        raise PawnIOError(f"PawnIO: no module named {name}")
    path = resource_dir() / f"{name}.bin"
    if not path.is_file():
        raise FileNotFoundError(f"missing {path}")
    return path.read_bytes()


def verify_zip(path):
    path = Path(path)
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if got != ZIP_SHA256:
        raise PawnIOError(f"PawnIO: {path.name}: SHA256 {got} does not match {ZIP_SHA256}")


def extract_modules(zip_file=None, dest=None):
    zip_file = Path(zip_file) if zip_file else zip_path()
    verify_zip(zip_file)
    contents = {}
    with zipfile.ZipFile(zip_file) as z:
        for name in EXTRACT_FILES:
            try:
                contents[name] = z.read(name)
            except KeyError:
                raise PawnIOError(f"PawnIO: {zip_file.name} has no {name}") from None
    dest = Path(dest) if dest else _base() / "resource" / "pawnio"
    dest.mkdir(parents=True, exist_ok=True)
    for name, data in contents.items():
        (dest / name).write_bytes(data)
    return [dest / name for name in contents]


# ====================================================================
#  WIN32
# ====================================================================

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_shell = ctypes.WinDLL("shell32", use_last_error=True)

_VP = ctypes.c_void_p
_k32.CreateFileW.restype = _VP
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, _VP, wt.DWORD, wt.DWORD, _VP]
_k32.DeviceIoControl.restype = wt.BOOL
_k32.DeviceIoControl.argtypes = [_VP, wt.DWORD, _VP, wt.DWORD, _VP, wt.DWORD,
                                 ctypes.POINTER(wt.DWORD), _VP]
_k32.CloseHandle.argtypes = [_VP]
_k32.CreateMutexW.restype = _VP
_k32.CreateMutexW.argtypes = [_VP, wt.BOOL, wt.LPCWSTR]
_k32.OpenMutexW.restype = _VP
_k32.OpenMutexW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.WaitForSingleObject.restype = wt.DWORD
_k32.WaitForSingleObject.argtypes = [_VP, wt.DWORD]
_k32.ReleaseMutex.argtypes = [_VP]
_k32.GetCurrentThread.restype = _VP
_k32.SetThreadGroupAffinity.restype = wt.BOOL
_adv.OpenSCManagerW.restype = _VP
_adv.OpenSCManagerW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.DWORD]
_adv.OpenServiceW.restype = _VP
_adv.OpenServiceW.argtypes = [_VP, wt.LPCWSTR, wt.DWORD]
_adv.StartServiceW.argtypes = [_VP, wt.DWORD, _VP]
_adv.CloseServiceHandle.argtypes = [_VP]

INVALID_HANDLE = ctypes.c_void_p(-1).value
GENERIC_READ_WRITE = 0xC0000000
SHARE_ALL = 7
OPEN_EXISTING = 3
ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND, ERROR_ACCESS_DENIED = 2, 3, 5
ERROR_SERVICE_ALREADY_RUNNING, ERROR_SERVICE_DOES_NOT_EXIST = 1056, 1060
SC_MANAGER_CONNECT = 0x0001
SERVICE_QUERY_STATUS, SERVICE_START = 0x0004, 0x0010
SERVICE_STOPPED, SERVICE_START_PENDING, SERVICE_RUNNING = 1, 2, 4
STATE_NAMES = {1: "STOPPED", 2: "START_PENDING", 3: "STOP_PENDING", 4: "RUNNING",
               5: "CONTINUE_PENDING", 6: "PAUSE_PENDING", 7: "PAUSED"}
WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT = 0, 0x80, 0x102
SYNCHRONIZE, MUTEX_MODIFY_STATE = 0x00100000, 0x0001
START_WAIT_S, OPEN_RETRIES = 5.0, 40


class _ServiceStatus(ctypes.Structure):
    _fields_ = [(n, wt.DWORD) for n in (
        "dwServiceType", "dwCurrentState", "dwControlsAccepted", "dwWin32ExitCode",
        "dwServiceSpecificExitCode", "dwCheckPoint", "dwWaitHint")]


_adv.QueryServiceStatus.restype = wt.BOOL
_adv.QueryServiceStatus.argtypes = [_VP, ctypes.POINTER(_ServiceStatus)]


def _winerror(what):
    err = ctypes.get_last_error()
    return PawnIOError(f"{what}: {ctypes.FormatError(err).strip()}", err)


def is_admin():
    return bool(_shell.IsUserAnAdmin())


def _open_device():
    # PawnIOLib.cpp L150-155 (pawnio_open_nt): NtOpenFile with GENERIC_READ |
    # GENERIC_WRITE and FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
    h = _k32.CreateFileW(DEVICE_PATH, GENERIC_READ_WRITE, SHARE_ALL, None, OPEN_EXISTING, 0, None)
    if h in (None, INVALID_HANDLE):
        raise _winerror(f"CreateFileW({DEVICE_PATH})")
    return h


def _close_handle(handle):
    if not _k32.CloseHandle(handle):
        raise _winerror("CloseHandle")


def _ioctl(handle, code, data, out_size, what):
    inbuf = (ctypes.c_char * len(data)).from_buffer_copy(data) if data else None
    outbuf = ctypes.create_string_buffer(out_size) if out_size else None
    got = wt.DWORD(0)
    if not _k32.DeviceIoControl(handle, code, inbuf, len(data), outbuf, out_size,
                                ctypes.byref(got), None):
        raise _winerror(f"DeviceIoControl {what}")
    return outbuf.raw[:got.value] if outbuf else b""


@contextlib.contextmanager
def _service(name, access):
    scm = _adv.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
    if not scm:
        raise _winerror("OpenSCManagerW")
    try:
        svc = _adv.OpenServiceW(scm, name, access)
        if not svc:
            err = ctypes.get_last_error()
            if err == ERROR_SERVICE_DOES_NOT_EXIST:
                raise PawnIOError("PawnIO: driver not installed", err)
            raise _winerror(f"OpenServiceW({name})")
        try:
            yield svc
        finally:
            _adv.CloseServiceHandle(svc)
    finally:
        _adv.CloseServiceHandle(scm)


def _query(svc):
    status = _ServiceStatus()
    if not _adv.QueryServiceStatus(svc, ctypes.byref(status)):
        raise _winerror("QueryServiceStatus")
    return status


def _service_state(name=SERVICE_NAME):
    with _service(name, SERVICE_QUERY_STATUS) as svc:
        return _query(svc).dwCurrentState


def service_info():
    state = _service_state()
    key = rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
        start, image = (winreg.QueryValueEx(k, v)[0] for v in ("Start", "ImagePath"))
    try:    # PnP creates the Enum subkey only when a device node uses the service
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key + r"\Enum") as k:
            nodes = winreg.QueryValueEx(k, "Count")[0]
    except FileNotFoundError:
        nodes = 0
    return {"state": STATE_NAMES.get(state, state), "start": start, "image_path": image,
            "device_nodes": nodes}


def _start_service():
    with _service(SERVICE_NAME, SERVICE_START | SERVICE_QUERY_STATUS) as svc:
        if not _adv.StartServiceW(svc, 0, None) and \
                ctypes.get_last_error() != ERROR_SERVICE_ALREADY_RUNNING:
            raise _winerror(f"StartServiceW({SERVICE_NAME})")
        deadline = time.monotonic() + START_WAIT_S
        while True:
            status = _query(svc)
            if status.dwCurrentState == SERVICE_RUNNING:
                return
            if status.dwCurrentState != SERVICE_START_PENDING or time.monotonic() > deadline:
                state = STATE_NAMES.get(status.dwCurrentState, status.dwCurrentState)
                raise PawnIOError(f"PawnIO: service is {state} after StartServiceW "
                                  f"(exit code {status.dwWin32ExitCode})")
            time.sleep(0.05)


# ====================================================================
#  SHARED BUSES AND THREAD PINNING
# ====================================================================

@contextlib.contextmanager
def bus_lock(name, timeout_ms=10000):
    handle = _k32.CreateMutexW(None, False, name)
    if not handle:
        if ctypes.get_last_error() != ERROR_ACCESS_DENIED:
            raise _winerror(f"CreateMutexW({name})")
        # created by another account without access for us: open it for waiting
        handle = _k32.OpenMutexW(SYNCHRONIZE | MUTEX_MODIFY_STATE, False, name)
        if not handle:
            raise _winerror(f"OpenMutexW({name})")
    try:
        got = _k32.WaitForSingleObject(handle, timeout_ms)
        if got == WAIT_TIMEOUT:
            raise PawnIOError(f"WaitForSingleObject({name}): timed out after {timeout_ms} ms")
        if got not in (WAIT_OBJECT_0, WAIT_ABANDONED):
            raise _winerror(f"WaitForSingleObject({name})")
        try:
            yield
        finally:
            if not _k32.ReleaseMutex(handle):
                raise _winerror(f"ReleaseMutex({name})")
    finally:
        _k32.CloseHandle(handle)


class _GroupAffinity(ctypes.Structure):
    _fields_ = [("Mask", ctypes.c_size_t), ("Group", wt.WORD), ("Reserved", wt.WORD * 3)]


_k32.SetThreadGroupAffinity.argtypes = [_VP, ctypes.POINTER(_GroupAffinity),
                                        ctypes.POINTER(_GroupAffinity)]


@contextlib.contextmanager
def pin_thread(logical):
    # logical processor number as hwinfo numbers them: group * 64 + bit
    if logical < 0:
        raise PawnIOError(f"PawnIO: cpu {logical} is not a processor number")
    group, bit = divmod(logical, 64)
    new, old = _GroupAffinity(1 << bit, group), _GroupAffinity()
    thread = _k32.GetCurrentThread()
    if not _k32.SetThreadGroupAffinity(thread, ctypes.byref(new), ctypes.byref(old)):
        raise _winerror(f"SetThreadGroupAffinity(cpu {logical})")
    try:
        yield
    finally:
        if not _k32.SetThreadGroupAffinity(thread, ctypes.byref(old), None):
            raise _winerror(f"SetThreadGroupAffinity restore (cpu {logical})")


# ====================================================================
#  DRIVER
# ====================================================================

class Driver:
    """One open device (the version query) plus one handle per loaded module."""

    def __init__(self, start_service=True):
        if not is_admin():
            raise PawnIOError("PawnIO: administrator required")
        self._modules = []
        self._base = self._open(start_service)
        try:
            self.version = unpack_version(
                _ioctl(self._base, IOCTL_VERSION, b"", 4, "IOCTL_PIO_VERSION"))
        except BaseException:
            _close_handle(self._base)
            raise

    @staticmethod
    def _open(start_service):
        try:
            return _open_device()
        except PawnIOError as e:
            if e.code not in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
                raise
            missing = e
        state = _service_state()
        if state != SERVICE_RUNNING and start_service:
            _start_service()
            state = SERVICE_RUNNING
            for _ in range(OPEN_RETRIES):
                try:
                    return _open_device()
                except PawnIOError as e:
                    if e.code not in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
                        raise
                    time.sleep(0.05)
        raise PawnIOError(f"PawnIO: {DEVICE_PATH} not found, service "
                          f"{STATE_NAMES.get(state, state)}", missing.code)

    def load(self, blob):
        check_blob(blob)
        handle = _open_device()
        try:
            _ioctl(handle, IOCTL_LOAD_BINARY, blob, 0, "IOCTL_PIO_LOAD_BINARY")
        except BaseException:
            _close_handle(handle)
            raise
        self._modules.append(handle)
        return handle

    @staticmethod
    def execute(handle, fn, inputs, n_out):
        what = f"IOCTL_PIO_EXECUTE_FN {fn}"
        out = _ioctl(handle, IOCTL_EXECUTE_FN, pack_execute(fn, inputs), n_out * CELL, what)
        if len(out) != n_out * CELL:
            raise PawnIOError(f"DeviceIoControl {what}: returned {len(out)} bytes, "
                              f"expected {n_out * CELL}")
        return unpack_cells(out)

    def open_module(self, name):
        return Module(self, name, self.load(module_bytes(name)))

    def close(self, handle=None):
        if handle is not None:
            self._modules.remove(handle)
            _close_handle(handle)
            return
        while self._modules:
            _close_handle(self._modules.pop())
        if self._base is not None:
            base, self._base = self._base, None
            _close_handle(base)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Module:
    def __init__(self, driver, name, handle):
        self.driver, self.name, self.handle = driver, name, handle

    def call(self, fn, inputs=(), n_out=0):
        if fn not in MODULES[self.name]:
            raise PawnIOError(f"PawnIO: module {self.name} has no function {fn}")
        return self.driver.execute(self.handle, fn, list(inputs), n_out)

    def close(self):
        self.driver.close(self.handle)
