"""unlock.py -- enumerate and close file handles locking a target path.

Pure-Python (ctypes, no external tools). Requires administrator to see and
close handles owned by processes other than the caller.

Usage:
    python unlock.py <path> [<path> ...] [--dry-run] [--json]

Exit codes:
    0  all matching handles closed (or none needed for --dry-run)
    1  one or more closes failed
    2  no matching handles found
    3  bad arguments / target path unresolvable
    5  not running as administrator
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as w
import json
import os
import sys
from ctypes import POINTER, Structure, byref, c_void_p, sizeof

# ---------------------------------------------------------------- Win32 setup

ntdll     = ctypes.WinDLL("ntdll",    use_last_error=True)
kernel32  = ctypes.WinDLL("kernel32", use_last_error=True)
shell32   = ctypes.WinDLL("shell32",  use_last_error=True)
advapi32  = ctypes.WinDLL("advapi32", use_last_error=True)

NTSTATUS = ctypes.c_long
ULONG_PTR = ctypes.c_size_t

STATUS_SUCCESS               = 0x00000000
STATUS_INFO_LENGTH_MISMATCH  = 0xC0000004

SystemExtendedHandleInformation = 0x40

PROCESS_DUP_HANDLE                = 0x0040
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DUPLICATE_SAME_ACCESS  = 0x0002
DUPLICATE_CLOSE_SOURCE = 0x0001

FILE_TYPE_DISK = 0x0001

VOLUME_NAME_NT = 0x2

INVALID_HANDLE_VALUE = w.HANDLE(-1).value


class SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX(Structure):
    _fields_ = [
        ("Object",                c_void_p),
        ("UniqueProcessId",       ULONG_PTR),
        ("HandleValue",           ULONG_PTR),
        ("GrantedAccess",         w.ULONG),
        ("CreatorBackTraceIndex", w.USHORT),
        ("ObjectTypeIndex",       w.USHORT),
        ("HandleAttributes",      w.ULONG),
        ("Reserved",              w.ULONG),
    ]


class SYSTEM_HANDLE_INFORMATION_EX(Structure):
    _fields_ = [
        ("NumberOfHandles", ULONG_PTR),
        ("Reserved",        ULONG_PTR),
        ("Handles",         SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX * 1),
    ]


ntdll.NtQuerySystemInformation.restype  = NTSTATUS
ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_int, c_void_p, w.ULONG, POINTER(w.ULONG)]

kernel32.OpenProcess.restype  = w.HANDLE
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]

kernel32.DuplicateHandle.restype  = w.BOOL
kernel32.DuplicateHandle.argtypes = [w.HANDLE, w.HANDLE, w.HANDLE, POINTER(w.HANDLE),
                                      w.DWORD, w.BOOL, w.DWORD]

kernel32.CloseHandle.restype  = w.BOOL
kernel32.CloseHandle.argtypes = [w.HANDLE]

kernel32.GetCurrentProcess.restype = w.HANDLE

kernel32.GetFileType.restype  = w.DWORD
kernel32.GetFileType.argtypes = [w.HANDLE]

kernel32.GetFinalPathNameByHandleW.restype  = w.DWORD
kernel32.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]

kernel32.GetVolumePathNameW.restype  = w.BOOL
kernel32.GetVolumePathNameW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]

kernel32.QueryDosDeviceW.restype  = w.DWORD
kernel32.QueryDosDeviceW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]

kernel32.QueryFullProcessImageNameW.restype  = w.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, POINTER(w.DWORD)]

shell32.IsUserAnAdmin.restype = w.BOOL


_proc_cache: dict[int, tuple[str, str]] = {}
def process_info(pid: int) -> tuple[str, str]:
    """Returns (basename, full_exe_path). Fallbacks are non-empty strings."""
    if pid in _proc_cache:
        return _proc_cache[pid]
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    name, path = f"pid_{pid}", ""
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            sz = w.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, byref(sz)):
                path = buf.value
                name = os.path.basename(path)
        finally:
            kernel32.CloseHandle(h)
    _proc_cache[pid] = (name, path)
    return name, path


# ---------------------------------------------------------------- helpers

def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def win32_to_nt_path(path: str) -> str | None:
    """C:\\Users\\x\\foo.txt -> \\Device\\HarddiskVolume3\\Users\\x\\foo.txt"""
    path = os.path.abspath(path)

    mount_buf = ctypes.create_unicode_buffer(1024)
    if not kernel32.GetVolumePathNameW(path, mount_buf, 1024):
        return None
    mount = mount_buf.value                    # "C:\"
    drive = mount.rstrip("\\")                 # "C:"

    dev_buf = ctypes.create_unicode_buffer(1024)
    if not kernel32.QueryDosDeviceW(drive, dev_buf, 1024):
        return None
    device = dev_buf.value                     # "\Device\HarddiskVolumeN"

    tail = path[len(mount):].replace("/", "\\").lstrip("\\")
    return f"{device}\\{tail}" if tail else device


def enumerate_handles() -> list[SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX]:
    size = 1 << 20  # 1 MiB seed
    while True:
        buf = ctypes.create_string_buffer(size)
        need = w.ULONG(0)
        status = ntdll.NtQuerySystemInformation(
            SystemExtendedHandleInformation, buf, size, byref(need))
        if status == STATUS_SUCCESS:
            break
        if status & 0xFFFFFFFF != STATUS_INFO_LENGTH_MISMATCH:
            raise OSError(f"NtQuerySystemInformation failed: 0x{status & 0xFFFFFFFF:08X}")
        size = max(need.value + (1 << 16), size * 2)

    header = ctypes.cast(buf, POINTER(SYSTEM_HANDLE_INFORMATION_EX)).contents
    n = header.NumberOfHandles
    array_type = SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX * n
    entries_addr = ctypes.addressof(buf) + SYSTEM_HANDLE_INFORMATION_EX.Handles.offset
    return list(array_type.from_address(entries_addr))


def handle_final_nt_path(dup: w.HANDLE) -> str | None:
    """GetFinalPathNameByHandle in NT-namespace form (safe; won't hang on pipes
    because we pre-filter with GetFileType == FILE_TYPE_DISK)."""
    buf = ctypes.create_unicode_buffer(1024)
    n = kernel32.GetFinalPathNameByHandleW(dup, buf, 1024, VOLUME_NAME_NT)
    if n == 0:
        return None
    if n >= 1024:
        buf = ctypes.create_unicode_buffer(n + 1)
        n = kernel32.GetFinalPathNameByHandleW(dup, buf, n + 1, VOLUME_NAME_NT)
        if n == 0:
            return None
    return buf.value


# ---------------------------------------------------------------- core

def find_locking_handles(target_paths: list[str]) -> list[dict]:
    """Return list of {pid, handle, nt_path} matching any target."""
    targets = {}
    for p in target_paths:
        nt = win32_to_nt_path(p)
        if not nt:
            print(f"unlock: cannot resolve NT path for {p!r}", file=sys.stderr)
            continue
        targets[nt.lower()] = p
    if not targets:
        return []

    me = kernel32.GetCurrentProcess()
    matches: list[dict] = []
    proc_cache: dict[int, w.HANDLE] = {}

    try:
        for h in enumerate_handles():
            pid = int(h.UniqueProcessId)
            if pid == 0 or pid == 4:            # System/Idle: can't dup from
                continue

            proc = proc_cache.get(pid)
            if proc is None:
                proc = kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
                proc_cache[pid] = proc          # may be 0 (no access)
            if not proc:
                continue

            dup = w.HANDLE()
            ok = kernel32.DuplicateHandle(
                proc, w.HANDLE(h.HandleValue), me, byref(dup),
                0, False, DUPLICATE_SAME_ACCESS)
            if not ok or not dup.value:
                continue

            try:
                if kernel32.GetFileType(dup) != FILE_TYPE_DISK:
                    continue
                nt_name = handle_final_nt_path(dup)
                if not nt_name:
                    continue
                key = nt_name.lower()
                if key in targets:
                    pname, ppath = process_info(pid)
                    matches.append({
                        "pid":      pid,
                        "process":  pname,
                        "exe_path": ppath,
                        "handle":   int(h.HandleValue),
                        "nt_path":  nt_name,
                        "target":   targets[key],
                    })
            finally:
                kernel32.CloseHandle(dup)
    finally:
        for proc in proc_cache.values():
            if proc:
                kernel32.CloseHandle(proc)

    return matches


def close_handle_remote(pid: int, handle_value: int) -> bool:
    proc = kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    if not proc:
        return False
    try:
        dup = w.HANDLE()
        ok = kernel32.DuplicateHandle(
            proc, w.HANDLE(handle_value),
            kernel32.GetCurrentProcess(), byref(dup),
            0, False, DUPLICATE_CLOSE_SOURCE)
        if not ok:
            return False
        if dup.value:
            kernel32.CloseHandle(dup)
        return True
    finally:
        kernel32.CloseHandle(proc)


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="unlock",
        description="Close file handles locking one or more paths.")
    ap.add_argument("paths", nargs="+", help="File(s) or folder(s) to unlock.")
    ap.add_argument("--dry-run", action="store_true",
                    help="List locking handles without closing them.")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON on stdout.")
    args = ap.parse_args(argv)

    if not is_admin():
        msg = "unlock: administrator privileges required to enumerate/close handles across processes."
        if args.json:
            print(json.dumps({"error": "not_admin", "message": msg}))
        else:
            print(msg, file=sys.stderr)
        return 5

    try:
        matches = find_locking_handles(args.paths)
    except OSError as e:
        if args.json:
            print(json.dumps({"error": "enumerate_failed", "message": str(e)}))
        else:
            print(f"unlock: {e}", file=sys.stderr)
        return 3

    if not matches:
        if args.json:
            print(json.dumps({"found": 0, "closed": 0, "failed": 0, "handles": []}))
        else:
            print("unlock: no matching handles.")
        return 2

    results = []
    closed = failed = 0
    for m in matches:
        if args.dry_run:
            results.append({**m, "action": "dry_run"})
            continue
        ok = close_handle_remote(m["pid"], m["handle"])
        results.append({**m, "action": "closed" if ok else "failed"})
        if ok: closed += 1
        else:  failed += 1

    if args.json:
        print(json.dumps({
            "found":  len(matches),
            "closed": closed,
            "failed": failed,
            "handles": results,
        }))
    else:
        for r in results:
            marker = r["action"].upper()
            print(f"[{marker}] {r['process']} (pid {r['pid']}) handle=0x{r['handle']:X}  {r['nt_path']}")
        print(f"unlock: found={len(matches)} closed={closed} failed={failed}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
