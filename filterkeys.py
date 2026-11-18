#!/usr/bin/env python3
"""filterkeys.py - the FilterKeys accessibility setting (SPI + registry).

FilterKeys carries its own repeat timing and overrides the Control Panel
keyboard rate, which is what lets the repeat go below the Windows floor -
and also what makes a stray activation look like a keyboard fault.
"""

import ctypes
import ctypes.wintypes as wt

_user32 = ctypes.WinDLL("user32", use_last_error=True)

SPI_GETFILTERKEYS = 0x0032
SPI_SETFILTERKEYS = 0x0033
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002

FKF_FILTERKEYSON = 0x0001
FKF_AVAILABLE = 0x0002
FKF_HOTKEYACTIVE = 0x0004
FKF_CONFIRMHOTKEY = 0x0008
FKF_HOTKEYSOUND = 0x0010
FKF_INDICATOR = 0x0020
FKF_CLICKON = 0x0040

# Right-Shift-held-for-eight-seconds is what silently switches FilterKeys on;
# clearing FKF_HOTKEYACTIVE is what stops it coming back.
FLAGS_DEFAULT = 126   # available, hotkey armed, FilterKeys off
FLAGS_REMOVED = 122   # available, hotkey disarmed, FilterKeys off

_user32.SystemParametersInfoW.restype = wt.BOOL
_user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p,
                                          wt.UINT]


class FILTERKEYS(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT),
        ("dwFlags", wt.DWORD),
        ("iWaitMSec", wt.DWORD),
        ("iDelayMSec", wt.DWORD),
        ("iRepeatMSec", wt.DWORD),
        ("iBounceMSec", wt.DWORD),
    ]


def _spi(action: int, fk: FILTERKEYS, flags: int) -> None:
    ok = _user32.SystemParametersInfoW(
        action, ctypes.sizeof(FILTERKEYS), ctypes.byref(fk), flags
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def read_filterkeys() -> FILTERKEYS:
    fk = FILTERKEYS()
    fk.cbSize = ctypes.sizeof(FILTERKEYS)
    _spi(SPI_GETFILTERKEYS, fk, 0)
    return fk


def write_filterkeys(fk: FILTERKEYS, persist: bool = False) -> None:
    fk.cbSize = ctypes.sizeof(FILTERKEYS)
    _spi(SPI_SETFILTERKEYS, fk,
         SPIF_SENDCHANGE | (SPIF_UPDATEINIFILE if persist else 0))


def set_filterkeys(on: bool, delay_ms: int, repeat_ms: int,
                   persist: bool = False) -> None:
    fk = FILTERKEYS()
    fk.dwFlags = (FKF_FILTERKEYSON | FKF_AVAILABLE) if on else 0
    fk.iWaitMSec = 0
    fk.iDelayMSec = delay_ms
    fk.iRepeatMSec = repeat_ms
    fk.iBounceMSec = 0
    write_filterkeys(fk, persist)


def is_removed() -> bool:
    """True when FilterKeys is off AND its activation hotkey is disarmed."""
    flags = read_filterkeys().dwFlags
    return not (flags & (FKF_FILTERKEYSON | FKF_HOTKEYACTIVE))


def set_removed(removed: bool) -> None:
    fk = read_filterkeys()
    fk.dwFlags = FLAGS_REMOVED if removed else FLAGS_DEFAULT
    write_filterkeys(fk, persist=True)


def summary():
    """(on, delay_ms, repeat_ms) for the diagnostics readout."""
    fk = read_filterkeys()
    return (bool(fk.dwFlags & FKF_FILTERKEYSON), fk.iDelayMSec, fk.iRepeatMSec)
